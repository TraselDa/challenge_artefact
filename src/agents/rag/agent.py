"""Agent RAG pour les recherches floues et narratives."""

import logging
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from src.agents.rag.normalizer import normalize_text
from src.agents.rag.retriever import RAGResult, search
from src.llm_client import DEFAULT_MODEL, get_client

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """Tu es un assistant expert en données électorales de Côte d'Ivoire.
Tu réponds UNIQUEMENT en français.
Tu utilises UNIQUEMENT les documents fournis pour répondre.
Si les documents ne contiennent pas l'information demandée, dis-le clairement.
Cite les sources (circonscription, candidat, parti) quand pertinent.
Sois précis et factuel. Ne fais pas de suppositions."""


@dataclass
class RAGResponse:
    """Réponse de l'agent RAG."""

    answer: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 à 1.0
    retrieved_docs: list[RAGResult] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)


class RAGAgent:
    """Agent RAG pour les questions narratives ou avec entités floues."""

    def __init__(
        self,
        chroma_path: str,
        model: str = DEFAULT_MODEL,
    ) -> None:
        """Initialise l'agent RAG.

        Args:
            chroma_path: Répertoire de persistance ChromaDB.
            model: Identifiant du modèle (format OpenRouter).
        """
        self.chroma_path = chroma_path
        self.model = model
        self.client: OpenAI = get_client()
        self._collection: Any = None

    def _get_collection(self) -> Any:
        """Charge ou retourne la collection ChromaDB (lazy loading)."""
        if self._collection is None:
            try:
                import chromadb

                from src.agents.rag.indexer import get_or_create_collection

                client = chromadb.PersistentClient(path=self.chroma_path)
                self._collection = get_or_create_collection(client)
                logger.info("Collection ChromaDB chargée")
            except Exception as e:
                logger.error(f"Erreur chargement ChromaDB: {e}")
                raise
        return self._collection

    def answer(
        self,
        question: str,
        normalized_question: str | None = None,
    ) -> RAGResponse:
        """Répond à une question via RAG.

        Pipeline:
        1. Normalise la question
        2. Recherche dans ChromaDB
        3. Génère une réponse avec les documents récupérés
        4. Cite les sources

        Args:
            question: Question originale de l'utilisateur.
            normalized_question: Version normalisée (optionnel).

        Returns:
            RAGResponse avec la réponse et les sources.
        """
        search_query = normalized_question or normalize_text(question)

        try:
            collection = self._get_collection()
            doc_count = collection.count()
        except Exception as e:
            logger.error(f"RAG indisponible: {e}")
            return RAGResponse(
                answer=(
                    "Le service de recherche sémantique n'est pas disponible. "
                    "Veuillez relancer l'ingestion avec `make ingest`."
                ),
                confidence=0.0,
            )

        if doc_count == 0:
            logger.warning("Index ChromaDB vide")
            return RAGResponse(
                answer=(
                    "L'index de recherche est vide. "
                    "Veuillez relancer l'ingestion avec `make ingest`."
                ),
                confidence=0.0,
            )

        # Recherche sémantique
        retrieved = search(search_query, collection, n_results=8)

        if not retrieved:
            return RAGResponse(
                answer=(
                    "Je n'ai pas trouvé d'information pertinente dans le dataset "
                    "pour cette question."
                ),
                sources=[],
                confidence=0.0,
                retrieved_docs=[],
            )

        # Calculer la confiance (inverse de la distance moyenne)
        avg_distance = sum(r.distance for r in retrieved) / len(retrieved)
        confidence = max(0.0, min(1.0, 1.0 - avg_distance))

        # Générer la réponse narrative
        answer_text = self._generate_answer(question, retrieved)

        # Extraire les sources
        sources = list({r.page_source for r in retrieved if r.page_source})

        # Construire la provenance structurée
        provenance: list[dict[str, Any]] = [
            {
                "row_id": r.row_id,
                "table_id": r.table_id,
                "source_page": r.page_source,
                "excerpt": r.excerpt,
                "circonscription": r.metadata.get("circonscription", ""),
                "candidat": r.metadata.get("candidat", ""),
                "parti": r.metadata.get("parti", ""),
            }
            for r in retrieved
        ]

        return RAGResponse(
            answer=answer_text,
            sources=sources,
            confidence=confidence,
            retrieved_docs=retrieved,
            provenance=provenance,
        )

    def _generate_answer(
        self,
        question: str,
        context_docs: list[RAGResult],
    ) -> str:
        """Génère la réponse narrative avec le LLM.

        Args:
            question: Question de l'utilisateur.
            context_docs: Documents récupérés par ChromaDB.

        Returns:
            Réponse narrative en français.
        """
        context = "\n\n".join(
            f"[Source: {doc.page_source}]\n{doc.document}"
            for doc in context_docs
        )

        user_message = (
            f"Voici les données disponibles :\n\n{context}\n\n"
            f"Question : {question}"
        )

        try:
            from src.llm_client import chat

            return chat(
                self.client,
                model=self.model,
                system=RAG_SYSTEM_PROMPT,
                user=user_message,
                max_tokens=1024,
            )
        except Exception as e:
            logger.error(f"Erreur LLM RAG: {e}")
            # Fallback: synthèse des documents
            return (
                "Voici les informations trouvées :\n\n"
                + "\n".join(f"• {doc.document}" for doc in context_docs[:3])
            )
