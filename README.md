# EDAN 2025 — Chat with Election Data

> Application de chat pour interroger les résultats des élections des députés à l'Assemblée Nationale de Côte d'Ivoire (scrutin du 27 décembre 2025).

---

## Fonctionnalités

| Niveau | Fonctionnalité | Statut |
|--------|----------------|--------|
| **Level 1** | Text-to-SQL Agent (questions analytiques) | Implémenté |
| **Level 1** | Graphiques inline (bar, pie, histogramme) | Implémenté |
| **Level 1** | Guardrails SQL (SELECT only, LIMIT, allowlist) | Implémenté |
| **Level 2** | RAG hybride (recherche floue, fautes de frappe) | Implémenté |
| **Level 2** | Normalisation d'entités (partis, noms, accents) | Implémenté |
| **Level 2** | Citations avec source (page, circonscription) | Implémenté |
| **Level 3** | Détection d'ambiguïté + clarification | Implémenté |
| **Level 4** | Tracing et suite d'évaluation offline | Implémenté |

---

## Prérequis

| Outil | Utilité | Installation |
|-------|---------|-------------|
| **Docker** + **docker-compose** | Lancer l'application en conteneurs (méthode recommandée) | [docs.docker.com](https://docs.docker.com/get-docker/) |
| **make** | Raccourcis pour toutes les commandes | macOS : `xcode-select --install` · Linux : `apt install make` · Windows : via WSL2 |
| **Python 3.11+** | Mode local uniquement (sans Docker) | [python.org](https://www.python.org/) |
| **Clé API OpenRouter** | Accès au LLM (Claude Sonnet via OpenRouter) | [openrouter.ai](https://openrouter.ai/) |

> **Note :** la méthode Docker est la seule garantie de reproductibilité. Les tests ont été réalisés dans cet environnement.

---

## Démarrage rapide (Docker)

```bash
# 1. Copier les variables d'environnement
cp .env.example .env

# 2. Ajouter votre clé API dans .env
#    OPENROUTER_API_KEY=sk-or-xxxxx

# 3. Démarrer (ingestion + API)
make docker-up
```

L'ingestion du PDF se lance automatiquement au démarrage.

**Interface chat (Streamlit) :** `http://localhost:8501`
**API + docs interactive :** `http://localhost:8090/docs`

---

## Commandes Docker

```bash
make docker-build    # Builder les images (première fois ou après ajout de dépendances)
make docker-up       # Démarrer tous les conteneurs (ingestion + API + Streamlit)
make docker-restart  # Redémarrer api + app sans re-ingestion (après un changement de code)
make docker-reingest # Rebuild complet + suppression DuckDB + ré-ingestion
make docker-down     # Arrêter et supprimer les conteneurs
make docker-logs     # Suivre les logs en temps réel
```

**Ordre de démarrage automatique :**
1. `ingestion` — extrait le PDF et charge DuckDB (se termine et s'arrête)
2. `api` — démarre FastAPI sur le port 8090 (attend que l'ingestion soit terminée)
3. `app` — démarre Streamlit sur le port 8501 (attend que l'API soit healthy)

---

## Commandes locales (sans Docker)

> Requièrent Python 3.11+ et les dépendances installées. Les tests unitaires (`make test`) peuvent être lancés localement ; les tests d'intégration et la suite d'évaluation (`make eval`) nécessitent une clé `OPENROUTER_API_KEY` valide et une base DuckDB ingérée.

```bash
make install        # Installer les dépendances (crée .env depuis .env.example si absent)
make ingest         # Extraire le PDF → DuckDB
make validate-data  # Vérifier l'intégrité des données extraites

# Serveur
make run-api        # Lancer FastAPI sur le port 8090 (rechargement automatique)
make stop-local     # Libérer le port 8090 (tue les processus uvicorn locaux)

# Tests
make test           # Tous les tests unitaires (pytest + couverture)
make test-security  # Tests adversariaux (injections SQL, questions hors-scope)

# Évaluation Level 4
make eval                    # Suite d'évaluation complète (tous les niveaux)
make eval-level LEVEL=1      # Évaluer un niveau précis (1, 2, 3 ou adversarial)
make eval-report             # Évaluer et sauvegarder le rapport JSON dans data/traces/

# Observabilité
make trace-report            # Afficher un résumé des traces (activer ENABLE_TRACING=true dans .env)

# Qualité du code
make lint           # Vérifier le style (ruff + mypy)
make format         # Formater le code (ruff)
make clean          # Supprimer les fichiers générés (DuckDB, ChromaDB, cache Python)
```

---

## Tester le chat

Une fois démarré, ouvrir `http://localhost:8090/docs` et utiliser l'endpoint `POST /api/chat` :

```json
{ "message": "Combien de sièges a gagné le RHDP ?" }
```

Exemples de questions :

```
"Combien de sièges a gagné le RHDP ?"
"Quel parti a gagné à Abidjan ?"
"Classement des partis dans la région Poro."
"Top 10 des candidats par score dans la région Agneby-Tiassa."
"Taux de participation par région."
"Histogramme des élus par parti."
"Qui a gagné dans la circonscription 001 ?"
"Quel est le taux de participation national ?"
"Quels sont les partis représentés ?"
"Résultats à Tiapum"  → trouve "Tiapoum" (RAG fuzzy)
"Sièges du R.H.D.P"   → matche "RHDP" (normalisation)
```

---

## Architecture

```
Client (curl / Swagger UI)
    │  POST /api/chat
    ▼
FastAPI (port 8090)
    │
    ▼
IntentRouter
    ├── sql         → Text-to-SQL Agent → DuckDB
    ├── sql_chart   → SQL + Plotly
    ├── rag         → RAG Agent (ChromaDB)
    ├── clarification → demande de précision
    └── out_of_scope  → refus explicatif
```

---

## Variables d'environnement

Copier `.env.example` vers `.env` et remplir :

| Variable | Description | Défaut |
|----------|-------------|--------|
| `OPENROUTER_API_KEY` | Clé API OpenRouter (obligatoire) | — |
| `LLM_MODEL` | Modèle utilisé | `anthropic/claude-sonnet-4-5` |
| `DUCKDB_PATH` | Chemin vers la base DuckDB | `data/processed/edan.duckdb` |
| `CHROMA_PERSIST_DIR` | Répertoire ChromaDB | `data/processed/chroma` |
| `FASTAPI_PORT` | Port FastAPI | `8090` |
| `SQL_TIMEOUT_SECONDS` | Timeout requêtes SQL | `10` |
| `SQL_MAX_LIMIT` | LIMIT maximum autorisé | `1000` |
| `SQL_DEFAULT_LIMIT` | LIMIT ajouté si absent | `100` |
| `ENABLE_TRACING` | Activer le tracing JSONL (`true`/`1`/`yes`) | `false` |

---

## Dataset

| Propriété | Valeur |
|-----------|--------|
| **Source** | Commission Électorale Indépendante (CEI) — Côte d'Ivoire |
| **Contenu** | Résultats des Élections des Députés à l'Assemblée Nationale |
| **Date du scrutin** | 27 décembre 2025 |
| **Format** | PDF, 35 pages, 1 grand tableau avec cellules fusionnées verticalement |
| **Périmètre** | 255 circonscriptions, toutes les régions de Côte d'Ivoire |
| **Totaux nationaux** | 8 597 092 inscrits, 3 012 094 votants, taux de participation : 35,04% |

Schéma complet : [`data/reference/schema.md`](data/reference/schema.md)

---

## Sécurité SQL

1. **SELECT uniquement** — DDL/DML bloqué (INSERT, UPDATE, DELETE, DROP…)
2. **LIMIT obligatoire** — max 1000, défaut 100
3. **Timeout** — 10 secondes max par requête
4. **Allowlist stricte** — uniquement les tables/colonnes documentées dans `schema.md`
5. **Connexion read-only** — DuckDB ouvert en lecture seule

```bash
make test-security   # Vérifier que les injections sont bien bloquées
```

---

## Licence

Projet réalisé dans le cadre d'un challenge technique — AI Engineer.
Dataset : propriété de la Commission Électorale Indépendante (CEI) de Côte d'Ivoire.
