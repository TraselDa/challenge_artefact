"""Normalisation des entités pour la recherche floue."""

import difflib
import logging
import re
import unicodedata

_WORD_RE = re.compile(r"[\w'-]+")

logger = logging.getLogger(__name__)

# Alias de partis politiques
PARTY_ALIASES: dict[str, str] = {
    "rhdp": "RHDP",
    "r.h.d.p": "RHDP",
    "r.h.d.p.": "RHDP",
    "rassemblement houphouetistes": "RHDP",
    "rassemblement des houphouetistes": "RHDP",
    "pdci": "PDCI-RDA",
    "p.d.c.i": "PDCI-RDA",
    "p.d.c.i.": "PDCI-RDA",
    "pdci-rda": "PDCI-RDA",
    "parti democratique cote ivoire": "PDCI-RDA",
    "parti democratique": "PDCI-RDA",
    "fpi": "FPI",
    "f.p.i": "FPI",
    "f.p.i.": "FPI",
    "front populaire ivoirien": "FPI",
    "front populaire": "FPI",
    "independant": "INDEPENDANT",
    "independants": "INDEPENDANT",
    "independent": "INDEPENDANT",
    "sans parti": "INDEPENDANT",
    "adci": "ADCI",
    "a.d.c.i": "ADCI",
    "mgc": "MGC",
    "m.g.c": "MGC",
}


def normalize_text(text: str | None) -> str:
    """Normalise: lowercase, accents supprimés, espaces nettoyés.

    Args:
        text: Texte brut (ou None).

    Returns:
        Texte normalisé. Retourne "" si text est None.

    Examples:
        >>> normalize_text("Côte d'Ivoire")
        "cote d'ivoire"
        >>> normalize_text("ABIDJAN")
        "abidjan"
        >>> normalize_text(None)
        ""
    """
    if text is None:
        return ""
    # Décomposer les caractères accentués (NFD) puis supprimer les diacritiques
    nfd = unicodedata.normalize("NFD", str(text))
    without_accents = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # Minuscules et nettoyage des espaces
    return " ".join(without_accents.lower().split())


def normalize_party(name: str | None) -> str:
    """Normalise un nom de parti (gère aliases, points, espaces).

    Args:
        name: Nom brut du parti.

    Returns:
        Nom normalisé (ex: "RHDP", "PDCI-RDA", "FPI").

    Examples:
        >>> normalize_party("R.H.D.P")
        "RHDP"
        >>> normalize_party("rhdp")
        "RHDP"
        >>> normalize_party("Pdci")
        "PDCI-RDA"
    """
    if name is None:
        return ""
    # Supprimer les points redondants et normaliser
    # Gérer "R. H. D. P." → supprimer espaces autour des points d'abord
    name_nodotspaces = re.sub(r"\.\s*", ".", name)  # "R. H." → "R.H."
    cleaned = normalize_text(name_nodotspaces)
    cleaned_nodots = re.sub(r"\.", "", cleaned).strip()

    # Chercher dans les alias
    for alias, canonical in PARTY_ALIASES.items():
        alias_norm = normalize_text(alias)
        alias_nodots = re.sub(r"\.", "", alias_norm).strip()
        if cleaned == alias_norm or cleaned_nodots == alias_nodots:
            return canonical

    # Retourner en majuscules si pas trouvé
    return name.upper().strip()


def normalize_region(name: str) -> str:
    """Normalise un nom de région.

    Args:
        name: Nom brut de la région.

    Returns:
        Nom normalisé en majuscules.
    """
    return normalize_text(name).upper()


def normalize_circonscription(name: str) -> str:
    """Normalise un nom de circonscription.

    Args:
        name: Nom brut de la circonscription.

    Returns:
        Nom normalisé.
    """
    return normalize_text(name).upper()


def fuzzy_match(
    query: str, candidates: list[str], threshold: float = 0.7
) -> str | None:
    """Retourne le meilleur match parmi les candidats ou None si score < threshold.

    Utilise difflib.SequenceMatcher pour calculer la similarité.

    Args:
        query: Chaîne à rechercher.
        candidates: Liste des candidats à comparer.
        threshold: Score minimum de similarité (0.0 à 1.0).

    Returns:
        Meilleur candidat ou None si score insuffisant.

    Examples:
        >>> fuzzy_match("tiapum", ["Tiapoum", "Yamoussoukro"])
        "Tiapoum"
        >>> fuzzy_match("xyz123", ["Abidjan"], threshold=0.7)
        None
    """
    query_norm = normalize_text(query)
    best_match: str | None = None
    best_score = 0.0

    for candidate in candidates:
        candidate_norm = normalize_text(candidate)
        score = difflib.SequenceMatcher(None, query_norm, candidate_norm).ratio()
        # Also compare against individual words of multi-word candidates (e.g. "TIAPOUM"
        # from "TIAPOUM COMMUNE ET SOUS-PREFECTURE") so short user typos don't get
        # penalised by length mismatch against the full name.
        for word in _WORD_RE.findall(candidate_norm):
            if len(word) >= 3:
                word_score = difflib.SequenceMatcher(None, query_norm, word).ratio()
                score = max(score, word_score)
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_score >= threshold:
        logger.debug(f"Fuzzy match: '{query}' → '{best_match}' (score={best_score:.2f})")
        return best_match

    logger.debug(f"Pas de fuzzy match pour '{query}' (meilleur score={best_score:.2f})")
    return None
