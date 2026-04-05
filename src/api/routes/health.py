"""Endpoint de santé — GET /api/health."""

import logging
import os

import duckdb
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Réponse de l'endpoint de santé."""

    status: str
    db_connected: bool
    db_rows: int | None
    agents_ready: bool


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Vérifie que l'API et la base de données sont opérationnelles."""
    from src.api.main import app_state

    db_path = os.getenv("DUCKDB_PATH", "data/processed/edan.duckdb")
    db_connected = False
    db_rows: int | None = None

    try:
        conn = duckdb.connect(db_path, read_only=True)
        result = conn.execute("SELECT COUNT(*) FROM results").fetchone()
        db_rows = result[0] if result else 0
        db_connected = True
        conn.close()
    except Exception as exc:
        logger.warning("Health check DB failed: %s", exc)

    agents_ready = all(
        key in app_state for key in ("sql_agent", "rag_agent", "router")
    )

    overall_status = "ok" if (db_connected and agents_ready) else "degraded"

    return HealthResponse(
        status=overall_status,
        db_connected=db_connected,
        db_rows=db_rows,
        agents_ready=agents_ready,
    )
