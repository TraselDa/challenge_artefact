# EDAN 2025 — Chat with Election Data

> Application de chat pour interroger les résultats des élections des députés à l'Assemblée Nationale de Côte d'Ivoire (scrutin du 27 décembre 2025).

---

## Fonctionnalités

| Niveau | Fonctionnalité | Statut |
|--------|----------------|--------|
| **Level 1** | Text-to-SQL Agent (questions analytiques) | ✅ |
| **Level 1** | Graphiques inline (bar, pie, histogramme) | ✅ |
| **Level 1** | Guardrails SQL (SELECT only, LIMIT, allowlist) | ✅ |
| **Level 2** | RAG hybride (recherche floue, fautes de frappe) | ✅ |
| **Level 2** | Normalisation d'entités (partis, noms, accents) | ✅ |
| **Level 2** | Citations avec source (page, circonscription) | ✅ |
| **Level 3** | Détection d'ambiguïté + clarification | ✅ |
| **Level 4** | Tracing end-to-end par span (latence, tokens) | ✅ |
| **Level 4** | Suite d'évaluation offline 27 cas (100 %) | ✅ |
| **Level 4** | Cache LRU SQL + RAG (sans dépendance externe) | ✅ |
| **Level 4** | Versioning dataset via hash SHA-256 du PDF | ✅ |
| **Level 4** | CI GitHub Actions + regression check | ✅ |

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
make ingest         # Extraire le PDF → DuckDB + empreinte SHA-256 du dataset
make validate-data  # Vérifier l'intégrité des données extraites

# Serveur
make run-api        # Lancer FastAPI sur le port 8090 (rechargement automatique)
make stop-local     # Libérer le port 8090 (tue les processus uvicorn locaux)

# Tests
make test           # Tous les tests unitaires (pytest + couverture)
make test-security  # Tests adversariaux (injections SQL, questions hors-scope)

# Évaluation (Level 4)
make eval                        # Suite complète : 27 cas sur tous les niveaux
make eval-level LEVEL=1          # Un niveau précis (1, 2, 3 ou adversarial)
make eval-report                 # Évaluer et écrire le rapport dans data/traces/eval_report.json
make eval-baseline               # Figer le rapport courant comme référence (tests/eval/baseline_report.json)
make regression-check            # Comparer eval-report vs baseline (sort en erreur si régression > 10 %)

# Observabilité (Level 4)
make trace-report                # Résumé des traces (nécessite ENABLE_TRACING=true dans .env)
make trace-report -- --last 20   # Afficher les 20 dernières requêtes
make trace-report -- --intent sql  # Filtrer par intent

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

## Level 4 — Observabilité & Évaluation

### Tracing end-to-end

Chaque requête est tracée en **spans** : routing → SQL/RAG → génération réponse. Les traces sont écrites en JSONL dans `data/traces/traces.jsonl` et **n'impactent jamais la requête** (pattern fire-and-forget avec try/except).

**Activer le tracing :**

```bash
# Dans .env
ENABLE_TRACING=true
```

**Ce qu'une trace contient :**

```json
{
  "trace_id": "a3f8c1d2",
  "question": "Combien de sièges a gagné le RHDP ?",
  "intent": "sql",
  "total_latency_ms": 1842.3,
  "timestamp": "2026-04-06T14:30:00.123456+00:00",
  "sql": "SELECT nb_sieges FROM vw_results_by_party WHERE parti = 'RHDP' LIMIT 100",
  "tokens": { "input_tokens": 1204, "output_tokens": 87 },
  "spans": [
    { "step": "routing",   "latency_ms": 23.1,   "metadata": { "intent": "sql" } },
    { "step": "sql_agent", "latency_ms": 1564.2, "metadata": { "row_count": 1 } },
    { "step": "chart_gen", "latency_ms": 12.8,   "metadata": {} }
  ]
}
```

**Lire les traces :**

```bash
make trace-report                    # 10 dernières requêtes + stats globales
make trace-report -- --last 50       # 50 dernières
make trace-report -- --intent rag    # Filtrer sur un intent
```

Exemple de sortie :

```
  Statistiques globales (142 requêtes) :
    Latence moyenne : 2 341 ms
    Médiane (p50)   : 1 980 ms
    p95             : 5 102 ms

  Par intent :
    sql                       :   98 req  avg 1 843ms
    rag                       :   31 req  avg 3 217ms
    out_of_scope              :    8 req  avg    12ms
    sql_chart                 :    5 req  avg 2 910ms
```

> Les requêtes `out_of_scope` (injections SQL, questions hors-dataset) ont une latence quasi nulle — elles sont bloquées avant tout appel LLM.

---

### Suite d'évaluation offline

27 cas de test couvrant les 4 niveaux, évalués sur 6 métriques indépendantes :

| Métrique | Ce qui est vérifié |
|----------|--------------------|
| **intent** | Le routeur classe correctement la question |
| **sql** | Le SQL généré contient les tables/colonnes attendues |
| **answer** | La réponse contient les mots-clés attendus |
| **fact** | La valeur numérique exacte est présente (tolérance 1 %) |
| **citation** | La vue SQL utilisée correspond à la source attendue |
| **aggregation** | Le résultat SQL de référence apparaît dans la réponse |

**Score courant : 27/27 (100 %) — tous niveaux confondus.**

```bash
make eval               # Lancer l'évaluation complète
make eval-level LEVEL=adversarial   # Uniquement les tests de sécurité
```

Exemple de sortie :

```
  Score global : 27/27 (100.0%)

  Par niveau :
    Level 1            : 12/12 (100.0%)   ← Text-to-SQL
    Level 2            : 5/5  (100.0%)   ← Fuzzy / RAG
    Level 3            : 2/2  (100.0%)   ← Clarification
    Level adversarial  : 8/8  (100.0%)   ← Sécurité

  Par métrique :
    intent      : 100.0%
    sql         : 100.0%
    fact        : 100.0%
    aggregation : 100.0%
```

---

### Regression check (CI)

Workflow pour ne pas dégrader les performances entre itérations :

```bash
make eval-baseline      # Figer le score actuel comme référence
# … modifier du code …
make eval-report        # Réévaluer → data/traces/eval_report.json
make regression-check   # Comparer : sort en erreur si un niveau perd > 10 %
```

La CI GitHub Actions (`.github/workflows/ci.yml`) lance automatiquement `make lint` + `pytest` sur chaque push. Le regression check s'exécute en local avant de merger.

---

### Cache LRU

Les résultats SQL et les réponses RAG sont mis en cache en mémoire (LRU sans dépendance externe) :

| Cache | Taille max | Clé |
|-------|-----------|-----|
| SQL results | 128 entrées | texte exact de la requête SQL |
| RAG retrieval | 64 entrées | (query normalisée, n_results) |

La même question posée une deuxième fois dans la même session ne génère aucun appel DuckDB ni ChromaDB. Le cache est vidé à chaque redémarrage.

---

### Versioning du dataset

À chaque `make ingest`, un fichier `data/processed/.data_version` est créé :

```json
{
  "pdf_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41...",
  "ingest_timestamp": "2026-04-06T12:00:00",
  "embedding_model": "text-embedding-3-small",
  "schema_version": "1"
}
```

Au démarrage de l'API, le hash du PDF est comparé au hash enregistré dans l'index ChromaDB. Un warning est loggué si les deux divergent (index ChromaDB périmé → relancer `make ingest`).

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
| `ENABLE_TRACING` | Activer le tracing JSONL dans `data/traces/` (`true`/`1`/`yes`) | `false` |
| `TRACES_DIR` | Répertoire d'écriture des traces | `data/traces` |

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
