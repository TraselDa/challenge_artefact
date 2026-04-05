"""Détection d'ambiguïté et génération de questions de clarification (Level 3)."""

import logging
from dataclasses import dataclass, field

from openai import OpenAI

from src.llm_client import get_client

logger = logging.getLogger(__name__)

CLARIFIER_SYSTEM_PROMPT = """Tu es un assistant qui pose des questions de clarification
en français, de manière naturelle et concise. Tu proposes les options disponibles
sous forme de liste numérotée. Tu ne réponds qu'en français."""


@dataclass
class ClarificationRequest:
    """Résultat de la vérification d'ambiguïté."""

    is_ambiguous: bool
    question: str | None  # Question de clarification à poser
    options: list[str] = field(default_factory=list)  # Options proposées
    original_question: str = ""


class Clarifier:
    """Détecte les ambiguïtés et génère des questions de clarification."""

    def __init__(self, db_path: str) -> None:
        """Initialise le clarifier.

        Args:
            db_path: Chemin vers edan.duckdb (pour rechercher les entités).
        """
        self.db_path = db_path
        self.client: OpenAI = get_client()

    def check_ambiguity(self, question: str, entity: str) -> ClarificationRequest:
        """Vérifie si une entité est ambiguë dans le dataset.

        Ex: "Abidjan" → plusieurs circonscriptions → demander laquelle.

        Args:
            question: Question originale de l'utilisateur.
            entity: Entité à vérifier (nom de lieu, etc.).

        Returns:
            ClarificationRequest avec les options si ambigu.
        """
        matching = self._get_matching_circonscriptions(entity)

        if len(matching) <= 1:
            return ClarificationRequest(
                is_ambiguous=False,
                question=None,
                options=matching,
                original_question=question,
            )

        clarification_q = self.generate_clarification(question, matching)

        return ClarificationRequest(
            is_ambiguous=True,
            question=clarification_q,
            options=matching,
            original_question=question,
        )

    def _get_matching_circonscriptions(self, name: str) -> list[str]:
        """Recherche les circonscriptions matchant le nom dans DuckDB.

        Args:
            name: Nom (partiel) de la circonscription ou région.

        Returns:
            Liste des noms de circonscriptions correspondants.
        """
        try:
            import duckdb

            conn = duckdb.connect(str(self.db_path), read_only=True)
            rows = conn.execute(
                """
                SELECT DISTINCT circonscription
                FROM vw_results_by_circonscription
                WHERE LOWER(circonscription) LIKE ?
                   OR LOWER(region) LIKE ?
                ORDER BY circonscription
                LIMIT 20
                """,
                [f"%{name.lower()}%", f"%{name.lower()}%"],
            ).fetchall()
            conn.close()
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Erreur recherche circonscriptions: {e}")
            return []

    def generate_clarification(self, question: str, options: list[str]) -> str:
        """Génère une question de clarification élégante en français.

        Args:
            question: Question originale de l'utilisateur.
            options: Liste des options à proposer.

        Returns:
            Question de clarification formatée.
        """
        options_text = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options[:10]))

        prompt = (
            f"L'utilisateur a posé cette question : \"{question}\"\n\n"
            f"Il y a plusieurs circonscriptions correspondantes :\n{options_text}\n\n"
            f"Génère une question de clarification courte et naturelle en français, "
            f"demandant à l'utilisateur de préciser laquelle il veut."
        )

        try:
            from src.llm_client import chat

            return chat(
                self.client,
                model="anthropic/claude-haiku-4-5",  # Modèle léger pour la clarification
                system=CLARIFIER_SYSTEM_PROMPT,
                user=prompt,
                max_tokens=256,
            )
        except Exception as e:
            logger.warning(f"Erreur LLM clarification: {e}")
            # Fallback: question générique
            opts_str = ", ".join(options[:5])
            return (
                f"Pourriez-vous préciser à quelle circonscription vous faites référence ? "
                f"Options disponibles : {opts_str}"
            )
