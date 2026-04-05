"""Nettoyage et normalisation du DataFrame brut extrait du PDF."""

import logging
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Mapping colonnes brutes PDF → colonnes base de données
COLUMN_RENAME_MAP: dict[str, str] = {
    "REGION": "region",
    "numero": "numero_circonscription",
    "CIRCONSCRIPTION": "circonscription",
    "NB BV": "nb_bureaux_vote",
    "INSCRITS": "inscrits",
    "VOTANTS": "votants",
    "TAUX DE PART.": "taux_participation",
    "BULL. NULS": "bulletins_nuls",
    "SUF. EXPRIMES": "suffrages_exprimes",
    "BULL. BLANCS NOMBRE": "bulletins_blancs",
    "BULL. BLANCS %": "bulletins_blancs_pct",
    "GROUPEMENTS / PARTIS POLITIQUES": "parti",
    "CANDIDATS / LISTES DE CANDIDATS": "candidat",
    "SCORES": "scores",
    "%": "score_pct",
    "ELU(E)": "elu",
}

# Colonnes qui doivent être propagées (forward-fill) car fusionnées verticalement
FORWARD_FILL_COLS = [
    "region",
    "numero_circonscription",
    "circonscription",
    "nb_bureaux_vote",
    "inscrits",
    "votants",
    "taux_participation",
    "bulletins_nuls",
    "suffrages_exprimes",
    "bulletins_blancs",
    "bulletins_blancs_pct",
]


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoie et normalise le DataFrame extrait du PDF.

    Pipeline:
    1. Renommage des colonnes
    2. Suppression des colonnes extra
    3. Forward-fill des cellules fusionnées
    4. Conversion des types
    5. Suppression des lignes invalides

    Args:
        df: DataFrame brut issu de pdf_extractor.

    Returns:
        DataFrame nettoyé avec les colonnes DB.
    """
    if df.empty:
        logger.warning("DataFrame vide reçu pour nettoyage")
        return df

    logger.info(f"Nettoyage: {df.shape[0]} lignes d'entrée")

    # 1. Renommer les colonnes connues
    df = df.rename(columns=COLUMN_RENAME_MAP)

    # 2. Garder uniquement les colonnes DB attendues (+ source_page si présente)
    db_cols = list(COLUMN_RENAME_MAP.values())
    existing_cols = [c for c in db_cols if c in df.columns]
    if "source_page" in df.columns:
        existing_cols.append("source_page")
    df = df[existing_cols].copy()

    # 3. Remplacer les chaînes vides par NaN pour faciliter le forward-fill
    df = df.replace("", pd.NA)

    # 3b. Nullifier les artefacts d'en-têtes dans la colonne région AVANT le forward-fill.
    # Le header "REGION" est parfois découpé en "REGI" / "ON" sur deux lignes par pdfplumber.
    # La ligne "REGI" passe le filtre d'en-tête (_is_header_row) et si elle n'est pas
    # nullifiée avant le forward-fill, elle contamine la première circonscription de chaque page.
    if "region" in df.columns:
        df["region"] = df["region"].where(
            ~df["region"].isin(_REGION_INVALID), other=pd.NA
        )

    # 4. Forward-fill des colonnes fusionnées verticalement
    df = forward_fill_merged_cells(df, FORWARD_FILL_COLS)

    # 5. Convertir les types
    df = _convert_types(df)

    # 6. Supprimer les lignes sans candidat (lignes de séparation)
    df = df.dropna(subset=["candidat"])
    df = df[df["candidat"].str.strip() != ""]

    # 7. Supprimer les lignes avec région invalide (résidus d'en-têtes)
    if "region" in df.columns:
        df = df[~df["region"].isin(_REGION_INVALID)]

    # 8. Réinitialiser l'index
    df = df.reset_index(drop=True)

    # 9. Fallback élu : si une circonscription n'a aucun élu marqué (cellule ELU
    #    vide dans le PDF, scrutin de liste, ou artefact d'extraction), marquer
    #    le candidat avec le score le plus élevé comme élu.
    if "elu" in df.columns and "scores" in df.columns and "numero_circonscription" in df.columns:
        circos_sans_elu = df.groupby("numero_circonscription")["elu"].transform("any")
        mask_sans_elu = ~circos_sans_elu

        if mask_sans_elu.any():
            affected = df.loc[mask_sans_elu, "numero_circonscription"].nunique()
            logger.info(f"Fallback élu appliqué sur {affected} circonscription(s) sans élu marqué")
            # Pour chaque circo sans élu, trouver le candidat avec le score max
            idx_max_scores = (
                df[mask_sans_elu]
                .groupby("numero_circonscription")["scores"]
                .idxmax()
            )
            df.loc[idx_max_scores, "elu"] = True

    logger.info(f"Nettoyage terminé: {df.shape[0]} lignes en sortie")
    return df


def forward_fill_merged_cells(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Propage les valeurs des cellules fusionnées verticalement (forward-fill).

    Dans pdfplumber, les cellules fusionnées retournent None/vide pour les lignes
    suivantes. Cette fonction propage la dernière valeur non-nulle vers le bas.

    Args:
        df: DataFrame à traiter.
        cols: Colonnes à forward-filler.

    Returns:
        DataFrame avec valeurs propagées.
    """
    for col in cols:
        if col in df.columns:
            df[col] = df[col].ffill()
    return df


