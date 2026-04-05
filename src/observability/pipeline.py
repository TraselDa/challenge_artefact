"""Wrapper du pipeline complet — pour l'eval suite et les tests offline.

N'est PAS utilisé par l'API FastAPI (qui utilise app_state dans main.py).
Usage exclusif : tests/eval/eval_suite.py et scripts de test.
"""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Résultat unifié du pipeline — attributs attendus par eval_suite.py."""

    intent: str
    response: str
    sql: str | None = None
    sources: list[str] = field(default_factory=list)


class Pipeline:
    """Orchestrateur complet : router → agents.

    Instancie tous les agents comme le fait lifespan() dans main.py,
    mais de manière synchrone pour les scripts/tests offline.
    """

    def __init__(
        self,
        db_path: str,
        chroma_dir: str,
        model: str | None = None,
    ) -> None:
        """Initialise tous les agents.

        Args:
            db_path: Chemin vers edan.duckdb.
            chroma_dir: Répertoire de persistance ChromaDB.
            model: Identifiant du modèle (format OpenRouter). Lit LLM_MODEL si absent.
        """
        from src.agents.clarifier import Clarifier
        from src.agents.rag.agent import RAGAgent
        from src.agents.router import IntentRouter
        from src.agents.text_to_sql.agent import TextToSQLAgent

        _model = model or os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")

        self.router = IntentRouter(model=_model)
        self.sql_agent = TextToSQLAgent(db_path=db_path, model=_model)
        self.rag_agent = RAGAgent(chroma_path=chroma_dir, model=_model)
        self.clarifier = Clarifier(db_path=db_path)

        logger.info(
            "Pipeline initialisé (db=%s, chroma=%s, model=%s)",
            db_path,
            chroma_dir,
            _model,
        )

    def run(self, question: str) -> PipelineResult:
        """Exécute le pipeline complet sur une question.

        Reproduit la logique de chat.py sans la couche HTTP.

        Args:
            question: Question en français.

        Returns:
            PipelineResult avec intent, response, sql (si SQL), sources (si RAG).
        """
        from src.agents.router import AMBIGUOUS_ENTITIES, Intent

        routing = self.router.route(question)
        intent = routing.intent

        if intent == Intent.OUT_OF_SCOPE:
            return PipelineResult(
                intent=intent.value,
                response=(
                    "Cette information n'est pas disponible dans le dataset des résultats "
                    "électoraux du 27 décembre 2025."
                ),
            )

        if intent == Intent.NEEDS_CLARIFICATION:
            detected_entity = next(
                (e for e in AMBIGUOUS_ENTITIES if e in routing.normalized_query),
                None,
            )
            clarif_question = "Pouvez-vous préciser votre question ?"
            if detected_entity:
                try:
                    clarif = self.clarifier.check_ambiguity(question, detected_entity)
                    if clarif.is_ambiguous and clarif.question:
                        clarif_question = clarif.question
                except Exception as exc:
                    logger.warning("Clarifier erreur: %s", exc)
            return PipelineResult(
                intent="clarification",
                response=clarif_question,
            )

        if intent in (Intent.SQL, Intent.SQL_CHART):
            result = self.sql_agent.answer(question)
            return PipelineResult(
                intent=intent.value,
                response=result.answer,
                sql=result.sql,
            )

        # RAG (et fallback pour tout autre intent)
        result = self.rag_agent.answer(question, routing.normalized_query)
        return PipelineResult(
            intent=intent.value,
            response=result.answer,
            sources=result.sources,
        )
