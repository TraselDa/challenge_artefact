"""Endpoint principal de chat — POST /api/chat."""

import logging
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.router import Intent
from src.llm_client import get_token_usage, init_token_counter
from src.observability.tracer import new_tracer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

_OUT_OF_SCOPE_MSG = (
    "Cette information n'est pas disponible dans le dataset des résultats électoraux "
    "du 27 décembre 2025. Je peux uniquement répondre aux questions portant sur les "
    "élections législatives ivoiriennes de cette date."
)


class ChatRequest(BaseModel):
    """Requête de chat."""

    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


class ChartData(BaseModel):
    """Données d'un graphique Plotly sérialisé."""

    chart_json: str
    chart_type: str
    title: str


class ChatResponse(BaseModel):
    """Réponse structurée de l'endpoint de chat."""

    answer: str
    sql: str | None = None
    chart: ChartData | None = None
    sources: list[str] = []
    provenance: list[dict[str, Any]] = []
    intent: str
    latency_ms: int
    session_id: str | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None


def _resolve_clarification_answer(answer: str, options: list[str]) -> str | None:
    """Essaie de résoudre la réponse de l'utilisateur à une question de clarification.

    Tente d'abord une sélection numérique (1, 2, ...), puis un fuzzy match.

    Args:
        answer: Réponse brute de l'utilisateur.
        options: Liste des options proposées lors de la clarification.

    Returns:
        Option résolue ou None si non déterminable.
    """
    stripped = answer.strip()

    # Sélection numérique (1-based)
    try:
        idx = int(stripped) - 1
        if 0 <= idx < len(options):
            return options[idx]
    except ValueError:
        pass

    # Fuzzy match sur les options
    from src.agents.rag.normalizer import fuzzy_match
    return fuzzy_match(stripped, options, threshold=0.6)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Répond à une question sur les résultats électoraux ivoiriens.

    Pipeline:
    1. Session memory: résoudre une clarification en cours ou appliquer les choix stockés
    2. Classification de l'intent (SQL / SQL_CHART / RAG / OUT_OF_SCOPE / NEEDS_CLARIFICATION)
    3. Délégation à l'agent approprié
    4. Génération optionnelle du graphique Plotly
    5. Retour de la réponse structurée avec provenance
    """
    from src.api.main import app_state
    from src.charts.chart_generator import chart_to_json, generate_chart

    start = time.time()
    question = request.question.strip()
    _trace_id = uuid.uuid4().hex[:8]
    _tracer = new_tracer(_trace_id, request.question, session_id=request.session_id)
    init_token_counter()

    logger.info("Question [session=%s]: %s", request.session_id, question)

    # ── Session memory ────────────────────────────────────────────────────────
    session_store: dict[str, Any] = app_state.get("session_store", {})
    session: dict[str, Any] = {}
    if request.session_id:
        session = session_store.setdefault(request.session_id, {})

    pending = session.get("pending_clarification")
    entities_substituted: set[str] = set()

    if pending:
        # L'utilisateur répond peut-être à une question de clarification
        resolved = _resolve_clarification_answer(question, pending["options"])
        if resolved:
            entity = pending["entity"]
            original_q = pending["original_question"]
            # Reformuler la question originale avec l'entité résolue
            question = re.sub(re.escape(entity), resolved, original_q, flags=re.IGNORECASE)
            # Mémoriser ce choix pour les prochaines questions de la session
            session.setdefault("entity_choices", {})[entity] = resolved
            session.pop("pending_clarification", None)
            entities_substituted.add(entity)
            logger.info("Clarification résolue: %s → %s → '%s'", entity, resolved, question)
        else:
            # L'utilisateur pose une nouvelle question — abandonner la clarification en cours
            session.pop("pending_clarification", None)
            logger.info("Clarification abandonnée, nouvelle question traitée.")

    # Appliquer les choix d'entités mémorisés dans la session (pour les questions futures)
    entity_choices: dict[str, str] = session.get("entity_choices", {})
    if entity_choices:
        for entity, resolved_val in entity_choices.items():
            if entity not in entities_substituted:  # ne pas re-substituer si déjà fait ci-dessus
                new_q = re.sub(re.escape(entity), resolved_val, question, flags=re.IGNORECASE)
                if new_q != question:
                    entities_substituted.add(entity)
                    question = new_q
        if entities_substituted:
            logger.info("Substitution d'entités de session appliquée: '%s'", question)

    try:
        # ── Routing ───────────────────────────────────────────────────────────
        router_agent = app_state.get("router")
        if router_agent is None:
            raise HTTPException(status_code=503, detail="Agents non initialisés.")

        _t0 = time.time()
        routing = router_agent.route(question)
        _tracer.record("routing", (time.time() - _t0) * 1000, intent=routing.intent.value, confidence=routing.confidence)
        intent = routing.intent
        logger.info("Intent: %s (confidence=%.2f)", intent, routing.confidence)

        # ── Traitement selon l'intent ─────────────────────────────────────────
        answer = ""
        sql: str | None = None
        chart: ChartData | None = None
        sources: list[str] = []
        provenance: list[dict[str, Any]] = []
        needs_clarification = False
        clarification_question: str | None = None

        if intent == Intent.OUT_OF_SCOPE:
            answer = _OUT_OF_SCOPE_MSG

        elif intent == Intent.NEEDS_CLARIFICATION:
            # Si l'entité a déjà été substituée (session memory), passer directement au SQL
            if entities_substituted:
                sql_agent = app_state.get("sql_agent")
                if sql_agent:
                    _t0 = time.time()
                    result = sql_agent.answer(question)
                    _tracer.record("sql_agent", (time.time() - _t0) * 1000, sql_ok=result.sql is not None, error=result.error)
                    answer = result.answer
                    sql = result.sql
                    provenance = result.provenance
                    sources = [p["source_page"] for p in provenance if p.get("source_page")]
                else:
                    answer = "Agent SQL non disponible."
            else:
                # Détecter quelle entité ambiguë a déclenché la clarification
                from src.agents.router import AMBIGUOUS_ENTITIES
                detected_entity = next(
                    (e for e in AMBIGUOUS_ENTITIES if e in routing.normalized_query),
                    None,
                )

                clarifier = app_state.get("clarifier")
                if clarifier and detected_entity:
                    try:
                        clarif = clarifier.check_ambiguity(question, detected_entity)
                    except Exception as clarif_exc:
                        logger.warning("Erreur Clarifier: %s", clarif_exc)
                        clarif = None

                    if clarif and clarif.is_ambiguous and clarif.options:
                        needs_clarification = True
                        clarification_question = clarif.question
                        answer = clarification_question or "Pouvez-vous préciser ?"
                        # Stocker l'état en attente de réponse
                        if request.session_id:
                            session["pending_clarification"] = {
                                "original_question": question,
                                "entity": detected_entity,
                                "options": clarif.options,
                            }
                    else:
                        # 0 ou 1 seul match — passer directement au SQL
                        sql_agent = app_state.get("sql_agent")
                        if sql_agent:
                            _t0 = time.time()
                            result = sql_agent.answer(question)
                            _tracer.record("sql_agent", (time.time() - _t0) * 1000, sql_ok=result.sql is not None, error=result.error)
                            answer = result.answer
                            sql = result.sql
                            provenance = result.provenance
                            sources = [p["source_page"] for p in provenance if p.get("source_page")]
                        else:
                            answer = "Agent SQL non disponible."
                else:
                    needs_clarification = True
                    clarification_question = (
                        "Pourriez-vous préciser votre question ? "
                        "(ex : indiquer une région, une circonscription ou un parti spécifique)"
                    )
                    answer = clarification_question

        elif intent in (Intent.SQL, Intent.SQL_CHART):
            sql_agent = app_state.get("sql_agent")
            if sql_agent is None:
                raise HTTPException(status_code=503, detail="Agent SQL non disponible.")

            _t0 = time.time()
            result = sql_agent.answer(question)
            _tracer.record("sql_agent", (time.time() - _t0) * 1000, sql_ok=result.sql is not None, error=result.error)
            answer = result.answer
            sql = result.sql
            provenance = result.provenance
            sources = [p["source_page"] for p in provenance if p.get("source_page")]

            # Générer un graphique si SQL_CHART
            if intent == Intent.SQL_CHART and result.sql_result and result.sql_result.results:
                try:
                    if result.chart_config:
                        _t0 = time.time()
                        fig = generate_chart(result.sql_result.results, result.chart_config)
                        _tracer.record("chart_gen", (time.time() - _t0) * 1000, chart_type=result.chart_config.chart_type)
                        if fig is not None:
                            chart = ChartData(
                                chart_json=chart_to_json(fig),
                                chart_type=result.chart_config.chart_type,
                                title=result.chart_config.title,
                            )
                except Exception as chart_exc:
                    logger.warning("Erreur génération graphique: %s", chart_exc)

        elif intent == Intent.RAG:
            rag_agent = app_state.get("rag_agent")
            if rag_agent is None:
                raise HTTPException(status_code=503, detail="Agent RAG non disponible.")

            _t0 = time.time()
            result = rag_agent.answer(question, routing.normalized_query)
            _tracer.record("rag_retrieval", (time.time() - _t0) * 1000, docs_count=len(result.retrieved_docs), confidence=result.confidence)
            answer = result.answer
            sources = result.sources
            provenance = result.provenance

        else:
            # Fallback RAG
            rag_agent = app_state.get("rag_agent")
            if rag_agent:
                _t0 = time.time()
                result = rag_agent.answer(question)
                _tracer.record("rag_retrieval", (time.time() - _t0) * 1000, docs_count=len(result.retrieved_docs), confidence=result.confidence)
                answer = result.answer
                sources = result.sources
                provenance = result.provenance
            else:
                answer = "Je ne suis pas en mesure de répondre à cette question."

        latency_ms = int((time.time() - start) * 1000)
        logger.info("Réponse en %d ms (intent=%s)", latency_ms, intent)

        # ── Tracing optionnel (no-op si ENABLE_TRACING non défini) ───────────
        try:
            _tracer.flush(
                intent=intent.value,
                total_latency_ms=latency_ms,
                sql=sql,
                tokens=get_token_usage(),
            )
        except Exception:
            pass

        return ChatResponse(
            answer=answer,
            sql=sql,
            chart=chart,
            sources=sources,
            provenance=provenance,
            intent=intent.value,
            latency_ms=latency_ms,
            session_id=request.session_id,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Erreur /api/chat: %s", exc, exc_info=True)
        latency_ms = int((time.time() - start) * 1000)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur interne: {exc}",
        )
