#!/usr/bin/env python3
"""Script principal d'ingestion: PDF → DuckDB.

Usage:
    python scripts/ingest.py
    python scripts/ingest.py --pdf data/raw/EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf
    python scripts/ingest.py --db data/processed/edan.duckdb
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest")


def main() -> None:
    """Point d'entrée principal du script d'ingestion."""
    parser = argparse.ArgumentParser(description="Ingestion PDF → DuckDB pour EDAN 2025")
    parser.add_argument(
        "--pdf",
        default="data/raw/EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf",
        help="Chemin vers le PDF source",
    )
    parser.add_argument(
        "--db",
        default=os.getenv("DUCKDB_PATH", "data/processed/edan.duckdb"),
        help="Chemin vers la base DuckDB",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    db_path = Path(args.db)

    logger.info("=" * 60)
    logger.info("EDAN 2025 — Pipeline d'ingestion")
    logger.info("=" * 60)
    logger.info(f"PDF source : {pdf_path}")
    logger.info(f"DuckDB     : {db_path}")

    # 1. Vérifier que le PDF existe
    if not pdf_path.exists():
        logger.error(f"PDF non trouvé: {pdf_path}")
        logger.error("Placez le fichier PDF dans data/raw/ et relancez.")
        sys.exit(1)

    # 2. Extraction PDF
    logger.info("\n[1/5] Extraction du PDF...")
    from src.ingestion.pdf_extractor import extract_pdf

    df_raw, summary_dict = extract_pdf(pdf_path)
    logger.info(f"      → {df_raw.shape[0]} lignes extraites")

    if df_raw.empty:
        logger.error("Aucune donnée extraite du PDF. Vérifiez le format du fichier.")
        sys.exit(1)

    # 3. Nettoyage
    logger.info("\n[2/5] Nettoyage et normalisation...")
    from src.ingestion.cleaner import clean_dataframe

    df_clean = clean_dataframe(df_raw)
    logger.info(f"      → {df_clean.shape[0]} lignes après nettoyage")

    # 4. Connexion DuckDB et création du schéma
    logger.info("\n[3/5] Création du schéma DuckDB...")
    from src.ingestion.loader import (
        create_schema,
        create_views,
        get_connection,
        load_results,
        load_summary_national,
    )

    conn = get_connection(db_path, read_only=False)
    create_schema(conn)

    # 5. Chargement des données
    logger.info("\n[4/5] Chargement des données...")
    nb_rows = load_results(conn, df_clean)
    load_summary_national(conn, summary_dict)
    create_views(conn)
    conn.close()

    logger.info(f"      → {nb_rows} candidats chargés")

    # 6. Validation
    logger.info("\n[5/5] Validation...")
    from src.ingestion.validator import validate

    report = validate(db_path)

    if not report.passed:
        logger.error("\n❌ Ingestion terminée avec des erreurs. Vérifiez les logs ci-dessus.")
        sys.exit(1)

    # 5b. Écriture du fichier de version
    from src.agents.rag.indexer import EMBEDDING_MODEL
    pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    version_info = {
        "pdf_hash": pdf_hash,
        "ingest_timestamp": datetime.now(UTC).isoformat(),
        "embedding_model": EMBEDDING_MODEL,
        "schema_version": "1.0",
        "pdf_path": str(pdf_path),
    }
    version_path = db_path.parent / ".data_version"
    version_path.write_text(json.dumps(version_info, indent=2, ensure_ascii=False))
    logger.info("Version dataset: hash=%s...", pdf_hash[:12])

    # 7. Reconstruction de l'index ChromaDB (force_rebuild=True car le schéma DuckDB a changé)
    chroma_path = os.getenv("CHROMA_PERSIST_DIR", "data/processed/chroma")
    logger.info(f"\n[6/6] Reconstruction de l'index ChromaDB ({chroma_path})...")
    try:
        from src.agents.rag.indexer import build_index

        build_index(db_path=str(db_path), chroma_path=chroma_path, force_rebuild=True)
        logger.info("      → Index ChromaDB reconstruit")
    except ImportError:
        logger.warning("      → ChromaDB non disponible (pip install chromadb), index ignoré")
    except Exception as e:
        logger.warning(f"      → Erreur reconstruction ChromaDB (non bloquant): {e}")

    logger.info("\n✅ Ingestion terminée avec succès!")
    logger.info(f"   Base de données : {db_path}")
    logger.info(f"   Index vectoriel : {chroma_path}")


if __name__ == "__main__":
    main()
