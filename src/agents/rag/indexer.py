"""Indexation des données électorales dans ChromaDB."""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
COLLECTION_NAME = "edan_results"


def build_index(
    db_path: str,
    chroma_path: str,
    force_rebuild: bool = False,
) -> Any:
    """Construit ou charge l'index ChromaDB depuis DuckDB.

    Indexe chaque ligne de results comme un document texte.

    Args:
        db_path: Chemin vers edan.duckdb.
        chroma_path: Répertoire de persistance ChromaDB.
        force_rebuild: Si True, recrée l'index même s'il existe.

    Returns:
        Collection ChromaDB.
    """
    import chromadb
    import duckdb
    from chromadb.utils import embedding_functions

    chroma_dir = Path(chroma_path)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(chroma_dir))

    # Lire le hash du PDF depuis .data_version si disponible
    pdf_hash: str | None = None
    db_path_obj = Path(db_path)
    version_file = db_path_obj.parent / ".data_version"
    if version_file.exists():
        try:
            import json as _json
            version_info = _json.loads(version_file.read_text(encoding="utf-8"))
            pdf_hash = version_info.get("pdf_hash")
        except Exception:
            pass

    # Vérifier si l'index existe déjà
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing and not force_rebuild:
        # Vérifier la cohérence du hash
        try:
            existing_col = client.get_collection(COLLECTION_NAME)
            stored_hash = existing_col.metadata.get("pdf_hash") if existing_col.metadata else None
            if pdf_hash and stored_hash and stored_hash != pdf_hash:
                logger.warning(
                    "Hash mismatch: index ChromaDB créé avec hash %s... mais .data_version a %s... "
                    "Relancez 'make ingest' pour reconstruire l'index.",
                    stored_hash[:12], pdf_hash[:12],
                )
        except Exception:
            pass
        logger.info(f"Index ChromaDB existant chargé depuis {chroma_path}")
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        return client.get_collection(COLLECTION_NAME, embedding_function=ef)

    logger.info(f"Construction de l'index ChromaDB dans {chroma_path}")

    # Supprimer l'ancienne collection si rebuild
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    collection = client.create_collection(
        COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine", "pdf_hash": pdf_hash or ""},
    )

    # Charger les données depuis DuckDB
    conn = duckdb.connect(str(db_path), read_only=True)
    rows = conn.execute(
        "SELECT * FROM results ORDER BY numero_circonscription, scores DESC"
    ).fetchall()
    columns = [desc[0] for desc in conn.description]  # type: ignore
    conn.close()

    if not rows:
        logger.warning("Aucune donnée à indexer dans ChromaDB")
        return collection

    # Construire les documents, métadonnées et IDs
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for i, row in enumerate(rows):
        row_dict = dict(zip(columns, row))
        doc_id, document, metadata = _row_to_document(row_dict, i)
        ids.append(doc_id)
        documents.append(document)
        metadatas.append(metadata)

    # Indexer par batch de 500
    batch_size = 500
    for start in range(0, len(documents), batch_size):
        end = min(start + batch_size, len(documents))
        collection.add(
            ids=ids[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )
        logger.debug(f"Indexé {end}/{len(documents)} documents")

    logger.info(f"Index ChromaDB construit: {len(documents)} documents")
    return collection


def _row_to_document(
    row: dict[str, Any], idx: int
) -> tuple[str, str, dict[str, Any]]:
    """Convertit une ligne de results en (id, document, metadata).

    Args:
        row: Dictionnaire représentant une ligne de la table results.
        idx: Index unique pour l'ID.

    Returns:
        Tuple (id, document_texte, metadata).
    """
    circ_num = row.get("numero_circonscription", 0)
    region = row.get("region", "")
    circo = row.get("circonscription", "")
    parti = row.get("parti", "")
    candidat = row.get("candidat", "")
    scores = row.get("scores", 0)
    score_pct = row.get("score_pct", 0.0)
    elu = row.get("elu", False)

    # Texte descriptif naturel pour l'embedding
    elu_str = "Candidat élu." if elu else ""
    document = (
        f"Circonscription {circ_num} ({circo}, région {region}): "
        f"{candidat} du parti {parti} a obtenu {scores} voix ({score_pct:.1f}%). "
        f"{elu_str}"
    ).strip()

    source_page = row.get("source_page")
    doc_id = f"result_{circ_num}_{idx}"

    metadata: dict[str, Any] = {
        "region": str(region),
        "numero_circonscription": int(circ_num) if circ_num else 0,
        "circonscription": str(circo),
        "parti": str(parti),
        "candidat": str(candidat),
        "scores": int(scores) if scores else 0,
        "elu": bool(elu),
        "table_id": "results",
        "row_id": doc_id,
        "source_page": int(source_page) if source_page is not None else 0,
    }

    return doc_id, document, metadata


def get_or_create_collection(client: Any) -> Any:
    """Retourne la collection existante ou la crée (vide).

    Args:
        client: Client ChromaDB.

    Returns:
        Collection ChromaDB.
    """
    from chromadb.utils import embedding_functions

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        return client.get_collection(COLLECTION_NAME, embedding_function=ef)
    return client.create_collection(COLLECTION_NAME, embedding_function=ef)
