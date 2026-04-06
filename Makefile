.PHONY: help install ingest run run-streamlit run-api stop stop-local test test-security eval eval-level eval-report eval-baseline regression-check trace-report lint format validate-data clean docker-build docker-up docker-restart docker-reingest docker-down docker-logs

help: ## Afficher l'aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Installer les dépendances et créer .env si absent
	pip install -r requirements.txt
	@if [ ! -f .env ]; then cp .env.example .env && echo "⚠️  .env créé depuis .env.example — ajoutez votre ANTHROPIC_API_KEY"; fi

ingest: ## Extraire le PDF et charger dans DuckDB
	python3 scripts/ingest.py

run: ## Lancer FastAPI (alias de run-api)
	$(MAKE) run-api

run-api: ## Lancer FastAPI (avec rechargement automatique)
	uvicorn src.api.main:app --host 0.0.0.0 --port 8090 --reload

stop: ## Arrêter les conteneurs Docker (alias de docker-down)
	docker-compose down

stop-local: ## Libérer le port 8090 pour le mode run-api local (sans Docker)
	@echo "Libération du port 8090..."
	@lsof -ti :8090 | grep -v "com.docker\|colima\|ssh" | xargs -r kill -9 2>/dev/null || true
	@echo "Port 8090 libéré."

test: ## Lancer tous les tests
	pytest tests/ -v --cov=src --cov-report=term-missing

test-security: ## Lancer les tests de sécurité (adversarial prompts)
	pytest tests/test_adversarial.py -v

eval: ## Lancer la suite d'évaluation offline Level 4 (requiert OPENROUTER_API_KEY)
	PYTHONPATH=. python3 tests/eval/eval_suite.py --verbose

eval-level: ## Évaluer un niveau spécifique (ex: make eval-level LEVEL=1)
	PYTHONPATH=. python3 tests/eval/eval_suite.py --level $(LEVEL) --verbose

eval-report: ## Évaluer et sauvegarder le rapport JSON
	PYTHONPATH=. python3 tests/eval/eval_suite.py --output data/traces/eval_report.json

eval-baseline: ## Sauvegarder le rapport d'évaluation courant comme baseline
	PYTHONPATH=. python3 tests/eval/eval_suite.py --output tests/eval/baseline_report.json
	@echo "Baseline sauvegardé dans tests/eval/baseline_report.json"

regression-check: ## Comparer l'évaluation courante au baseline (requiert make eval-report d'abord)
	PYTHONPATH=. python3 scripts/regression_check.py

trace-report: ## Afficher le rapport des traces (activer avec ENABLE_TRACING=true dans .env)
	PYTHONPATH=. python3 scripts/trace_report.py

lint: ## Vérifier la qualité du code
	ruff check src/ tests/ scripts/
	mypy src/

format: ## Formater le code
	ruff format src/ tests/ scripts/
	ruff check --fix src/ tests/ scripts/

validate-data: ## Valider les données extraites dans DuckDB
	python3 -c "import sys; sys.path.insert(0, '.'); from src.ingestion.validator import validate; validate()"

clean: ## Nettoyer les fichiers générés
	rm -rf data/processed/*.duckdb data/processed/*.csv data/processed/*.parquet
	rm -rf data/processed/chroma/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true

docker-build: ## Builder les images Docker (nécessaire après ajout de dépendances)
	docker-compose build

docker-up: ## Premier démarrage : ingestion + api + app
	docker-compose up -d

docker-restart: ## Redémarrer api + app sans re-ingestion (changements de code)
	docker-compose up -d --no-deps api app

docker-reingest: ## Rebuild complet + suppression DuckDB + ré-ingestion
	docker-compose down
	rm -f data/processed/edan.duckdb
	docker-compose up --build

docker-down: ## Arrêter tous les conteneurs
	docker-compose down

docker-logs: ## Voir les logs Docker en temps réel
	docker-compose logs -f
