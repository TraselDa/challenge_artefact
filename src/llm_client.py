"""Factory pour le client LLM via OpenRouter (API compatible OpenAI)."""

import contextvars
import logging
import os
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Modèle par défaut (format OpenRouter : provider/model-name)
DEFAULT_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")

# Compteur de tokens par requête (async-safe via ContextVar)
_token_counter: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "token_counter", default=None
)


def init_token_counter() -> dict[str, int]:
    """Initialise un compteur de tokens pour la requête courante."""
    counter: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    _token_counter.set(counter)
    return counter


def get_token_usage() -> dict[str, int]:
    """Retourne les tokens accumulés pour la requête courante."""
    counter = _token_counter.get(None)
    return dict(counter) if counter else {}


def get_client() -> OpenAI:
    """Retourne un client OpenAI configuré pour OpenRouter.

    Utilise la variable d'environnement OPENROUTER_API_KEY.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("OPENROUTER_API_KEY non définie — les appels LLM échoueront.")
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key or "missing",
    )


def chat(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> str:
    """Appel LLM simplifié : system + user → texte réponse.

    Args:
        client: Client OpenAI/OpenRouter.
        model: Identifiant du modèle (ex: "anthropic/claude-sonnet-4-5").
        system: Prompt système.
        user: Message utilisateur.
        max_tokens: Nombre max de tokens dans la réponse.
        temperature: Température (None = défaut modèle, 0 = déterministe).

    Returns:
        Contenu texte de la réponse.

    Raises:
        openai.APIError: En cas d'erreur API.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = client.chat.completions.create(**kwargs)
    if response.usage:
        counter = _token_counter.get(None)
        if counter is not None:
            counter["input_tokens"] += response.usage.prompt_tokens or 0
            counter["output_tokens"] += response.usage.completion_tokens or 0
    return response.choices[0].message.content or ""
