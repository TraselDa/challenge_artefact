"""Tests pour les guardrails SQL.

Couvre :
- SELECT only (blocage des DDL/DML)
- Ajout/cap du LIMIT
- Allowlist des tables et colonnes autorisées
"""

import pytest

from src.agents.text_to_sql.sql_guard import SQLGuardError, validate_sql

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_TABLES = [
    "results",
    "summary_national",
    "vw_winners",
    "vw_turnout",
    "vw_results_by_region",
    "vw_results_by_party",
    "vw_results_by_circonscription",
]


# ---------------------------------------------------------------------------
# SELECT only — blocage des opérations dangereuses
# ---------------------------------------------------------------------------


class TestSelectOnly:
    """Vérifie que seules les requêtes SELECT sont autorisées."""

    def test_valid_select(self) -> None:
        sql = "SELECT * FROM results LIMIT 10"
        result = validate_sql(sql)
        assert "SELECT" in result.upper()

    def test_rejects_drop_table(self) -> None:
        with pytest.raises(SQLGuardError, match=r"(?i)drop|dangereux|interdit"):
            validate_sql("DROP TABLE results")

    def test_rejects_drop_database(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("DROP DATABASE edan")

    def test_rejects_insert(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("INSERT INTO results VALUES ('hack', 1, 'x', 0, 0, 0, 0.0, 0, 0, 0, 0.0, 'INDEPENDANT', 'Test', 0, 0.0, FALSE)")

    def test_rejects_delete(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("DELETE FROM results")

    def test_rejects_delete_where(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("DELETE FROM results WHERE 1=1")

    def test_rejects_update(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("UPDATE results SET elu = TRUE WHERE 1=1")

    def test_rejects_create_table(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("CREATE TABLE evil (id INT)")

    def test_rejects_alter_table(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("ALTER TABLE results ADD COLUMN hack TEXT")

    def test_rejects_truncate(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("TRUNCATE TABLE results")

    def test_rejects_exec(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("EXEC xp_cmdshell('ls -la')")

    def test_rejects_execute(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("EXECUTE('DROP TABLE results')")

    def test_rejects_information_schema(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("SELECT * FROM information_schema.tables")

    def test_rejects_sql_injection_semicolon(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("SELECT * FROM results; DROP TABLE results")

    def test_rejects_inline_comment_bypass(self) -> None:
        """-- comment SQL ne doit pas permettre de contourner les gardes."""
        with pytest.raises(SQLGuardError):
            validate_sql("SELECT * FROM results LIMIT 10; -- DROP TABLE results")


# ---------------------------------------------------------------------------
# LIMIT — ajout automatique et cap à 1000
# ---------------------------------------------------------------------------


class TestLimit:
    """Vérifie la gestion automatique du LIMIT."""

    def test_adds_limit_when_missing(self) -> None:
        sql = "SELECT * FROM results"
        result = validate_sql(sql)
        assert "LIMIT" in result.upper()

    def test_default_limit_is_100(self) -> None:
        sql = "SELECT * FROM results"
        result = validate_sql(sql)
        # Le LIMIT 100 par défaut doit être présent
        assert "100" in result

    def test_keeps_existing_limit_within_bounds(self) -> None:
        sql = "SELECT * FROM results LIMIT 50"
        result = validate_sql(sql)
        assert "50" in result
        assert "LIMIT" in result.upper()

    def test_caps_limit_above_1000(self) -> None:
        sql = "SELECT * FROM results LIMIT 9999"
        result = validate_sql(sql)
        assert "9999" not in result
        assert "1000" in result

    def test_caps_limit_exactly_at_1001(self) -> None:
        sql = "SELECT * FROM results LIMIT 1001"
        result = validate_sql(sql)
        assert "1001" not in result
        assert "1000" in result

    def test_accepts_limit_exactly_1000(self) -> None:
        sql = "SELECT * FROM results LIMIT 1000"
        result = validate_sql(sql)
        assert "1000" in result

    def test_limit_in_subquery_handled(self) -> None:
        """Une requête sans LIMIT externe doit en recevoir un."""
        sql = "SELECT parti, nb_sieges FROM vw_results_by_party ORDER BY nb_sieges DESC"
        result = validate_sql(sql)
        assert "LIMIT" in result.upper()


# ---------------------------------------------------------------------------
# Allowlist — tables et colonnes autorisées
# ---------------------------------------------------------------------------


class TestAllowlist:
    """Vérifie que seules les tables documentées dans schema.md sont autorisées."""

    @pytest.mark.parametrize("table", VALID_TABLES)
    def test_valid_table(self, table: str) -> None:
        sql = f"SELECT * FROM {table} LIMIT 10"
        result = validate_sql(sql)
        assert result is not None

    def test_valid_table_results(self) -> None:
        sql = "SELECT candidat, parti, scores FROM results LIMIT 10"
        validate_sql(sql)  # Ne doit pas lever d'exception

    def test_valid_view_winners(self) -> None:
        sql = "SELECT candidat, parti, scores, score_pct FROM vw_winners LIMIT 20"
        validate_sql(sql)

    def test_valid_view_turnout(self) -> None:
        sql = "SELECT region, circonscription, taux_participation FROM vw_turnout LIMIT 30"
        validate_sql(sql)

    def test_valid_view_by_party(self) -> None:
        sql = "SELECT parti, nb_sieges FROM vw_results_by_party WHERE nb_sieges > 0 LIMIT 50"
        validate_sql(sql)

    def test_rejects_unknown_table(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("SELECT * FROM evil_table LIMIT 10")

    def test_rejects_unknown_table_hidden_in_join(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql(
                "SELECT r.candidat FROM results r "
                "JOIN secret_data s ON r.numero_circonscription = s.id LIMIT 10"
            )

    def test_rejects_sqlite_master(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("SELECT * FROM sqlite_master LIMIT 10")

    def test_rejects_pg_catalog(self) -> None:
        with pytest.raises(SQLGuardError):
            validate_sql("SELECT * FROM pg_catalog.pg_tables LIMIT 10")


# ---------------------------------------------------------------------------
# Requêtes complexes valides — s'assurent qu'on ne sur-bloque pas
# ---------------------------------------------------------------------------


class TestValidComplexQueries:
    """Des requêtes légitimes et complexes ne doivent pas être bloquées."""

    def test_group_by_with_order(self) -> None:
        sql = (
            "SELECT region, AVG(taux_participation) AS taux_moyen "
            "FROM vw_turnout "
            "GROUP BY region "
            "ORDER BY taux_moyen DESC "
            "LIMIT 20"
        )
        result = validate_sql(sql)
        assert result is not None

    def test_ilike_search(self) -> None:
        sql = (
            "SELECT candidat, parti, scores "
            "FROM results "
            "WHERE region ILIKE '%AGNEBY%' "
            "ORDER BY scores DESC "
            "LIMIT 10"
        )
        result = validate_sql(sql)
        assert result is not None

    def test_case_when_elu(self) -> None:
        sql = (
            "SELECT parti, "
            "SUM(CASE WHEN elu THEN 1 ELSE 0 END) AS nb_elus "
            "FROM results "
            "GROUP BY parti "
            "ORDER BY nb_elus DESC "
            "LIMIT 50"
        )
        result = validate_sql(sql)
        assert result is not None

    def test_summary_national(self) -> None:
        sql = "SELECT taux_participation, inscrits, votants FROM summary_national LIMIT 1"
        result = validate_sql(sql)
        assert result is not None

    def test_join_results_views(self) -> None:
        sql = (
            "SELECT r.region, r.nb_circonscriptions, p.parti, p.nb_sieges "
            "FROM vw_results_by_region r "
            "JOIN vw_results_by_party p ON TRUE "
            "LIMIT 50"
        )
        result = validate_sql(sql)
        assert result is not None
