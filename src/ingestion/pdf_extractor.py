"""Module d'extraction PDF → DataFrame brut via pdfplumber."""

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber

logger = logging.getLogger(__name__)

# En-têtes à filtrer (répétés à chaque page)
HEADER_MARKERS = {"REGION", "CIRCONSCRIPTION", "NB BV", "INSCRITS", "VOTANTS", "SCORES"}

# Colonnes attendues dans le tableau principal
EXPECTED_COLUMNS = [
    "REGION",
    "numero",
    "CIRCONSCRIPTION",
    "NB BV",
    "INSCRITS",
    "VOTANTS",
    "TAUX DE PART.",
    "BULL. NULS",
    "SUF. EXPRIMES",
    "BULL. BLANCS NOMBRE",
    "BULL. BLANCS %",
    "GROUPEMENTS / PARTIS POLITIQUES",
    "CANDIDATS / LISTES DE CANDIDATS",
    "SCORES",
    "%",
    "ELU(E)",
]


def extract_pdf(pdf_path: str | Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extrait le tableau principal et le résumé national du PDF.

    Args:
        pdf_path: Chemin vers le fichier PDF.

    Returns:
        Tuple (df_results, summary_dict) où:
        - df_results: DataFrame avec tous les candidats
        - summary_dict: dict avec les totaux nationaux (ligne TOTAL)
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF non trouvé: {pdf_path}")

    logger.info(f"Extraction du PDF: {pdf_path}")

    all_rows: list[list[Any]] = []
    all_source_pages: list[int] = []
    summary_dict: dict[str, Any] = {}

    with pdfplumber.open(pdf_path) as pdf:
        logger.info(f"Nombre de pages: {len(pdf.pages)}")

        for page_num, page in enumerate(pdf.pages):
            logger.debug(f"Traitement page {page_num + 1}/{len(pdf.pages)}")

            tables = page.extract_tables()
            if not tables:
                logger.debug(f"Aucun tableau trouvé page {page_num + 1}")
                continue

            for table in tables:
                if not table:
                    continue

                for row_idx, row in enumerate(table):
                    if row is None:
                        continue

                    # Nettoyer les cellules None → chaîne vide
                    clean_row = [
                        (cell.strip() if isinstance(cell, str) else "") for cell in row
                    ]

                    # Filtrer les lignes vides
                    if not any(clean_row):
                        continue

                    # Détecter et filtrer les en-têtes répétés
                    if _is_header_row(clean_row):
                        logger.debug(f"En-tête filtré page {page_num + 1}, ligne {row_idx}")
                        continue

                    # Détecter la ligne TOTAL (page 1, contient les totaux nationaux)
                    if page_num == 0 and _is_total_row(clean_row):
                        summary_dict = _parse_total_row(clean_row)
                        logger.info(f"Ligne TOTAL extraite: {summary_dict}")
                        continue

                    all_rows.append(clean_row)
                    all_source_pages.append(page_num + 1)  # 1-indexed

    logger.info(f"Total de lignes extraites: {len(all_rows)}")

    df = _build_dataframe(all_rows)
    # Attach page provenance — each row knows which PDF page it came from
    if all_source_pages:
        df["source_page"] = all_source_pages[: len(df)]
    return df, summary_dict


def _is_header_row(row: list[str]) -> bool:
    """Détecte si une ligne est un en-tête de tableau."""
    row_text = " ".join(str(c) for c in row).upper()
    matches = sum(1 for marker in HEADER_MARKERS if marker in row_text)
    return matches >= 3


def _is_total_row(row: list[str]) -> bool:
    """Détecte si une ligne est la ligne de totaux nationaux."""
    row_text = " ".join(str(c) for c in row).upper()
    return "TOTAL" in row_text and any(
        c.replace(" ", "").replace("\xa0", "").isdigit()
        for c in row
        if c
    )


def _parse_total_row(row: list[str]) -> dict[str, Any]:
    """Extrait les valeurs de la ligne TOTAL.

    La ligne TOTAL a la même structure que les autres lignes du tableau.
    Les colonnes correspondent à EXPECTED_COLUMNS (indices 0-15+).
    Les nombres utilisent l'espace comme séparateur de milliers et la virgule
    comme séparateur décimal (format français).

    Colonnes cibles :
        index 3  → NB BV (nb_bureaux_vote)
        index 4  → INSCRITS
        index 5  → VOTANTS
        index 6  → TAUX DE PART. (pourcentage avec %)
        index 7  → BULL. NULS
        index 8  → SUF. EXPRIMES
        index 9  → BULL. BLANCS NOMBRE
        index 10 → BULL. BLANCS %
        index 13 → SCORES (total_scores)
    """
    logger.info("Ligne TOTAL détectée — extraction des valeurs nationales")

    def to_int(val: str) -> int | None:
        """Convertit une chaîne en int en gérant les séparateurs de milliers français."""
        try:
            cleaned = val.replace(" ", "").replace("\xa0", "").replace(",", "")
            return int(cleaned)
        except (ValueError, AttributeError):
            return None

    def to_float(val: str) -> float | None:
        """Convertit une chaîne en float en gérant la virgule décimale française."""
        try:
            cleaned = val.replace(" ", "").replace("\xa0", "").replace("%", "").replace(",", ".")
            return float(cleaned)
        except (ValueError, AttributeError):
            return None

    result: dict[str, Any] = {}

    try:
        if len(row) > 3:
            v = to_int(row[3])
            if v is not None:
                result["nb_bureaux_vote"] = v
        if len(row) > 4:
            v = to_int(row[4])
            if v is not None:
                result["inscrits"] = v
        if len(row) > 5:
            v = to_int(row[5])
            if v is not None:
                result["votants"] = v
        if len(row) > 6:
            v = to_float(row[6])
            if v is not None:
                result["taux_participation"] = v
        if len(row) > 7:
            v = to_int(row[7])
            if v is not None:
                result["bulletins_nuls"] = v
        if len(row) > 8:
            v = to_int(row[8])
            if v is not None:
                result["suffrages_exprimes"] = v
        if len(row) > 9:
            v = to_int(row[9])
            if v is not None:
                result["bulletins_blancs"] = v
        if len(row) > 10:
            v = to_float(row[10])
            if v is not None:
                result["bulletins_blancs_pct"] = v
        if len(row) > 13:
            v = to_int(row[13])
            if v is not None:
                result["total_scores"] = v
    except Exception as e:
        logger.error(f"Erreur lors du parsing de la ligne TOTAL: {e} — row={row}")

    if not result:
        logger.warning("Parsing ligne TOTAL a produit un dict vide — vérifier les indices de colonnes")
    else:
        logger.info(f"Ligne TOTAL extraite: {result}")

    return result


def _build_dataframe(rows: list[list[Any]]) -> pd.DataFrame:
    """Construit un DataFrame à partir des lignes extraites."""
    if not rows:
        logger.warning("Aucune ligne à traiter")
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

    # Normaliser la largeur des lignes
    max_cols = max(len(r) for r in rows)
    normalized = [r + [""] * (max_cols - len(r)) for r in rows]

    df = pd.DataFrame(normalized)

    # Assigner les noms de colonnes si la largeur correspond
    if df.shape[1] >= len(EXPECTED_COLUMNS):
        df.columns = list(EXPECTED_COLUMNS) + [
            f"col_extra_{i}" for i in range(df.shape[1] - len(EXPECTED_COLUMNS))
        ]
    else:
        # Assigner autant de colonnes que possible
        cols = EXPECTED_COLUMNS[: df.shape[1]]
        df.columns = cols

    logger.info(f"DataFrame construit: {df.shape[0]} lignes × {df.shape[1]} colonnes")
    return df
