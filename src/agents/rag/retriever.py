"""Recherche sémantique dans ChromaDB."""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RAGResult:
    """Résultat d'une recherche RAG."""

    document: str
    metadata: dict[str, Any]
    distance: float
    page_source: str = ""
    row_id: str = ""
    table_id: str = ""
    excerpt: str = ""


def _format_page_source(meta: dict[str, Any], circ_num: Any) -> str:
    """Formate la source de page depuis les métadonnées ChromaDB.

    Préfère le numéro de page PDF réel (source_page) à l'identifiant de circonscription.
    """
    raw = meta.get("source_page")
    if raw and int(raw) > 0:
        return f"Page {int(raw)} (Circ. {circ_num})"
    return f"Circonscription {circ_num}"


def search(
    query: str,
    collection: Any,
    n_results: int = 5,
) -> list[RAGResult]:
    """Recherche sémantique dans l'index ChromaDB.

    Args:
        query: Question ou texte à rechercher.
        collection: Collection ChromaDB.
        n_results: Nombre de résultats à retourner.

    Returns:
        Liste de RAGResult triés par pertinence.
    """
    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.error(f"Erreur recherche ChromaDB: {e}")
        return []

    rag_results: list[RAGResult] = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, distances):
        circ_num = meta.get("numero_circonscription", "?")
        row_id = meta.get("row_id", f"result_{circ_num}")
        rag_results.append(
            RAGResult(
                document=doc,
                metadata=meta,
                distance=float(dist),
                page_source=_format_page_source(meta, circ_num),
                row_id=row_id,
                table_id=meta.get("table_id", "results"),
                excerpt=doc[:300],
            )
        )

    logger.debug(f"Recherche RAG '{query}': {len(rag_results)} résultats")
    return rag_results


def search_by_entity(
    entity: str,
    entity_type: str,
    collection: Any,
    n_results: int = 10,
) -> list[RAGResult]:
    """Recherche par entité avec filtre sur les métadonnées.

    Args:
        entity: Valeur de l'entité à rechercher.
        entity_type: Type d'entité ("circonscription", "candidat", "parti").
        collection: Collection ChromaDB.
        n_results: Nombre de résultats.

    Returns:
        Liste de RAGResult filtrés.
    """
    where_filter: dict[str, Any] | None = None

    if entity_type == "parti":
        where_filter = {"parti": {"$eq": entity.upper()}}
    elif entity_type == "candidat":
        where_filter = {"candidat": {"$eq": entity.upper()}}
    elif entity_type == "circonscription":
        where_filter = {"circonscription": {"$contains": entity.upper()}}

    try:
        kwargs: dict[str, Any] = {
            "query_texts": [entity],
            "n_results": min(n_results, collection.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = collection.query(**kwargs)
    except Exception as e:
        logger.warning(f"Recherche filtrée échouée ({e}), fallback sur recherche simple")
        return search(entity, collection, n_results)

    rag_results: list[RAGResult] = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, distances):
        circ_num = meta.get("numero_circonscription", "?")
        row_id = meta.get("row_id", f"result_{circ_num}")
        rag_results.append(
            RAGResult(
                document=doc,
                metadata=meta,
                distance=float(dist),
                page_source=_format_page_source(meta, circ_num),
                row_id=row_id,
                table_id=meta.get("table_id", "results"),
                excerpt=doc[:300],
            )
        )

    return rag_results
