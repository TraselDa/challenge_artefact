"""Tests pour l'agent Text-to-SQL.

Organisation :
- Tests unitaires  : validation SQL (sans LLM, sans DB)
- Tests d'intégration : génération SQL + exécution (nécessitent API key + DuckDB)

Les tests d'intégration sont marqués @pytest.mark.integration et
skippés automatiquement si OPENROUTER_API_KEY est absent ou si la DB
n'est pas initialisée.
"""

import os
from pathlib import Path

import pytest

from src.agents.text_to_sql.sql_guard import validate_sql

DUCKDB_PATH = Path("data/processed/edan.duckdb")

# ---------------------------------------------------------------------------
# Marqueurs
# ---------------------------------------------------------------------------

requires_api = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY non défini — test d'intégration ignoré",
)

requires_db = pytest.mark.skipif(
    not DUCKDB_PATH.exists(),
    reason=f"DuckDB non initialisé ({DUCKDB_PATH}). Lancer 'make ingest' d'abord.",
)

integration = pytest.mark.integration


# ---------------------------------------------------------------------------
# Tests unitaires — validation SQL sur des requêtes connues
# ---------------------------------------------------------------------------


class TestSQLValidation:
    """Vérifie que les requêtes SQL typiques passent les guardrails."""

    def test_rhdp_seats_query(self) -> None:
        sql = "SELECT nb_sieges FROM vw_results_by_party WHERE parti = 'RHDP'"
        result = validate_sql(sql)
        assert result is not None
        assert "LIMIT" in result.upper()

    def test_top_candidates_by_region(self) -> None:
        sql = """
        SELECT candidat, parti, scores, score_pct
        FROM results
        WHERE region ILIKE '%AGNEBY%'
        ORDER BY scores DESC
        LIMIT 10
        """
        result = validate_sql(sql)
        assert "LIMIT" in result.upper()

    def test_participation_by_region(self) -> None:
        sql = """
        SELECT region, AVG(taux_participation) AS taux_moyen
        FROM vw_turnout
        GROUP BY region
        ORDER BY taux_moyen DESC
        LIMIT 50
        """
        result = validate_sql(sql)
        assert result is not None

    def test_elus_by_party_chart(self) -> None:
        sql = """
        SELECT parti, nb_sieges
        FROM vw_results_by_party
        WHERE nb_sieges > 0
        ORDER BY nb_sieges DESC
        LIMIT 50
        """
        result = validate_sql(sql)
        assert result is not None

    def test_winner_in_circonscription_001(self) -> None:
        sql = """
        SELECT candidat, parti, scores, score_pct
        FROM vw_winners
        WHERE numero_circonscription = 1
        LIMIT 1
        """
        result = validate_sql(sql)
        assert result is not None

    def test_national_participation_rate(self) -> None:
        sql = "SELECT taux_participation FROM summary_national LIMIT 1"
        result = validate_sql(sql)
        assert result is not None

    def test_list_all_parties(self) -> None:
        sql = """
        SELECT parti, nb_candidats, nb_sieges
        FROM vw_results_by_party
        ORDER BY nb_sieges DESC
        LIMIT 100
        """
        result = validate_sql(sql)
        assert result is not None

    def test_count_independent_candidates(self) -> None:
        sql = "SELECT nb_candidats FROM vw_results_by_party WHERE parti = 'INDEPENDANT' LIMIT 1"
        result = validate_sql(sql)
        assert result is not None

    def test_query_with_ilike_accent_insensitive(self) -> None:
        """Les recherches avec ILIKE doivent rester valides."""
        sql = """
        SELECT candidat, parti, scores
        FROM results
        WHERE candidat ILIKE '%konan%'
        ORDER BY scores DESC
        LIMIT 20
        """
        result = validate_sql(sql)
        assert result is not None

    def test_query_with_group_and_having(self) -> None:
        sql = """
        SELECT parti, COUNT(*) AS nb_candidats, SUM(scores) AS total_voix
        FROM results
        GROUP BY parti
        HAVING COUNT(*) > 5
        ORDER BY total_voix DESC
        LIMIT 30
        """
        result = validate_sql(sql)
        assert result is not None


# ---------------------------------------------------------------------------
# Tests d'intégration — agent TextToSQL complet
# ---------------------------------------------------------------------------


