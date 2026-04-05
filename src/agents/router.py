"""Routeur d'intent: SQL vs RAG vs Chart vs Refus vs Clarification."""

import logging
from dataclasses import dataclass
from enum import StrEnum

from openai import OpenAI

from src.agents.rag.normalizer import normalize_text
from src.llm_client import DEFAULT_MODEL, get_client

logger = logging.getLogger(__name__)


class Intent(StrEnum):
    """Types d'intent possibles."""

    SQL = "sql"
    SQL_CHART = "sql_chart"
    RAG = "rag"
    OUT_OF_SCOPE = "out_of_scope"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass
class RouterDecision:
    """Décision du routeur."""

    intent: Intent
    confidence: float
    reason: str
    normalized_query: str = ""
    clarification_question: str | None = None


# Mots-clés pour le routing rapide
SQL_KEYWORDS = frozenset({
    "combien", "total", "somme", "nombre", "top", "classement",
    "pourcentage", "taux", "liste", "quels", "quelles",
    "tous les", "toutes les", "par région", "par parti", "compter",
    "maximum", "minimum", "moyenne", "plus", "moins", "rank",
    "quel est le", "quels sont", "combien de",
})

CHART_KEYWORDS = frozenset({
    "histogramme", "graphique", "diagramme", "chart", "courbe",
    "camembert", "pie", "bar", "visualise", "montre graphiquement",
    "représente", "trace", "plot",
})

RAG_KEYWORDS = frozenset({
    "qui est", "parle-moi de", "raconte", "explique", "contexte",
    "information sur", "détails sur", "qu'est-ce que", "tell me about",
    "describe", "présente",
})

OUT_OF_SCOPE_KEYWORDS = frozenset({
    # Accents stripped (normalized before matching)
    "meteo", "president", "premier ministre", "constitution",
    "sport", "foot", "football", "musique", "cinema", "covid",
    "guerre", "militaire", "api key", "system prompt", "cle api",
    "ignore", "oublie", "instruction", "jailbreak", "prompt injection",
    # Government / economy topics
    "ministre", "gouvernement", "pib", "economie", "budget",
    "coupe du monde", "moteur", "reaction", "physique", "chimie",
    # Jailbreak patterns (English)
    "forget", "pretend", "act as", "no restriction", "freely",
    "dan ", "do anything now", "unconstrained",
})

# Entités potentiellement ambiguës (plusieurs circonscriptions)
AMBIGUOUS_ENTITIES: dict[str, list[str]] = {
    "abidjan": [
        "plusieurs circonscriptions dans la région ABIDJAN "
        "(commune, sous-préfecture...)"
    ],
    "yamoussoukro": ["commune et sous-préfecture de Yamoussoukro"],
    "grand-bassam": ["commune et sous-préfecture de Grand-Bassam"],
    "divo": ["commune et sous-préfecture de Divo"],
    "daloa": ["commune et sous-préfecture de Daloa"],
    "bouaké": ["commune et sous-préfecture de Bouaké"],
    "korhogo": ["commune et sous-préfecture de Korhogo"],
}

ROUTER_SYSTEM_PROMPT = """Tu es un routeur d'intent pour une application d'analyse des résultats
électoraux de Côte d'Ivoire (scrutin 27 décembre 2025).

Classifie la question dans l'une de ces catégories:
- "sql": question analytique (chiffres, agrégations, classements, listes)
- "sql_chart": question qui demande un graphique/visualisation
- "rag": recherche floue, entité avec typo, question narrative
- "out_of_scope": hors du dataset (météo, politique générale, sécurité, etc.)
- "needs_clarification": entité ambiguë (ex: "Abidjan" sans précision)

Réponds UNIQUEMENT avec un JSON valide:
{"intent": "sql|sql_chart|rag|out_of_scope|needs_clarification", "confidence": 0.9, "reason": "..."}
"""


