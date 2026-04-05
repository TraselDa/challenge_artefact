"""Application FastAPI principale — EDAN 2025 Chat with Election Data."""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from src.api.routes.chat import router as chat_router
from src.api.routes.health import router as health_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# State global partagé entre les routes
app_state: dict[str, Any] = {}


@asynccontextmanager  # type: ignore[arg-type]
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Initialise les agents au démarrage, libère les ressources à l'arrêt."""
    from src.agents.clarifier import Clarifier
    from src.agents.rag.agent import RAGAgent
    from src.agents.router import IntentRouter
    from src.agents.text_to_sql.agent import TextToSQLAgent

    db_path = os.getenv("DUCKDB_PATH", "data/processed/edan.duckdb")
    chroma_path = os.getenv("CHROMA_PERSIST_DIR", "data/processed/chroma")
    model = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514")

    logger.info("Initialisation des agents (db=%s, model=%s)", db_path, model)

    app_state["sql_agent"] = TextToSQLAgent(db_path=db_path, model=model)
    app_state["rag_agent"] = RAGAgent(chroma_path=chroma_path, model=model)
    app_state["router"] = IntentRouter(model=model)
    app_state["clarifier"] = Clarifier(db_path=db_path)
    app_state["session_store"] = {}  # {session_id: {"pending_clarification": ..., "entity_choices": ...}}

    logger.info("Tous les agents sont initialisés.")
    yield

    app_state.clear()
    logger.info("Ressources libérées.")


def create_application() -> FastAPI:
    """Factory pattern: crée et configure l'application FastAPI."""
    application = FastAPI(
        title="EDAN 2025 — Chat with Election Data",
        description=(
            "API de chat pour interroger les résultats des élections législatives "
            "ivoiriennes du 27 décembre 2025."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    application.include_router(chat_router, prefix="/api")
    application.include_router(health_router, prefix="/api")
    return application


app = create_application()
