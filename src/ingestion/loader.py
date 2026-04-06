"""Chargement dans DuckDB et création des tables/vues."""

import logging
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def get_connection(db_path: str | Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Retourne une connexion DuckDB.

    Args:
        db_path: Chemin vers le fichier DuckDB.
        read_only: Si True, ouvre en lecture seule.

    Returns:
        Connexion DuckDB.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(db_path), read_only=read_only)


def create_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Crée toutes les tables et vues dans DuckDB.

    Args:
        conn: Connexion DuckDB (lecture-écriture).
    """
    logger.info("Création du schéma DuckDB")

    conn.execute("""
        CREATE OR REPLACE TABLE results (
            region                TEXT NOT NULL,
            numero_circonscription INTEGER NOT NULL,
            circonscription       TEXT NOT NULL,
            nb_bureaux_vote       INTEGER,
            inscrits              INTEGER,
            votants               INTEGER,
            taux_participation    DOUBLE,
            bulletins_nuls        INTEGER,
            suffrages_exprimes    INTEGER,
            bulletins_blancs      INTEGER,
            bulletins_blancs_pct  DOUBLE,
            parti                 TEXT NOT NULL,
            candidat              TEXT NOT NULL,
            scores                INTEGER NOT NULL,
            score_pct             DOUBLE,
            elu                   BOOLEAN DEFAULT FALSE,
            source_page           INTEGER
        )
    """)

    conn.execute("""
        CREATE OR REPLACE TABLE summary_national (
            nb_bureaux_vote       INTEGER,
            inscrits              INTEGER,
            votants               INTEGER,
            taux_participation    DOUBLE,
            taux_abstention       DOUBLE,
            bulletins_nuls        INTEGER,
            suffrages_exprimes    INTEGER,
            bulletins_blancs      INTEGER,
            bulletins_blancs_pct  DOUBLE,
            total_scores          INTEGER
        )
    """)

    logger.info("Tables créées")


def load_results(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Charge le DataFrame dans la table results.

    Args:
        conn: Connexion DuckDB.
        df: DataFrame nettoyé avec les colonnes de results.

    Returns:
        Nombre de lignes insérées.
    """
    # Vider la table avant rechargement
    conn.execute("DELETE FROM results")

    # S'assurer que toutes les colonnes requises sont présentes
    required_cols = [
        "region", "numero_circonscription", "circonscription",
        "nb_bureaux_vote", "inscrits", "votants", "taux_participation",
        "bulletins_nuls", "suffrages_exprimes", "bulletins_blancs",
        "bulletins_blancs_pct", "parti", "candidat", "scores", "score_pct", "elu",
        "source_page",
    ]
    for col in required_cols:
        if col not in df.columns:
            logger.warning(f"Colonne manquante: {col} — remplie avec NULL/False")
            if col == "elu":
                df[col] = False
            else:
                df[col] = None

    df_insert = df[required_cols].copy()

    # Supprimer les lignes avec des valeurs obligatoires manquantes
    df_insert = df_insert.dropna(subset=["region", "circonscription", "parti", "candidat"])
    df_insert = df_insert[df_insert["scores"].notna()]

    # Dédupliquer: le PDF peut générer des doublons via les cellules fusionnées.
    # IMPORTANT: trier elu=True en premier pour que keep="first" préserve
    # le statut d'élu quand un candidat apparaît plusieurs fois (ex: page break
    # sur une cellule fusionnée produit d'abord une ligne sans ELU(E), puis une
    # avec ELU(E)).
    dedup_keys = ["numero_circonscription", "candidat", "parti"]
    before = len(df_insert)
    # Sort: elu=True first (to preserve elected status), then source_page ascending
    # (keep row from earliest PDF page when duplicates exist across page breaks)
    sort_cols = ["elu", "source_page"] if "source_page" in df_insert.columns else ["elu"]
    sort_asc = [False, True] if len(sort_cols) == 2 else [False]
    df_insert = df_insert.sort_values(sort_cols, ascending=sort_asc)
    df_insert = df_insert.drop_duplicates(subset=dedup_keys, keep="first")
    after = len(df_insert)
    if before != after:
        logger.info(f"{before - after} lignes dupliquées supprimées")

    conn.execute("INSERT INTO results SELECT * FROM df_insert")

    row_count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]  # type: ignore[index]
    logger.info(f"{row_count} lignes insérées dans results")
    return int(row_count)