class IntentRouter:
    """Routeur d'intent pour diriger les questions vers le bon agent."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        """Initialise le routeur.

        Args:
            model: Identifiant du modèle (format OpenRouter).
        """
        self.model = model
        self.client: OpenAI = get_client()

    def route(self, question: str) -> RouterDecision:
        """Détermine l'intent de la question.

        Pipeline:
        1. Vérification rapide des keywords hors-scope
        2. Vérification des entités ambiguës (Level 3)
        3. Détection chart keywords
        4. Classification LLM si ambiguïté

        Args:
            question: Question de l'utilisateur en français.

        Returns:
            RouterDecision avec l'intent et la confidence.
        """
        normalized = normalize_text(question)

        # 1. Vérification hors-scope (prioritaire)
        keyword_decision = self._keyword_based_route(normalized)
        if keyword_decision and keyword_decision.intent == Intent.OUT_OF_SCOPE:
            keyword_decision.normalized_query = normalized
            return keyword_decision

        # 2. Vérification entités ambiguës
        if self._check_ambiguous_entities(normalized):
            return RouterDecision(
                intent=Intent.NEEDS_CLARIFICATION,
                confidence=0.85,
                reason="Entité géographique ambiguë détectée",
                normalized_query=normalized,
            )

        # 3. Détection rapide des charts
        if any(kw in normalized for kw in CHART_KEYWORDS):
            return RouterDecision(
                intent=Intent.SQL_CHART,
                confidence=0.9,
                reason="Mot-clé de visualisation détecté",
                normalized_query=normalized,
            )

        # 4. Détection rapide SQL
        if keyword_decision and keyword_decision.intent == Intent.SQL:
            keyword_decision.normalized_query = normalized
            return keyword_decision

        # 5. Classification LLM pour les cas ambigus
        try:
            llm_decision = self._llm_based_route(question)
            llm_decision.normalized_query = normalized
            return llm_decision
        except Exception as e:
            logger.warning(f"Routage LLM échoué ({e}), fallback SQL")
            return RouterDecision(
                intent=Intent.SQL,
                confidence=0.5,
                reason="Fallback: routage LLM indisponible",
                normalized_query=normalized,
            )

    def _keyword_based_route(self, normalized_question: str) -> RouterDecision | None:
        """Routing rapide basé sur mots-clés avant d'appeler le LLM.

        Args:
            normalized_question: Question normalisée (lowercase, sans accents).

        Returns:
            RouterDecision ou None si indéterminé.
        """
        # Vérifier hors-scope
        if any(kw in normalized_question for kw in OUT_OF_SCOPE_KEYWORDS):
            return RouterDecision(
                intent=Intent.OUT_OF_SCOPE,
                confidence=0.95,
                reason="Mot-clé hors-scope détecté",
            )

        # Vérifier SQL analytique
        if any(kw in normalized_question for kw in SQL_KEYWORDS):
            return RouterDecision(
                intent=Intent.SQL,
                confidence=0.85,
                reason="Mot-clé analytique SQL détecté",
            )

        # Vérifier RAG narratif
        if any(kw in normalized_question for kw in RAG_KEYWORDS):
            return RouterDecision(
                intent=Intent.RAG,
                confidence=0.8,
                reason="Mot-clé narratif RAG détecté",
            )

        return None

    def _llm_based_route(self, question: str) -> RouterDecision:
        """Classification LLM pour les cas ambigus.

        Args:
            question: Question originale de l'utilisateur.

        Returns:
            RouterDecision basée sur la réponse du LLM.
        """
        import json

        from src.llm_client import chat

        text = chat(
            self.client,
            model=self.model,
            system=ROUTER_SYSTEM_PROMPT,
            user=question,
            max_tokens=256,
        )

        # Parser le JSON
        try:
            # Extraire le JSON si entouré de texte
            import re
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(text)

            intent_str = data.get("intent", "sql")
            try:
                intent = Intent(intent_str)
            except ValueError:
                intent = Intent.SQL

            return RouterDecision(
                intent=intent,
                confidence=float(data.get("confidence", 0.7)),
                reason=data.get("reason", "Classification LLM"),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Parsing JSON routeur échoué: {e} — texte: {text}")
            # If LLM refused to classify (ethical refusal), treat as out_of_scope
            refusal_indicators = ["cannot", "je ne peux", "ethics", "ethique", "harmless"]
            if any(ind in text.lower() for ind in refusal_indicators):
                return RouterDecision(
                    intent=Intent.OUT_OF_SCOPE,
                    confidence=0.8,
                    reason="Fallback: LLM a refusé de classifier (question non sûre)",
                )
            return RouterDecision(
                intent=Intent.SQL,
                confidence=0.5,
                reason="Fallback: parsing JSON échoué",
            )

    def _check_ambiguous_entities(self, normalized_question: str) -> bool:
        """Vérifie si la question contient des entités ambiguës.

        Args:
            normalized_question: Question normalisée.

        Returns:
            True si une entité ambiguë est détectée.
        """
        for entity in AMBIGUOUS_ENTITIES:
            if entity in normalized_question:
                # Vérifier si une précision est déjà donnée (ex: "commune", numéro)
                if "commune" in normalized_question or "sous-prefecture" in normalized_question:
                    return False
                return True
        return False
