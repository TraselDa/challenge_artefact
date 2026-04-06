"""Agent principal Text-to-SQL."""

import json
import logging
import os
import re
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
from openai import OpenAI

from src.agents.rag.normalizer import normalize_text
from src.agents.text_to_sql.formatter import format_results
from src.agents.text_to_sql.prompt_templates import SYSTEM_PROMPT
from src.agents.text_to_sql.sql_guard import SQLGuardError, validate_sql
from src.charts.chart_generator import ChartConfig
from src.llm_client import DEFAULT_MODEL, get_client

logger = logging.getLogger(__name__)

SQL_TIMEOUT_SECONDS = int(os.getenv("SQL_TIMEOUT_SECONDS", "10"))


def _fix_json_newlines(text: str) -> str:
    """Escape literal newlines inside JSON string values (LLM sometimes omits escaping).

    Walks the text character by character, tracking whether we're inside a JSON
    string, and replaces bare \\n / \\r with their escaped equivalents.
    """
    result: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and in_string and i + 1 < len(text):
            # Already-escaped sequence — keep as-is
            result.append(c)
            result.append(text[i + 1])
            i += 2
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
        elif in_string and c == "\n":
            result.append("\\n")
        elif in_string and c == "\r":
            result.append("\\r")
        else:
            result.append(c)
        i += 1
    return "".join(result)


def _remove_elu_from_select(sql: str) -> str:
    """Strip the `elu` column from a SELECT clause (case-insensitive).

    Handles: "SELECT a, elu, b …", "SELECT a, elu …", "SELECT elu, a …".
    Also handles multiline SQL (LLM often inserts \\n before FROM).
    Returns the original SQL unchanged if `elu` is not in the SELECT.
    """
    m_select = re.match(r"(\s*SELECT\s+)", sql, re.IGNORECASE)
    m_from = re.search(r"\bFROM\b", sql, re.IGNORECASE)
    if not m_select or not m_from:
        return sql
    select_body = sql[m_select.end():m_from.start()]
    rest = sql[m_from.start():]
    cols = [c.strip() for c in select_body.split(",")]
    filtered = [c for c in cols if c.lower().strip() != "elu"]
    if len(filtered) == len(cols):
        return sql
    return "SELECT " + ", ".join(filtered) + "\n" + rest


@dataclass
class SQLResult:
    """Résultat d'une exécution SQL."""

    sql: str
    results: list[dict[str, Any]]
    row_count: int
    columns: list[str]


@dataclass
class AgentResponse:
    """Réponse complète de l'agent Text-to-SQL."""

    answer: str
    sql: str | None = None
    sql_result: SQLResult | None = None
    chart_config: ChartConfig | None = None
    provenance: list[dict[str, Any]] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    out_of_scope: bool = False
    error: str | None = None


