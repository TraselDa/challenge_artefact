"""Factory pour le client LLM via OpenRouter (API compatible OpenAI)."""

import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Modèle par défaut (format OpenRouter : provider/model-name)
DEFAULT_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")


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
) -> str:
    """Appel LLM simplifié : system + user → texte réponse.

    Args:
        client: Client OpenAI/OpenRouter.
        model: Identifiant du modèle (ex: "anthropic/claude-sonnet-4-5").
        system: Prompt système.
        user: Message utilisateur.
        max_tokens: Nombre max de tokens dans la réponse.

    Returns:
        Contenu texte de la réponse.

    Raises:
        openai.APIError: En cas d'erreur API.
    """
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""