def parse_number(value: Any) -> int | None:
    """Parse un nombre avec espaces comme séparateurs de milliers.

    Args:
        value: Valeur brute (str, int, float, None).

    Returns:
        Entier parsé ou None si impossible.

    Examples:
        >>> parse_number("52 106")
        52106
        >>> parse_number("8 597 092")
        8597092
        >>> parse_number(None)
        None
    """
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float):
        import math
        if math.isnan(value):
            return None
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Supprimer séparateurs de milliers (espace normal et insécable)
    text = text.replace(" ", "").replace("\xa0", "").replace("\u202f", "")
    # Supprimer suffixes non numériques
    text = re.sub(r"[^0-9]", "", text)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_percentage(value: Any) -> float | None:
    """Parse un pourcentage avec virgule décimale française.

    Args:
        value: Valeur brute (str, float, None).

    Returns:
        Float parsé ou None si impossible.

    Examples:
        >>> parse_percentage("27,00%")
        27.0
        >>> parse_percentage("0,56")
        0.56
        >>> parse_percentage(None)
        None
    """
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float):
        import math
        if math.isnan(value):
            return None
        return value
    if isinstance(value, int):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    # Remplacer virgule décimale française et supprimer le signe %
    text = text.replace(",", ".").rstrip("%").strip()
    # Supprimer espaces et caractères non numériques sauf le point
    text = re.sub(r"[^0-9.]", "", text)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_elu(value: Any) -> bool:
    """Parse la colonne ELU(E).

    Une cellule non-vide indique que le candidat est élu.

    Args:
        value: Valeur brute de la colonne ELU(E).

    Returns:
        True si élu, False sinon.
    """
    if value is None or value is pd.NA:
        return False
    if isinstance(value, float):
        import math
        if math.isnan(value):
            return False
    text = str(value).strip()
    return bool(text)


# Mapping de normalisation post-reconstruction pour les noms de régions connus.
# Les espaces sont perdus lors de l'extraction verticale pdfplumber.
_REGION_CORRECTIONS: dict[str, str] = {
    "DISTRICTAUTONOMED'ABIDJAN": "DISTRICT AUTONOME D'ABIDJAN",
    "DISTRICTAUTONOMEDEYAMOUSSOUKRO": "DISTRICT AUTONOME DE YAMOUSSOUKRO",
    "GRANDSPONTS": "GRANDS PONTS",
    "HAUT-SASSANDRA": "HAUT-SASSANDRA",
    "LOH-DJIBOUA": "LÔH-DJIBOUA",
    "SUD-COMOE": "SUD-COMOÉ",
    "LAME": "LA ME",
    "N'ZI": "N'ZI",
}

# Noms de régions valides (formes canoniques officielles).
# Utilisé pour détecter les noms inversés lus par pdfplumber sur les cellules
# fusionnées verticalement (ex: "OGOLOHCT" → reversed → "TCHOLOGO").
_VALID_REGIONS: frozenset[str] = frozenset({
    "AGNEBY-TIASSA", "BAFING", "BAGOUE", "BAS-SASSANDRA", "BELIER", "BERE",
    "BOUNKANI", "CAVALLY", "DISTRICT AUTONOME D'ABIDJAN",
    "DISTRICT AUTONOME DE YAMOUSSOUKRO", "FOLON", "GBEKE", "GBOKLE",
    "GOH", "GÔH", "GRANDS PONTS", "GUEMON", "HAMBOL", "HAUT-SASSANDRA",
    "IFFOU", "INDENIE-DJUABLIN", "KABADOUGOU", "LA ME", "LOH-DJIBOUA",
    "LÔH-DJIBOUA", "MARAHOUE", "ME", "MORONOU", "N'ZI", "NAWA", "PORO",
    "SAN-PEDRO", "SUD-COMOE", "SUD-COMOÉ", "TCHOLOGO", "TONKPI",
    "WORODOUGOU", "ZANZAN",
})

# Valeurs à supprimer (résidus d'en-têtes ou artefacts)
_REGION_INVALID = {"REGI", "REGION", ""}


