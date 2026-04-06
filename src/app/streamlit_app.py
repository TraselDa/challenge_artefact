"""Interface Streamlit — EDAN 2025 Chat with Election Data."""

import logging
import os
import uuid

import requests  # type: ignore[import-untyped]
import streamlit as st

logger = logging.getLogger(__name__)

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://localhost:8000")

# ── Configuration de la page ────────────────────────────────────────────────
st.set_page_config(
    page_title="EDAN 2025 - Chat Électoral",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS custom ───────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    .main-header {
        background: linear-gradient(135deg, #F77F00, #009A44);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { margin: 0; font-size: 1.8rem; }
    .main-header p  { margin: 0.3rem 0 0; opacity: 0.9; font-size: 0.95rem; }
    .intent-badge {
        font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 10px;
        margin-bottom: 0.4rem; display: inline-block; font-weight: 600;
    }
    .badge-sql    { background:#E3F2FD; color:#1565C0; }
    .badge-chart  { background:#FFF8E1; color:#F57F17; }
    .badge-rag    { background:#F3E5F5; color:#6A1B9A; }
    .badge-out    { background:#FFEBEE; color:#C62828; }
    .badge-clarif { background:#E8F5E9; color:#2E7D32; }
    .source-tag {
        background:#E8F5E9; color:#2E7D32;
        padding:0.2rem 0.6rem; border-radius:12px;
        font-size:0.78rem; margin:0.1rem; display:inline-block;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Constantes ───────────────────────────────────────────────────────────────
EXAMPLE_QUESTIONS: list[str] = [
    "Combien de sièges a gagné le RHDP ?",
    "Top 10 des candidats par score dans la région Agneby-Tiassa",
    "Taux de participation par région",
    "Histogramme des élus par parti",
    "Qui a gagné dans la circonscription 001 ?",
    "Quel est le taux de participation national ?",
    "Quels sont les partis représentés ?",
    "Nombre total de candidats indépendants",
]

INTENT_LABELS: dict[str, tuple[str, str]] = {
    "SQL":                  ("SQL", "badge-sql"),
    "SQL_CHART":            ("SQL + Graphique", "badge-chart"),
    "RAG":                  ("Recherche sémantique", "badge-rag"),
    "OUT_OF_SCOPE":         ("Hors dataset", "badge-out"),
    "NEEDS_CLARIFICATION":  ("Clarification", "badge-clarif"),
}


# ── Fonctions utilitaires ────────────────────────────────────────────────────
def send_question(question: str, session_id: str) -> dict:  # type: ignore[type-arg]
    """Envoie une question à l'API FastAPI.

    Args:
        question: Question de l'utilisateur.
        session_id: Identifiant de session.

    Returns:
        Réponse JSON de l'API.
    """
    resp = requests.post(
        f"{FASTAPI_URL}/api/chat",
        json={"question": question, "session_id": session_id},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def check_api_health() -> bool:
    """Vérifie que l'API FastAPI est accessible."""
    try:
        resp = requests.get(f"{FASTAPI_URL}/api/health", timeout=5)
        return bool(resp.status_code == 200)
    except Exception:
        return False


def load_example_questions() -> list[str]:
    """Retourne la liste des questions exemples."""
    return EXAMPLE_QUESTIONS


def display_response(response: dict) -> None:  # type: ignore[type-arg]
    """Affiche la réponse structurée (texte + graphique + SQL + sources).

    Args:
        response: Réponse JSON de l'API.
    """
    intent = response.get("intent", "")
    answer = response.get("answer", "")
    sql = response.get("sql")
    chart_data = response.get("chart")
    sources = response.get("sources", [])
    latency_ms = response.get("latency_ms", 0)

    # Badge d'intent
    if intent in INTENT_LABELS:
        label, css_class = INTENT_LABELS[intent]
        st.markdown(
            f'<span class="intent-badge {css_class}">{label}</span>',
            unsafe_allow_html=True,
        )

    # Réponse texte
    st.markdown(answer)

    # Graphique Plotly inline
    if chart_data and chart_data.get("chart_json"):
        try:
            import plotly.io as pio
            fig = pio.from_json(chart_data["chart_json"])
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.warning(f"Impossible d'afficher le graphique : {e}")

    # SQL généré
    if sql:
        with st.expander("📊 Requête SQL générée", expanded=False):
            st.code(sql, language="sql")

    # Sources RAG
    if sources:
        sources_html = " ".join(
            f'<span class="source-tag">📍 {s}</span>' for s in sources[:6]
        )
        st.markdown(f"**Sources :** {sources_html}", unsafe_allow_html=True)

    # Provenance détaillée (row_id, table_id, excerpt)
    provenance = response.get("provenance", [])
    if provenance:
        with st.expander(f"🔍 Provenance ({len(provenance)} enregistrements)", expanded=False):
            for p in provenance[:5]:
                row_id = p.get("row_id", "")
                table_id = p.get("table_id", "results")
                source_page = p.get("source_page", "")
                excerpt = p.get("excerpt", "")
                circ = p.get("circonscription", "")
                candidat = p.get("candidat", "")
                parti = p.get("parti", "")

                cols = st.columns([1, 2, 3])
                with cols[0]:
                    if source_page:
                        st.caption(f"**{source_page}**")
                    st.caption(f"table: `{table_id}`")
                    if row_id:
                        st.caption(f"id: `{row_id}`")
                with cols[1]:
                    if circ:
                        st.caption(f"📍 {circ}")
                    if candidat:
                        st.caption(f"👤 {candidat}")
                    if parti:
                        st.caption(f"🏛️ {parti}")
                with cols[2]:
                    if excerpt:
                        display = excerpt[:180] + "…" if len(excerpt) > 180 else excerpt
                        st.caption(f"*{display}*")
                st.divider()

    # Latence
    st.caption(f"⏱ {latency_ms} ms")


# ── Initialisation du state de session ───────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state["messages"] = []

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

if "api_ok" not in st.session_state:
    st.session_state["api_ok"] = check_api_health()


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="main-header">
        <h1>🗳️ EDAN 2025 — Chat Électoral</h1>
        <p>Interrogez les résultats des élections législatives ivoiriennes du 27 décembre 2025</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📋 À propos du dataset")
    st.markdown(
        """
        **Élections :** Députés à l'Assemblée Nationale
        **Date :** 27 décembre 2025
        **Source :** CEI — Commission Électorale Indépendante
        **Couverture :** ~255 circonscriptions, toutes régions
        """
    )

    st.divider()

    # Statut API
    if st.session_state["api_ok"]:
        st.success("API opérationnelle", icon="✅")
    else:
        st.error("API indisponible", icon="❌")
        if st.button("🔄 Réessayer la connexion"):
            st.session_state["api_ok"] = check_api_health()
            st.rerun()

    st.divider()

    st.markdown("### 💡 Questions exemples")
    for q in load_example_questions():
        if st.button(q, key=f"ex_{q[:25]}", use_container_width=True):
            st.session_state["pending_question"] = q

    st.divider()

    if st.button("🗑️ Effacer la conversation", use_container_width=True):
        st.session_state["messages"] = []
        st.rerun()

    st.caption("Propulsé par Claude Sonnet · DuckDB · ChromaDB")


# ── Affichage de l'historique ─────────────────────────────────────────────────
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and isinstance(msg.get("content"), dict):
            display_response(msg["content"])
        else:
            st.markdown(str(msg["content"]))


# ── Traitement d'une question ─────────────────────────────────────────────────
def handle_question(question: str) -> None:
    """Traite une question: affiche + appelle l'API + affiche la réponse.

    Args:
        question: Question de l'utilisateur.
    """
    if not question.strip():
        return

    st.session_state["messages"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        if not st.session_state["api_ok"]:
            st.error(
                f"L'API est indisponible ({FASTAPI_URL}). "
                "Lancez `make run-api` puis rechargez la page."
            )
            return

        with st.spinner("Analyse en cours..."):
            try:
                response = send_question(question, st.session_state["session_id"])
                display_response(response)
                st.session_state["messages"].append(
                    {"role": "assistant", "content": response}
                )

            except requests.Timeout:
                msg = "La requête a pris trop de temps. Essayez une question plus simple."
                st.error(msg)
                st.session_state["messages"].append({"role": "assistant", "content": msg})

            except requests.ConnectionError:
                st.session_state["api_ok"] = False
                msg = f"Connexion refusée ({FASTAPI_URL}). Vérifiez que l'API est démarrée."
                st.error(msg)
                st.session_state["messages"].append({"role": "assistant", "content": msg})

            except requests.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.response.json().get("detail", "")
                except Exception:
                    pass
                msg = f"Erreur API {exc.response.status_code}: {detail}"
                st.error(msg)
                st.session_state["messages"].append({"role": "assistant", "content": msg})

            except Exception as exc:
                msg = f"Erreur inattendue: {exc}"
                st.error(msg)
                st.session_state["messages"].append({"role": "assistant", "content": msg})


# Traiter la question en attente depuis la sidebar
pending = st.session_state.pop("pending_question", None)
if pending:
    handle_question(pending)

# Zone de saisie principale
if user_input := st.chat_input("Posez votre question sur les élections ivoiriennes..."):
    handle_question(user_input)
