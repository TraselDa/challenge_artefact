"""Formatage des résultats SQL en réponses narratives."""

import logging
from typing import Any

from openai import OpenAI

from src.llm_client import DEFAULT_MODEL

logger = logging.getLogger(__name__)

FORMATTER_SYSTEM_PROMPT = """Tu es un assistant qui transforme des résultats de requêtes SQL
sur les élections ivoiriennes en réponses claires et naturelles en français.

Règles:
- Réponds TOUJOURS en français
- Sois concis et factuel
- Présente les chiffres de façon lisible (ex: "8 597 092" plutôt que "8597092")
- Si les résultats sont vides, dis-le clairement
- Ne fais pas de suppositions au-delà des données fournies
- Si c'est une liste longue, résume les points clés
"""


def format_results(
    question: str,
    sql: str,
    results: list[dict[str, Any]],
    llm_client: OpenAI,
    model: str = DEFAULT_MODEL,
) -> str:
    """Génère une réponse narrative en français à partir des résultats SQL.

    Args:
        question: Question originale de l'utilisateur.
        sql: Requête SQL exécutée.
        results: Liste de dictionnaires (rows SQL).
        llm_client: Client Anthropic.
        model: Identifiant du modèle Claude.

    Returns:
        Réponse narrative en français.
    """
    if not results:
        return "Aucun résultat trouvé pour cette question dans le dataset électoral."

    results_text = results_to_text(results)

    user_message = (
        f"Question : {question}\n\n"
        f"Requête SQL exécutée :\n```sql\n{sql}\n```\n\n"
        f"Résultats ({len(results)} ligne(s)) :\n{results_text}"
    )

    try:
        from src.llm_client import chat

        return chat(
            llm_client,
            model=model,
            system=FORMATTER_SYSTEM_PROMPT,
            user=user_message,
            max_tokens=1024,
        )
    except Exception as e:
        logger.error(f"Erreur formatage LLM: {e}")
        # Fallback: retourner les résultats bruts en markdown
        return f"Résultats trouvés :\n\n{results_to_markdown_table(results)}"


def results_to_markdown_table(results: list[dict[str, Any]]) -> str:
    """Convertit les résultats SQL en tableau Markdown.

    Args:
        results: Liste de dictionnaires représentant les lignes SQL.

    Returns:
        Tableau Markdown formaté.
    """
    if not results:
        return "_Aucun résultat._"

    headers = list(results[0].keys())
    header_row = " | ".join(headers)
    separator = " | ".join(["---"] * len(headers))

    rows = []
    for row in results:
        values = [str(row.get(h, "")) for h in headers]
        rows.append(" | ".join(values))

    return f"| {header_row} |\n| {separator} |\n" + "\n".join(f"| {r} |" for r in rows)


def results_to_text(results: list[dict[str, Any]], max_rows: int = 20) -> str:
    """Convertit les résultats SQL en texte simple pour le prompt LLM.

    Args:
        results: Liste de dictionnaires.
        max_rows: Nombre max de lignes à inclure dans le texte.

    Returns:
        Texte lisible avec les résultats.
    """
    if not results:
        return "Aucun résultat."

    lines = []
    for i, row in enumerate(results[:max_rows]):
        parts = [f"{k}={v}" for k, v in row.items()]
        lines.append(f"  {i+1}. " + ", ".join(parts))

    text = "\n".join(lines)
    if len(results) > max_rows:
        text += f"\n  ... et {len(results) - max_rows} lignes supplémentaires."

    return text