def normalize_vertical_text(value: Any) -> str | None:
    """Normalise le texte extrait verticalement du PDF.

    pdfplumber lit les caractères des cellules fusionnées verticalement
    de bas en haut, séparés par \\n. Cette fonction renverse l'ordre des
    segments pour reconstruire le nom correct.

    Examples:
        >>> normalize_vertical_text("U\\nO\\nG\\nU\\nO\\nD\\nA\\nB\\nA\\nK")
        "KABADOUGOU"
        >>> normalize_vertical_text("O\\nG\\nO\\nL\\nO\\nH\\nC\\nT")
        "TCHOLOGO"
    """
    if value is None or value is pd.NA:
        return None
    text = str(value).strip()
    if "\n" not in text:
        if not text:
            return None
        upper = text.upper()
        # Vérifier d'abord les corrections explicites
        if upper in _REGION_CORRECTIONS:
            return _REGION_CORRECTIONS[upper]
        # Vérifier si le texte est déjà une région valide
        if upper in {r.upper() for r in _VALID_REGIONS}:
            return text
        # Essayer la version inversée : pdfplumber lit parfois les cellules
        # fusionnées verticalement de bas en haut (ex: "OGOLOHCT" → "TCHOLOGO")
        reversed_text = text[::-1]
        reversed_upper = reversed_text.upper()
        if reversed_upper in _REGION_CORRECTIONS:
            return _REGION_CORRECTIONS[reversed_upper]
        if reversed_upper in {r.upper() for r in _VALID_REGIONS}:
            return reversed_text
        # Détecter les noms de circonscriptions inversés (termes administratifs FR)
        if "SERUTCEFERP" in upper or "SENUMMOC" in upper or "ENUMMOC" in upper:
            return reversed_text
        return text
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        return None

    # Heuristique : si au moins un segment fait plus de 5 caractères, c'est un retour
    # à la ligne horizontal dans la cellule PDF (ex: "COMMUNES ET SOUS-\nPREFECTURES"),
    # PAS du texte vertical caractère par caractère. On assemble proprement sans inverser.
    if any(len(p) > 5 for p in parts):
        # "COMMUNES ET SOUS-\nPREFECTURES" → "COMMUNES ET SOUS-PREFECTURES"
        joined = re.sub(r"-\n\s*", "-", text)   # trait d'union en fin de ligne → coller
        joined = re.sub(r"\n", " ", joined)     # autres sauts de ligne → espace
        return " ".join(joined.split())

    # Texte vertical : inverser l'ordre des segments ET l'ordre interne de chaque segment
    # (les ligatures "IB" → "BI", "IF" → "FI" sont lues à l'envers par pdfplumber)
    reconstructed = "".join(p[::-1] for p in reversed(parts))
    return _REGION_CORRECTIONS.get(reconstructed, reconstructed)


def normalize_column_name(raw_name: str) -> str:
    """Normalise un nom de colonne brut PDF vers le nom de colonne DB.

    D'abord cherche dans le mapping explicite. Si non trouvé, applique
    une normalisation générique (minuscules, accents supprimés, espaces → _).

    Args:
        raw_name: Nom de colonne tel qu'extrait du PDF.

    Returns:
        Nom de colonne normalisé (jamais None).

    Examples:
        >>> normalize_column_name("INSCRITS")
        "inscrits"
        >>> normalize_column_name("NB BV")
        "nb_bureaux_vote"
        >>> normalize_column_name("RÉGION")
        "region"
    """
    import re
    import unicodedata

    # Chercher dans le mapping explicite
    if raw_name in COLUMN_RENAME_MAP:
        return COLUMN_RENAME_MAP[raw_name]

    # Fallback: normalisation générique
    # Supprimer accents
    nfd = unicodedata.normalize("NFD", raw_name)
    without_accents = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # Minuscules, espaces et "/" → "_", strip
    normalized = re.sub(r"[\s/]+", "_", without_accents.lower()).strip("_")
    # Supprimer caractères non alphanumériques sauf "_"
    normalized = re.sub(r"[^\w]", "", normalized)
    return normalized


def _convert_types(df: pd.DataFrame) -> pd.DataFrame:
    """Convertit les colonnes vers leurs types appropriés."""
    integer_cols = [
        "numero_circonscription",
        "nb_bureaux_vote",
        "inscrits",
        "votants",
        "bulletins_nuls",
        "suffrages_exprimes",
        "bulletins_blancs",
        "scores",
    ]
    percentage_cols = ["taux_participation", "bulletins_blancs_pct", "score_pct"]
    text_cols = ["region", "circonscription", "parti", "candidat"]

    for col in integer_cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_number)

    for col in percentage_cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_percentage)

    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].apply(normalize_vertical_text)

    if "elu" in df.columns:
        df["elu"] = df["elu"].apply(parse_elu)

    return df