@integration
@requires_api
@requires_db
class TestTextToSQLIntegration:
    """
    Tests end-to-end : question FR → SQL généré → exécution DuckDB → résultat.
    Ces tests appellent l'API Claude et exécutent sur la vraie base de données.
    """

    @pytest.fixture(scope="class")
    def agent(self):
        """Instance de l'agent Text-to-SQL."""
        from src.agents.text_to_sql.agent import TextToSQLAgent

        return TextToSQLAgent(db_path=str(DUCKDB_PATH))

    def test_l1_001_rhdp_seats(self, agent) -> None:
        """Level 1 — Combien de sièges a gagné le RHDP ?"""
        result = agent.answer("Combien de sièges a gagné le RHDP ?")
        assert result is not None
        assert result.sql is not None
        # Le SQL doit cibler vw_results_by_party ou results + WHERE RHDP
        assert any(
            keyword in result.sql.upper()
            for keyword in ["RHDP", "PARTI"]
        ), f"SQL inattendu : {result.sql}"
        # La réponse narrative doit contenir RHDP
        assert "RHDP" in result.answer

    def test_l1_002_top_candidates_agneby(self, agent) -> None:
        """Level 1 — Top 10 des candidats par score dans la région Agneby-Tiassa."""
        result = agent.answer("Top 10 des candidats par score dans la région Agneby-Tiassa.")
        assert result is not None
        assert result.sql is not None
        assert "AGNEBY" in result.sql.upper() or "AGNEBY" in result.sql
        assert "ORDER BY" in result.sql.upper()
        assert "LIMIT" in result.sql.upper()

    def test_l1_003_participation_by_region(self, agent) -> None:
        """Level 1 — Taux de participation par région."""
        result = agent.answer("Taux de participation par région.")
        assert result is not None
        assert result.sql is not None
        assert "REGION" in result.sql.upper()
        assert "TAUX_PARTICIPATION" in result.sql.upper() or "TAUX" in result.sql.upper()

    def test_l1_004_chart_elus_by_party(self, agent) -> None:
        """Level 1 — Histogramme des élus par parti (doit retourner chart_config)."""
        result = agent.answer("Histogramme des élus par parti.")
        assert result is not None
        # Le résultat doit indiquer qu'un graphique est disponible
        assert result.chart_config is not None or result.sql is not None

    def test_l1_005_winner_circonscription_001(self, agent) -> None:
        """Level 1 — Qui a gagné dans la circonscription 001 ?"""
        result = agent.answer("Qui a gagné dans la circonscription 001 ?")
        assert result is not None
        assert result.sql is not None
        assert "VW_WINNERS" in result.sql.upper() or "ELU" in result.sql.upper()
        # La réponse doit contenir un nom de candidat (non vide)
        assert len(result.answer) > 10

    def test_l1_006_national_participation(self, agent) -> None:
        """Level 1 — Quel est le taux de participation national ?"""
        result = agent.answer("Quel est le taux de participation national ?")
        assert result is not None
        assert result.sql is not None
        assert "SUMMARY_NATIONAL" in result.sql.upper() or "TAUX" in result.sql.upper()
        # La réponse doit mentionner un pourcentage proche de 35%
        assert "%" in result.answer or "35" in result.answer

    def test_l1_007_list_parties(self, agent) -> None:
        """Level 1 — Quels sont les partis représentés ?"""
        result = agent.answer("Quels sont les partis représentés ?")
        assert result is not None
        assert result.sql is not None
        assert "PARTI" in result.sql.upper()
        # La réponse doit mentionner au moins RHDP
        assert "RHDP" in result.answer

    def test_l1_008_independent_candidates(self, agent) -> None:
        """Level 1 — Nombre total de candidats indépendants."""
        result = agent.answer("Nombre total de candidats indépendants.")
        assert result is not None
        assert result.sql is not None
        assert "INDEPENDANT" in result.sql.upper()
        # La réponse doit contenir un nombre
        import re

        assert re.search(r"\d+", result.answer), (
            f"Réponse sans nombre : {result.answer}"
        )

    def test_sql_is_always_valid(self, agent) -> None:
        """Le SQL généré doit toujours passer les guardrails."""
        questions = [
            "Combien de candidats ont participé au total ?",
            "Quelle région a le plus fort taux de participation ?",
            "Top 5 des partis par nombre de sièges.",
        ]
        for question in questions:
            result = agent.answer(question)
            if result.sql:
                # Ne doit pas lever d'exception
                validated = validate_sql(result.sql)
                assert validated is not None, f"SQL invalide pour : {question!r}"

    def test_out_of_scope_returns_explanation(self, agent) -> None:
        """Une question hors-dataset doit retourner une explication, pas une erreur."""
        result = agent.answer("Quelle est la météo à Abidjan ?")
        assert result is not None
        # L'agent ne doit pas générer de SQL pour une question hors-scope
        assert result.sql is None or result.out_of_scope
        assert result.answer, "L'agent doit répondre avec une explication de refus"