class TextToSQLAgent:
    """Agent qui traduit des questions en français en requêtes SQL sur DuckDB."""

    def __init__(
        self,
        db_path: str | Path,
        model: str = DEFAULT_MODEL,
    ) -> None:
        """Initialise l'agent.

        Args:
            db_path: Chemin vers edan.duckdb.
            model: Identifiant du modèle (format OpenRouter, ex: "anthropic/claude-sonnet-4-5").
        """
        self.db_path = Path(db_path)
        self.model = model
        self.client: OpenAI = get_client()
        self._entities_cache: dict[str, list[str]] | None = None

    def answer(self, question: str) -> AgentResponse:
        """Répond à une question en français sur le dataset électoral.

        Pipeline:
        1. Génère le JSON LLM avec SQL et métadonnées
        2. Si hors-scope: retourne message de refus
        3. Si clarification: retourne la question de clarification
        4. Valide le SQL via guardrails
        5. Exécute sur DuckDB (read-only, timeout)
        6. Formate la réponse narrative
        7. Construit et retourne AgentResponse

        Args:
            question: Question de l'utilisateur en français.

        Returns:
            AgentResponse avec la réponse complète.
        """
        logger.info(f"Question: {question}")

        # 1. Générer le JSON LLM
        try:
            llm_json = self._generate_sql(question)
        except Exception as e:
            error_msg = str(e)
            # Détection d'un refus poli du LLM renvoyé en texte libre (sans JSON).
            # Quand le LLM refuse hors-scope, il répond parfois en prose sans enveloppe JSON.
            # Dans ce cas on traite la réponse comme out_of_scope plutôt que comme une erreur.
            _REFUSAL_MARKERS = (
                "désolé", "desole", "ne concerne pas", "hors de mes connaissances",
                "je ne peux pas", "n'est pas disponible", "pas disponible",
                "cette question", "hors sujet", "je suis incapable",
                "cannot", "not available", "out of scope",
            )
            _NO_JSON_PREFIX = "Aucun JSON trouvé dans la réponse LLM:"
            if _NO_JSON_PREFIX in error_msg:
                raw_llm_text = error_msg[error_msg.index(_NO_JSON_PREFIX) + len(_NO_JSON_PREFIX):].lower()
                if any(marker in raw_llm_text for marker in _REFUSAL_MARKERS):
                    logger.info("LLM a refusé en texte libre (hors-scope détecté), traitement comme out_of_scope")
                    return AgentResponse(
                        answer="Cette information n'est pas disponible dans le dataset des résultats électoraux du 27 décembre 2025.",
                        out_of_scope=True,
                    )
            logger.error(f"Erreur génération LLM: {error_msg}")
            return AgentResponse(
                answer="Une erreur est survenue lors de l'analyse de votre question.",
                error=error_msg,
            )

        # 2. Hors-scope
        if llm_json.get("out_of_scope"):
            reason = llm_json.get("out_of_scope_reason", "")
            return AgentResponse(
                answer=(
                    "Cette information n'est pas disponible dans le dataset des résultats "
                    f"électoraux du 27 décembre 2025. {reason}"
                ).strip(),
                out_of_scope=True,
            )

        # 3. Clarification
        if llm_json.get("needs_clarification"):
            return AgentResponse(
                answer=llm_json.get("clarification_question", "Pouvez-vous préciser votre question ?"),
                needs_clarification=True,
                clarification_question=llm_json.get("clarification_question"),
            )

        # 4. Valider le SQL
        sql_raw = llm_json.get("sql", "")
        if not sql_raw:
            return AgentResponse(
                answer="Je n'ai pas pu générer une requête SQL pour cette question.",
                error="SQL vide généré par le LLM",
            )

        try:
            sql_validated = validate_sql(sql_raw)
        except SQLGuardError as e:
            logger.warning(f"SQL rejeté par guardrails: {e}")
            return AgentResponse(
                answer=f"La requête générée a été bloquée pour des raisons de sécurité: {e}",
                error=str(e),
            )

        # 5. Exécuter le SQL
        try:
            sql_result = self._execute_sql(sql_validated)
        except TimeoutError:
            return AgentResponse(
                answer="La requête a pris trop de temps. Essayez une question plus simple.",
                sql=sql_validated,
                error="SQL timeout",
            )
        except Exception as e:
            error_str = str(e)
            # Auto-fix: `vw_winners` has no `elu` column — strip it and retry once.
            if 'elu' in error_str.lower() and 'vw_winners' in sql_validated.lower():
                fixed_sql = _remove_elu_from_select(sql_validated)
                if fixed_sql != sql_validated:
                    logger.info("Auto-fix: suppression de la colonne `elu` de vw_winners, retry")
                    try:
                        sql_validated = fixed_sql
                        sql_result = self._execute_sql(sql_validated)
                    except Exception as e2:
                        logger.error(f"Erreur exécution SQL après auto-fix: {e2}")
                        return AgentResponse(
                            answer=f"Erreur lors de l'exécution de la requête: {e2}",
                            sql=sql_validated,
                            error=str(e2),
                        )
                else:
                    return AgentResponse(
                        answer=f"Erreur lors de l'exécution de la requête: {e}",
                        sql=sql_validated,
                        error=error_str,
                    )
            else:
                logger.error(f"Erreur exécution SQL: {e}")
                return AgentResponse(
                    answer=f"Erreur lors de l'exécution de la requête: {e}",
                    sql=sql_validated,
                    error=error_str,
                )

        # 5b. Retry avec fuzzy fix si 0 résultats
        if sql_result.row_count == 0:
            fixed_sql = self._fuzzy_fix_sql(sql_validated)
            if fixed_sql:
                try:
                    fixed_sql_validated = validate_sql(fixed_sql)
                    sql_result_fixed = self._execute_sql(fixed_sql_validated)
                    if sql_result_fixed.row_count > 0:
                        logger.info("Fuzzy retry réussi, utilisation des résultats corrigés")
                        sql_validated = fixed_sql_validated
                        sql_result = sql_result_fixed
                except Exception as e:
                    logger.warning(f"Fuzzy retry échoué: {e}")

        # 6. Formatter la réponse
        answer_text = self._format_answer(question, sql_validated, sql_result)

        # 7. Construire ChartConfig si demandé
        chart_config: ChartConfig | None = None
        if llm_json.get("intent") == "chart" or llm_json.get("chart_type"):
            chart_type = llm_json.get("chart_type") or "bar"
            chart_x = llm_json.get("chart_x") or ""
            chart_y = llm_json.get("chart_y") or ""
            chart_title = llm_json.get("chart_title") or question

            if chart_x and chart_y and sql_result.results:
                chart_config = ChartConfig(
                    chart_type=chart_type,
                    x=chart_x,
                    y=chart_y,
                    title=chart_title,
                )

        # 8. Construire la provenance
        provenance = self._build_provenance(sql_validated, sql_result)

        return AgentResponse(
            answer=answer_text,
            sql=sql_validated,
            sql_result=sql_result,
            chart_config=chart_config,
            provenance=provenance,
        )

    def _load_known_entities(self) -> dict[str, list[str]]:
        """Charge les noms de circonscriptions et régions pour le fuzzy matching (mis en cache).

        Returns:
            Dict avec clés "circonscription" et "region".
        """
        if self._entities_cache is not None:
            return self._entities_cache
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)
            circos: list[str] = conn.execute(
                "SELECT DISTINCT circonscription FROM results ORDER BY circonscription"
            ).fetchdf()["circonscription"].tolist()
            regions: list[str] = conn.execute(
                "SELECT DISTINCT region FROM results ORDER BY region"
            ).fetchdf()["region"].tolist()
            conn.close()
            self._entities_cache = {"circonscription": circos, "region": regions}
        except Exception as e:
            logger.warning(f"Impossible de charger les entités pour fuzzy matching: {e}")
            self._entities_cache = {"circonscription": [], "region": []}
        return self._entities_cache

    def _fuzzy_fix_sql(self, sql: str) -> str | None:
        """Corrige les termes ILIKE inconnus via fuzzy matching sur les entités connues.

        Gère deux cas :
        - Colonnes géographiques (region, circonscription) : corrige à la fois la valeur
          ET le nom de colonne si l'entité trouvée appartient à l'autre pool.
          Ex : `region ILIKE '%TIAPOUM%'` → `circonscription ILIKE '%TIAPOUM%'`
          car TIAPOUM est une circonscription, pas une région.
        - Autres colonnes ILIKE : corrige uniquement la valeur (comportement original).

        Retourne le SQL corrigé si au moins un terme a été amélioré, None sinon.

        Args:
            sql: Requête SQL à corriger.

        Returns:
            SQL corrigé ou None si aucun changement.
        """
        import difflib as _dl

        entities = self._load_known_entities()
        all_entities = entities["circonscription"] + entities["region"]
        if not all_entities:
            return None

        # Pattern unifié : capture optionnellement la colonne géo avant ILIKE.
        # Groupe 1 : "region" | "circonscription" | None
        # Groupe 2 : terme à l'intérieur de %…%
        pattern = re.compile(
            r"(?:\b(region|circonscription)\s+)?ILIKE\s+'%([^%']+)%'",
            re.IGNORECASE,
        )

        # Collecter les remplacements (appliqués de droite à gauche pour préserver les positions)
        replacements: list[tuple[int, int, str]] = []

        for match in pattern.finditer(sql):
            geo_col: str | None = match.group(1)   # "region" / "circonscription" / None
            term: str = match.group(2)              # terme brut dans le ILIKE
            term_norm = normalize_text(term)

            best_replacement: str | None = None
            best_score = 0.0
            best_pool: str | None = None  # "region" | "circonscription" | None

            if geo_col:
                # Colonnes géo : chercher dans les deux pools séparément pour identifier
                # à quel type appartient la meilleure entité.
                search_pools: list[tuple[str, list[str]]] = [
                    ("region", entities["region"]),
                    ("circonscription", entities["circonscription"]),
                ]
            else:
                # Colonnes non-géo : chercher dans toutes les entités (valeur seule)
                search_pools = [("all", all_entities)]

            for pool_name, pool_entities in search_pools:
                for entity in pool_entities:
                    entity_norm = normalize_text(entity)
                    score = _dl.SequenceMatcher(None, term_norm, entity_norm).ratio()
                    replacement = entity

                    # Un mot individuel peut scorer mieux qu'une entité longue.
                    # Ex: "TIAPUM" → mot "TIAPOUM" (score 0.92) vs
                    # "NOE, NOUAMOU ET TIAPOUM, COMMUNES ET SOUS-PREFECTURES" (score bas).
                    # On utilise re.findall pour exclure la ponctuation (ex: "TIAPOUM," → "TIAPOUM").
                    for word in re.findall(r"[\w'-]+", entity):
                        word_norm = normalize_text(word)
                        if len(word_norm) < 3:
                            continue
                        word_score = _dl.SequenceMatcher(None, term_norm, word_norm).ratio()
                        if word_score > score:
                            score = word_score
                            replacement = word

                    if score > best_score:
                        best_score = score
                        best_replacement = replacement
                        best_pool = None if pool_name == "all" else pool_name

            if not best_replacement or best_score < 0.6:
                continue

            value_changed = normalize_text(best_replacement) != term_norm

            if geo_col:
                column_mismatch = best_pool is not None and geo_col.lower() != best_pool.lower()
                if not (value_changed or column_mismatch):
                    continue
                new_col = best_pool if column_mismatch else geo_col
                new_expr = f"{new_col} ILIKE '%{best_replacement}%'"
                logger.info(
                    f"Fuzzy fix geo: '{match.group(0)}' → '{new_expr}' "
                    f"(score={best_score:.2f}, pool={best_pool})"
                )
            else:
                if not value_changed:
                    continue
                new_expr = f"ILIKE '%{best_replacement}%'"
                logger.info(f"Fuzzy fix ILIKE: '{term}' → '{best_replacement}' (score={best_score:.2f})")

            replacements.append((match.start(), match.end(), new_expr))

        if not replacements:
            return None

        # Appliquer de droite à gauche pour préserver les positions des autres matches
        result = sql
        for start, end, new_expr in sorted(replacements, key=lambda x: x[0], reverse=True):
            result = result[:start] + new_expr + result[end:]
        return result

    def _build_provenance(self, sql: str, sql_result: SQLResult) -> list[dict[str, Any]]:
        """Construit la provenance depuis les résultats SQL.

        Stratégie en 3 niveaux :
        1. Les résultats contiennent numero_circonscription → lookup direct.
        2. Sinon : secondary lookup via les patterns ILIKE/= du SQL sur `results`.
        3. Cas spécial summary_national → Page 1 (ligne TOTAL).
        4. Fallback générique si aucune piste trouvable.

        Args:
            sql: Requête SQL exécutée.
            sql_result: Résultats de la requête.

        Returns:
            Liste de dicts avec row_id, table_id, source_page, excerpt, etc.
        """
        rows = sql_result.results
        if not rows:
            return []

        # ── Niveau 1 : numero_circonscription présent dans les résultats ─────
        circ_nums = list({
            int(r["numero_circonscription"])
            for r in rows
            if r.get("numero_circonscription") is not None
        })

        if circ_nums:
            return self._provenance_from_circ_nums(circ_nums, rows)

        # ── Niveau 2 : secondary lookup via patterns WHERE du SQL ─────────────
        secondary = self._provenance_via_sql_filters(sql, sql_result)
        if secondary:
            return secondary

        # ── Fallback générique ────────────────────────────────────────────────
        table_match = re.search(r"\bFROM\s+(\w+)", sql, re.IGNORECASE)
        table_id = table_match.group(1) if table_match else "results"
        return [{
            "row_id": "aggregated",
            "table_id": table_id,
            "source_page": "",
            "excerpt": f"{sql_result.row_count} résultat(s) depuis `{table_id}`",
            "circonscription": None,
            "candidat": None,
            "parti": None,
        }]

    def _provenance_from_circ_nums(
        self, circ_nums: list[int], rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Construit la provenance quand numero_circonscription est dans les résultats."""
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)
            placeholders = ", ".join("?" * len(circ_nums))
            lookup_df = conn.execute(
                f"SELECT DISTINCT numero_circonscription, circonscription, region, source_page "
                f"FROM results WHERE numero_circonscription IN ({placeholders})",
                circ_nums,
            ).fetchdf()
            conn.close()
            lookup: dict[int, dict[str, Any]] = {
                int(r["numero_circonscription"]): r.to_dict()
                for _, r in lookup_df.iterrows()
            }
        except Exception as e:
            logger.warning(f"Provenance lookup DuckDB échoué: {e}")
            lookup = {}

        provenance: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        for row in rows[:10]:
            circ_num = row.get("numero_circonscription")
            candidat = str(row.get("candidat") or "")
            key = (circ_num, candidat)
            if key in seen:
                continue
            seen.add(key)

            meta = lookup.get(int(circ_num), {}) if circ_num is not None else {}
            raw_page = meta.get("source_page") or row.get("source_page")
            source_page = f"Page {int(raw_page)}" if raw_page else ""
            circonscription = str(row.get("circonscription") or meta.get("circonscription") or "")
            parti = str(row.get("parti") or "")
            scores = row.get("scores")
            score_pct = row.get("score_pct")

            parts: list[str] = []
            if candidat:
                parts.append(candidat)
            if parti:
                parts.append(f"({parti})")
            if scores is not None:
                parts.append(f"— {int(scores):,} voix".replace(",", "\u00a0"))
            if score_pct is not None:
                parts.append(f"({float(score_pct):.1f}%)")

            provenance.append({
                "row_id": f"result_{circ_num}_{candidat or circ_num}",
                "table_id": "results",
                "source_page": source_page,
                "excerpt": " ".join(parts),
                "circonscription": circonscription,
                "candidat": candidat,
                "parti": parti,
            })
        return provenance

    def _provenance_via_sql_filters(
        self, sql: str, sql_result: SQLResult
    ) -> list[dict[str, Any]]:
        """Secondary lookup : reconstruit la provenance depuis les filtres WHERE du SQL.

        Cas gérés :
        - summary_national → Page 1 (ligne TOTAL du PDF)
        - Requêtes sur views (vw_winners, etc.) avec ILIKE/= sur des colonnes connues
          → rejoue ces filtres sur `results` pour récupérer source_page et les métadonnées
        """
        # Cas spécial : summary_national (totaux nationaux = Page 1 du PDF)
        if re.search(r"\bsummary_national\b", sql, re.IGNORECASE):
            return [{
                "row_id": "summary_national_row",
                "table_id": "summary_national",
                "source_page": "Page 1",
                "excerpt": "Totaux nationaux — ligne TOTAL extraite de la page 1 du PDF",
                "circonscription": None,
                "candidat": None,
                "parti": None,
            }]

        # Extraire les conditions ILIKE et = sur les colonnes filtrables
        filterable = {"circonscription", "region", "candidat", "parti"}
        conditions: list[str] = []

        ilike_re = re.compile(
            r"\b(circonscription|region|candidat|parti)\s+ILIKE\s+('[^']*')",
            re.IGNORECASE,
        )
        for col, val in ilike_re.findall(sql):
            if col.lower() in filterable:
                conditions.append(f"{col.lower()} ILIKE {val}")

        eq_re = re.compile(
            r"\b(circonscription|region|candidat|parti)\s*=\s*('[^']*')",
            re.IGNORECASE,
        )
        for col, val in eq_re.findall(sql):
            if col.lower() in filterable:
                conditions.append(f"{col.lower()} = {val}")

        if not conditions:
            return []

        where_clause = " AND ".join(conditions)
        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)
            lookup_df = conn.execute(
                f"SELECT DISTINCT numero_circonscription, circonscription, region, "
                f"source_page, candidat, parti "
                f"FROM results WHERE {where_clause} LIMIT 5"
            ).fetchdf()
            conn.close()
        except Exception as e:
            logger.warning(f"Secondary provenance lookup échoué (where={where_clause}): {e}")
            return []

        if lookup_df.empty:
            return []

        import math

        table_match = re.search(r"\bFROM\s+(\w+)", sql, re.IGNORECASE)
        table_id = table_match.group(1) if table_match else "results"

        provenance: list[dict[str, Any]] = []
        for _, r in lookup_df.iterrows():
            raw_page = r.get("source_page")
            source_page = (
                f"Page {int(raw_page)}"
                if raw_page is not None and not (isinstance(raw_page, float) and math.isnan(raw_page))
                else ""
            )
            candidat = str(r.get("candidat") or "")
            parti = str(r.get("parti") or "")
            excerpt = f"{candidat} ({parti})" if candidat and parti else candidat or parti

            provenance.append({
                "row_id": f"result_{r['numero_circonscription']}",
                "table_id": table_id,
                "source_page": source_page,
                "excerpt": excerpt,
                "circonscription": str(r.get("circonscription") or ""),
                "candidat": candidat,
                "parti": parti,
            })
        return provenance

    def _generate_sql(self, question: str) -> dict[str, Any]:
        """Génère le JSON LLM avec SQL et métadonnées.

        Args:
            question: Question de l'utilisateur.

        Returns:
            Dictionnaire parsé depuis la réponse JSON du LLM.
        """
        from src.llm_client import chat

        text = chat(
            self.client,
            model=self.model,
            system=SYSTEM_PROMPT,
            user=question,
            max_tokens=1024,
        )
        logger.debug(f"Réponse LLM brute: {text}")

        # Extraire le JSON (peut être entouré de backticks ou de texte)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            raise ValueError(f"Aucun JSON trouvé dans la réponse LLM: {text}")

        raw = json_match.group()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # LLM sometimes embeds literal newlines in string values → escape them
            fixed = _fix_json_newlines(raw)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON invalide dans la réponse LLM: {e}\nTexte: {text}") from e

    def _execute_sql(self, sql: str) -> SQLResult:
        """Exécute le SQL validé sur DuckDB (read-only, avec timeout).

        Args:
            sql: Requête SQL validée par les guardrails.

        Returns:
            SQLResult avec les données.

        Raises:
            TimeoutError: Si la requête dépasse SQL_TIMEOUT_SECONDS.
            duckdb.Error: Si la requête SQL est invalide.
        """
        from src.cache import get_sql_cached, set_sql_cached
        cached = get_sql_cached(sql)
        if cached is not None:
            return cached

        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Base DuckDB non trouvée: {self.db_path}. Lancez `make ingest` d'abord."
            )

        def _timeout_handler(signum: int, frame: Any) -> None:
            raise TimeoutError(f"Requête SQL timeout après {SQL_TIMEOUT_SECONDS}s")

        # Configurer le timeout (SIGALRM — Unix uniquement)
        try:
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(SQL_TIMEOUT_SECONDS)
        except (AttributeError, OSError):
            # Windows ou environnement sans SIGALRM
            logger.debug("SIGALRM non disponible, exécution sans timeout")

        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)
            cursor = conn.execute(sql)
            df = cursor.fetchdf()
            columns = list(df.columns)
            results = df.to_dict(orient="records")
            conn.close()
        finally:
            try:
                signal.alarm(0)
            except (AttributeError, OSError):
                pass

        logger.info(f"SQL exécuté: {len(results)} lignes retournées")
        sql_result = SQLResult(
            sql=sql,
            results=results,
            row_count=len(results),
            columns=columns,
        )
        set_sql_cached(sql, sql_result)
        return sql_result

    def _format_answer(
        self, question: str, sql: str, sql_result: SQLResult
    ) -> str:
        """Formate la réponse narrative.

        Args:
            question: Question originale.
            sql: SQL exécuté.
            sql_result: Résultats de la requête.

        Returns:
            Réponse narrative en français.
        """
        return format_results(
            question=question,
            sql=sql,
            results=sql_result.results,
            llm_client=self.client,
            model=self.model,
        )
