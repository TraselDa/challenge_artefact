"""Validation des données après ingestion dans DuckDB."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Rapport de validation post-ingestion."""

    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    stats: dict[str, int | float | str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def print_report(self) -> None:
        """Affiche le rapport de validation dans les logs."""
        status = "✅ VALIDATION OK" if self.passed else "❌ VALIDATION ÉCHOUÉE"
        logger.info(f"\n{'='*50}\n{status}\n{'='*50}")

        logger.info("\n📊 Statistiques:")
        for key, val in self.stats.items():
            logger.info(f"  {key}: {val}")

        logger.info("\n✓ Vérifications:")
        for check, result in self.checks.items():
            icon = "✅" if result else "❌"
            logger.info(f"  {icon} {check}")

        if self.errors:
            logger.error("\n⚠️  Erreurs:")
            for err in self.errors:
                logger.error(f"  - {err}")


def validate(db_path: str | Path = "data/processed/edan.duckdb") -> ValidationReport:
    """Valide l'intégrité des données ingérées dans DuckDB.

    Args:
        db_path: Chemin vers la base DuckDB.

    Returns:
        ValidationReport avec le résultat de toutes les vérifications.
    """
    db_path = Path(db_path)
    report = ValidationReport(passed=True)

    if not db_path.exists():
        report.passed = False
        report.errors.append(f"Base DuckDB non trouvée: {db_path}")
        report.print_report()
        return report

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        _run_checks(conn, report)
        conn.close()
    except Exception as e:
        report.passed = False
        report.errors.append(f"Erreur de connexion DuckDB: {e}")

    report.print_report()
    return report


def _run_checks(conn: duckdb.DuckDBPyConnection, report: ValidationReport) -> None:
    """Exécute toutes les vérifications sur la base."""

    # 1. results non vide
    try:
        count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]  # type: ignore
        report.stats["nb_candidats_total"] = count
        ok = count > 0
        report.checks["results non vide"] = ok
        if not ok:
            report.passed = False
            report.errors.append("La table results est vide")
    except Exception as e:
        report.passed = False
        report.errors.append(f"Erreur lecture results: {e}")
        report.checks["results non vide"] = False

    # 2. summary_national a exactement 1 ligne
    try:
        count_sn = conn.execute("SELECT COUNT(*) FROM summary_national").fetchone()[0]  # type: ignore
        ok = count_sn == 1
        report.checks["summary_national = 1 ligne"] = ok
        if not ok:
            report.passed = False
            report.errors.append(f"summary_national a {count_sn} lignes (attendu: 1)")
    except Exception as e:
        report.passed = False
        report.errors.append(f"Erreur lecture summary_national: {e}")
        report.checks["summary_national = 1 ligne"] = False

    # 3. Chaque circonscription a au moins 1 élu
    try:
        circos_without_winner = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT numero_circonscription
                FROM results
                GROUP BY numero_circonscription
                HAVING SUM(CASE WHEN elu THEN 1 ELSE 0 END) = 0
            )
        """).fetchone()[0]  # type: ignore
        ok = circos_without_winner == 0
        report.checks["chaque circonscription a un élu"] = ok
        if not ok:
            report.errors.append(
                f"{circos_without_winner} circonscriptions sans élu détectées"
            )
            # Ne pas bloquer — peut être dû à une extraction imparfaite
    except Exception as e:
        report.errors.append(f"Erreur vérification élus: {e}")
        report.checks["chaque circonscription a un élu"] = False

    # 4. Pas de région NULL
    try:
        null_regions = conn.execute(
            "SELECT COUNT(*) FROM results WHERE region IS NULL OR region = ''"
        ).fetchone()[0]  # type: ignore
        ok = null_regions == 0
        report.checks["pas de région NULL"] = ok
        if not ok:
            report.passed = False
            report.errors.append(f"{null_regions} lignes avec région NULL")
    except Exception as e:
        report.passed = False
        report.errors.append(f"Erreur vérification régions: {e}")
        report.checks["pas de région NULL"] = False

    # 5. Pas de candidat NULL
    try:
        null_candidats = conn.execute(
            "SELECT COUNT(*) FROM results WHERE candidat IS NULL OR candidat = ''"
        ).fetchone()[0]  # type: ignore
        ok = null_candidats == 0
        report.checks["pas de candidat NULL"] = ok
        if not ok:
            report.passed = False
            report.errors.append(f"{null_candidats} lignes avec candidat NULL")
    except Exception as e:
        report.passed = False
        report.errors.append(f"Erreur vérification candidats: {e}")
        report.checks["pas de candidat NULL"] = False

    # 6. taux_participation entre 0 et 100
    try:
        bad_taux = conn.execute("""
            SELECT COUNT(*) FROM results
            WHERE taux_participation IS NOT NULL
              AND (taux_participation < 0 OR taux_participation > 100)
        """).fetchone()[0]  # type: ignore
        ok = bad_taux == 0
        report.checks["taux_participation dans [0, 100]"] = ok
        if not ok:
            report.errors.append(f"{bad_taux} lignes avec taux_participation hors [0,100]")
    except Exception as e:
        report.errors.append(f"Erreur vérification taux: {e}")
        report.checks["taux_participation dans [0, 100]"] = False

    # 7. Scores >= 0
    try:
        neg_scores = conn.execute(
            "SELECT COUNT(*) FROM results WHERE scores < 0"
        ).fetchone()[0]  # type: ignore
        ok = neg_scores == 0
        report.checks["scores >= 0"] = ok
        if not ok:
            report.errors.append(f"{neg_scores} lignes avec scores négatifs")
    except Exception as e:
        report.errors.append(f"Erreur vérification scores: {e}")
        report.checks["scores >= 0"] = False

    # Statistiques supplémentaires
    try:
        stats_row = conn.execute("""
            SELECT
                COUNT(DISTINCT region) AS nb_regions,
                COUNT(DISTINCT numero_circonscription) AS nb_circonscriptions,
                SUM(CASE WHEN elu THEN 1 ELSE 0 END) AS nb_elus,
                COUNT(DISTINCT parti) AS nb_partis
            FROM results
        """).fetchone()
        if stats_row:
            report.stats["nb_regions"] = stats_row[0]
            report.stats["nb_circonscriptions"] = stats_row[1]
            report.stats["nb_elus"] = stats_row[2]
            report.stats["nb_partis"] = stats_row[3]
    except Exception as e:
        logger.warning(f"Impossible de calculer les statistiques: {e}")

    # Statistiques nationales
    try:
        sn = conn.execute(
            "SELECT inscrits, votants, taux_participation FROM summary_national LIMIT 1"
        ).fetchone()
        if sn:
            report.stats["inscrits_national"] = sn[0]
            report.stats["votants_national"] = sn[1]
            report.stats["taux_participation_national"] = f"{sn[2]:.2f}%"
    except Exception:
        pass