def load_summary_national(
    conn: duckdb.DuckDBPyConnection, summary: dict[str, Any]
) -> None:
    """Charge le résumé national dans summary_national.

    Args:
        conn: Connexion DuckDB.
        summary: Dictionnaire avec les totaux nationaux.
    """
    conn.execute("DELETE FROM summary_national")

    if not summary:
        logger.warning("Aucun résumé national trouvé, insertion de valeurs par défaut")
        # Valeurs connues de la ligne TOTAL du PDF
        summary = {
            "nb_bureaux_vote": 25338,
            "inscrits": 8597092,
            "votants": 3012094,
            "taux_participation": 35.04,
            "bulletins_nuls": 68525,
            "suffrages_exprimes": 2943569,
            "bulletins_blancs": 29578,
            "bulletins_blancs_pct": 1.00,
            "total_scores": 2913991,
        }

    taux_participation = summary.get("taux_participation") or 0.0
    taux_abstention = round(100.0 - taux_participation, 2)

    conn.execute("""
        INSERT INTO summary_national VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        summary.get("nb_bureaux_vote"),
        summary.get("inscrits"),
        summary.get("votants"),
        taux_participation,
        taux_abstention,
        summary.get("bulletins_nuls"),
        summary.get("suffrages_exprimes"),
        summary.get("bulletins_blancs"),
        summary.get("bulletins_blancs_pct"),
        summary.get("total_scores"),
    ])
    logger.info("Résumé national chargé")


def create_views(conn: duckdb.DuckDBPyConnection) -> None:
    """Crée toutes les vues précalculées.

    Args:
        conn: Connexion DuckDB.
    """
    logger.info("Création des vues")

    conn.execute("""
        CREATE OR REPLACE VIEW vw_winners AS
        SELECT region, numero_circonscription, circonscription,
               parti, candidat, scores, score_pct,
               nb_bureaux_vote, inscrits, votants, taux_participation,
               bulletins_nuls, suffrages_exprimes, bulletins_blancs, bulletins_blancs_pct
        FROM results
        WHERE elu = TRUE
    """)

    conn.execute("""
        CREATE OR REPLACE VIEW vw_turnout AS
        SELECT DISTINCT
            region, numero_circonscription, circonscription,
            nb_bureaux_vote, inscrits, votants, taux_participation,
            ROUND(100.0 - taux_participation, 2) AS taux_abstention,
            ROUND(bulletins_nuls * 100.0 / NULLIF(votants, 0), 2) AS bulletins_nuls_pct,
            bulletins_nuls, suffrages_exprimes, bulletins_blancs, bulletins_blancs_pct
        FROM results
    """)

    conn.execute("""
        CREATE OR REPLACE VIEW vw_results_by_region AS
        SELECT
            r.region,
            COUNT(DISTINCT r.numero_circonscription) AS nb_circonscriptions,
            SUM(CASE WHEN r.elu THEN 1 ELSE 0 END) AS nb_sieges,
            t.total_nb_bureaux_vote,
            t.total_inscrits,
            t.total_votants,
            ROUND(t.total_votants * 100.0 / NULLIF(t.total_inscrits, 0), 2) AS taux_participation,
            ROUND(100.0 - ROUND(t.total_votants * 100.0 / NULLIF(t.total_inscrits, 0), 2), 2) AS taux_abstention,
            COUNT(*) AS nb_candidats,
            ROUND(t.total_bulletins_nuls * 100.0 / NULLIF(t.total_votants, 0), 2) AS bulletins_nuls_pct,
            t.total_bulletins_nuls,
            t.total_suffrages_exprimes,
            t.total_bulletins_blancs,
            ROUND(t.total_bulletins_blancs * 100.0 / NULLIF(t.total_suffrages_exprimes, 0), 2) AS bulletins_blancs_pct
        FROM results r
        JOIN (
            SELECT region,
                   SUM(nb_bureaux_vote)    AS total_nb_bureaux_vote,
                   SUM(inscrits)           AS total_inscrits,
                   SUM(votants)            AS total_votants,
                   SUM(bulletins_nuls)     AS total_bulletins_nuls,
                   SUM(suffrages_exprimes) AS total_suffrages_exprimes,
                   SUM(bulletins_blancs)   AS total_bulletins_blancs
            FROM vw_turnout
            GROUP BY region
        ) t ON r.region = t.region
        GROUP BY r.region, t.total_nb_bureaux_vote, t.total_inscrits, t.total_votants,
                 t.total_bulletins_nuls, t.total_suffrages_exprimes, t.total_bulletins_blancs
    """)

    conn.execute("""
        CREATE OR REPLACE VIEW vw_results_by_party AS
        SELECT
            r.parti,
            COUNT(*) AS nb_candidats,
            SUM(r.scores) AS total_scores,
            SUM(CASE WHEN r.elu THEN 1 ELSE 0 END) AS nb_sieges,
            ROUND(
                SUM(CASE WHEN r.elu THEN 1 ELSE 0 END) * 100.0
                / NULLIF((SELECT COUNT(DISTINCT numero_circonscription) FROM results), 0),
                2
            ) AS taux_victoire,
            t.total_nb_bureaux_vote,
            t.total_inscrits,
            t.total_votants,
            ROUND(t.total_votants * 100.0 / NULLIF(t.total_inscrits, 0), 2) AS taux_participation,
            t.total_bulletins_nuls,
            t.total_suffrages_exprimes,
            t.total_bulletins_blancs,
            ROUND(t.total_bulletins_blancs * 100.0 / NULLIF(t.total_suffrages_exprimes, 0), 2) AS bulletins_blancs_pct
        FROM results r
        JOIN (
            SELECT parti,
                   SUM(nb_bureaux_vote)    AS total_nb_bureaux_vote,
                   SUM(inscrits)           AS total_inscrits,
                   SUM(votants)            AS total_votants,
                   SUM(bulletins_nuls)     AS total_bulletins_nuls,
                   SUM(suffrages_exprimes) AS total_suffrages_exprimes,
                   SUM(bulletins_blancs)   AS total_bulletins_blancs
            FROM (
                SELECT DISTINCT parti, numero_circonscription,
                       nb_bureaux_vote, inscrits, votants,
                       bulletins_nuls, suffrages_exprimes, bulletins_blancs
                FROM results
            ) x
            GROUP BY parti
        ) t ON r.parti = t.parti
        GROUP BY r.parti, t.total_nb_bureaux_vote, t.total_inscrits, t.total_votants,
                 t.total_bulletins_nuls, t.total_suffrages_exprimes, t.total_bulletins_blancs
        ORDER BY nb_sieges DESC
    """)

    conn.execute("""
        CREATE OR REPLACE VIEW vw_results_by_circonscription AS
        WITH runner_up AS (
            SELECT
                numero_circonscription,
                MAX(scores) AS runner_up_scores
            FROM (
                SELECT
                    numero_circonscription,
                    scores,
                    RANK() OVER (PARTITION BY numero_circonscription ORDER BY scores DESC) AS rk
                FROM results
            ) ranked
            WHERE rk = 2
            GROUP BY numero_circonscription
        )
        SELECT
            r.region, r.numero_circonscription, r.circonscription,
            r.nb_bureaux_vote, r.inscrits, r.votants, r.taux_participation,
            ROUND(100.0 - r.taux_participation, 2) AS taux_abstention,
            r.bulletins_nuls, r.suffrages_exprimes, r.bulletins_blancs, r.bulletins_blancs_pct,
            COUNT(*) AS nb_candidats,
            MAX(CASE WHEN r.elu THEN r.candidat END) AS elu_candidat,
            MAX(CASE WHEN r.elu THEN r.parti END)    AS elu_parti,
            MAX(CASE WHEN r.elu THEN r.scores END)   AS elu_scores,
            MAX(CASE WHEN r.elu THEN r.score_pct END) AS elu_score_pct,
            ru.runner_up_scores,
            MAX(CASE WHEN r.elu THEN r.scores END) - ru.runner_up_scores AS marge_victoire,
            ROUND(
                (MAX(CASE WHEN r.elu THEN r.scores END) - ru.runner_up_scores) * 100.0
                / NULLIF(r.suffrages_exprimes, 0),
                2
            ) AS marge_victoire_pct
        FROM results r
        LEFT JOIN runner_up ru ON r.numero_circonscription = ru.numero_circonscription
        GROUP BY r.region, r.numero_circonscription, r.circonscription,
                 r.nb_bureaux_vote, r.inscrits, r.votants, r.taux_participation,
                 r.bulletins_nuls, r.suffrages_exprimes, r.bulletins_blancs, r.bulletins_blancs_pct,
                 ru.runner_up_scores
    """)

    conn.execute("""
        CREATE OR REPLACE VIEW vw_close_races AS
        SELECT
            region, numero_circonscription, circonscription,
            elu_candidat, elu_parti, elu_scores, elu_score_pct,
            runner_up_scores, marge_victoire, marge_victoire_pct,
            nb_candidats, inscrits, votants, taux_participation, taux_abstention
        FROM vw_results_by_circonscription
        WHERE marge_victoire IS NOT NULL
        ORDER BY marge_victoire_pct ASC
    """)

    # Vue : scores agrégés par (région, parti) avec classement
    # Résout les questions "quel parti a eu le Nème meilleur score dans la région X"
    conn.execute("""
        CREATE OR REPLACE VIEW vw_party_scores_by_region AS
        SELECT
            r.region,
            r.parti,
            COUNT(*)                                            AS nb_candidats,
            COUNT(DISTINCT r.numero_circonscription)            AS nb_circonscriptions,
            SUM(r.scores)                                       AS total_scores,
            ROUND(
                SUM(r.scores) * 100.0
                / NULLIF(SUM(SUM(r.scores)) OVER (PARTITION BY r.region), 0),
                2
            )                                                   AS pct_scores_region,
            SUM(CASE WHEN r.elu THEN 1 ELSE 0 END)             AS nb_sieges,
            -- Participation : agrégée sur les circonscriptions distinctes où le parti était présent
            t.total_inscrits,
            t.total_votants,
            ROUND(t.total_votants * 100.0 / NULLIF(t.total_inscrits, 0), 2) AS taux_participation,
            ROUND(100.0 - ROUND(t.total_votants * 100.0 / NULLIF(t.total_inscrits, 0), 2), 2) AS taux_abstention,
            t.total_suffrages_exprimes,
            -- Classement au sein de la région (1 = meilleur score)
            RANK() OVER (PARTITION BY r.region ORDER BY SUM(r.scores) DESC) AS classement_region
        FROM results r
        JOIN (
            SELECT
                parti,
                region,
                SUM(inscrits)           AS total_inscrits,
                SUM(votants)            AS total_votants,
                SUM(suffrages_exprimes) AS total_suffrages_exprimes
            FROM (
                SELECT DISTINCT parti, region, numero_circonscription,
                       inscrits, votants, suffrages_exprimes
                FROM results
            ) x
            GROUP BY parti, region
        ) t ON r.parti = t.parti AND r.region = t.region
        GROUP BY r.region, r.parti,
                 t.total_inscrits, t.total_votants, t.total_suffrages_exprimes
        ORDER BY r.region, total_scores DESC
    """)

    # Vue : classement des candidats au sein de leur circonscription
    # Résout "qui était 2ème dans la circonscription X", "meilleure marge de victoire"
    conn.execute("""
        CREATE OR REPLACE VIEW vw_candidates_ranked_by_circonscription AS
        SELECT
            region,
            numero_circonscription,
            circonscription,
            parti,
            candidat,
            scores,
            score_pct,
            elu,
            RANK() OVER (
                PARTITION BY numero_circonscription
                ORDER BY scores DESC
            ) AS classement_circonscription
        FROM results
        ORDER BY numero_circonscription, classement_circonscription
    """)

    logger.info(
        "8 vues créées : vw_winners, vw_turnout, vw_results_by_region, "
        "vw_results_by_party, vw_results_by_circonscription, vw_close_races, "
        "vw_party_scores_by_region, vw_candidates_ranked_by_circonscription"
    )
