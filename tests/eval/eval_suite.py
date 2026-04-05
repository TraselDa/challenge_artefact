"""Suite d'évaluation offline — Level 4.

Ce script charge test_cases.json et évalue les agents sur l'ensemble
des questions de test, en produisant un rapport de réussite détaillé.

Usage :
    # Évaluation complète
    python tests/eval/eval_suite.py

    # Seulement les Level 1
    python tests/eval/eval_suite.py --level 1

    # Seulement les adversarial
    python tests/eval/eval_suite.py --level adversarial

    # Sauvegarder le rapport
    python tests/eval/eval_suite.py --output eval_report.json
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
TEST_CASES_PATH = Path(__file__).parent / "test_cases.json"

# Permet d'exécuter le script directement (python tests/eval/eval_suite.py)
# sans avoir à setter PYTHONPATH manuellement.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DUCKDB_PATH = REPO_ROOT / "data" / "processed" / "edan.duckdb"
CHROMA_DIR = REPO_ROOT / "data" / "processed" / "chroma"


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    """Résultat de l'évaluation d'un cas de test."""

    id: str
    level: Any
    category: str
    question: str
    passed: bool
    intent_ok: bool
    sql_ok: bool
    answer_ok: bool
    latency_ms: float
    actual_intent: str | None = None
    actual_sql: str | None = None
    actual_response: str | None = None
    error: str | None = None
    details: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """Rapport global d'évaluation."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    score_pct: float = 0.0
    by_level: dict[str, dict] = field(default_factory=dict)
    by_category: dict[str, dict] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# Chargement des cas de test
# ---------------------------------------------------------------------------


def load_test_cases(level_filter: str | None = None) -> list[dict]:
    """Charge et filtre les cas depuis test_cases.json."""
    with open(TEST_CASES_PATH, encoding="utf-8") as f:
        cases = json.load(f)

    if level_filter is not None:
        # Convertir le filtre : "1" → 1 (int) pour les niveaux numériques
        try:
            level_int = int(level_filter)
            cases = [c for c in cases if c["level"] == level_int]
        except ValueError:
            cases = [c for c in cases if str(c["level"]) == level_filter]

    return cases


# ---------------------------------------------------------------------------
# Évaluation d'un cas de test
# ---------------------------------------------------------------------------


def evaluate_case(case: dict, pipeline) -> EvalResult:
    """Évalue un seul cas de test contre le pipeline complet."""
    start = time.perf_counter()

    result = EvalResult(
        id=case["id"],
        level=case["level"],
        category=case.get("category", "unknown"),
        question=case["question"],
        passed=False,
        intent_ok=False,
        sql_ok=False,
        answer_ok=False,
        latency_ms=0.0,
    )

    try:
        # Appel au pipeline
        response = pipeline.run(case["question"])
        elapsed_ms = (time.perf_counter() - start) * 1000
        result.latency_ms = round(elapsed_ms, 1)

        result.actual_intent = getattr(response, "intent", None)
        result.actual_sql = getattr(response, "sql", None)
        result.actual_response = getattr(response, "response", str(response))

        # --- Évaluation de l'intent ---
        expected_intent = case.get("expected_intent")
        if expected_intent:
            result.intent_ok = (
                result.actual_intent == expected_intent
                or (
                    # Tolérance : sql_chart est accepté quand sql est attendu
                    expected_intent == "sql"
                    and result.actual_intent in ("sql", "sql_chart")
                )
            )
            if not result.intent_ok:
                result.details.append(
                    f"Intent: attendu={expected_intent!r}, obtenu={result.actual_intent!r}"
                )
        else:
            result.intent_ok = True  # Pas de contrainte d'intent

        # --- Évaluation du SQL généré ---
        sql_contains = case.get("expected_sql_contains", [])
        if sql_contains and result.actual_sql:
            sql_upper = result.actual_sql.upper()
            missing = [kw for kw in sql_contains if kw.upper() not in sql_upper]
            result.sql_ok = not missing
            if missing:
                result.details.append(f"SQL manquant : {missing}")
        else:
            result.sql_ok = True  # Pas de contrainte SQL

        # --- Évaluation de la réponse ---
        answer_contains = case.get("expected_answer_contains", [])
        if answer_contains and result.actual_response:
            response_upper = result.actual_response.upper()
            missing = [kw for kw in answer_contains if kw.upper() not in response_upper]
            result.answer_ok = not missing
            if missing:
                result.details.append(f"Réponse manquante : {missing}")
        else:
            result.answer_ok = True  # Pas de contrainte de réponse

        result.passed = result.intent_ok and result.sql_ok and result.answer_ok

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        result.latency_ms = round(elapsed_ms, 1)
        result.error = str(exc)
        result.passed = False
        result.details.append(f"Exception: {exc}")
        logger.error(f"[{case['id']}] Erreur : {exc}")

    return result


# ---------------------------------------------------------------------------
# Agrégation du rapport
# ---------------------------------------------------------------------------


def aggregate_report(results: list[EvalResult], duration_s: float) -> EvalReport:
    """Construit le rapport global depuis les résultats individuels."""
    report = EvalReport(
        total=len(results),
        passed=sum(1 for r in results if r.passed),
        failed=sum(1 for r in results if not r.passed and r.error is None),
        skipped=sum(1 for r in results if r.error is not None),
        results=results,
        duration_s=round(duration_s, 2),
    )
    report.score_pct = round(report.passed / report.total * 100, 1) if report.total else 0.0

    # Agrégation par niveau
    for result in results:
        level_key = str(result.level)
        if level_key not in report.by_level:
            report.by_level[level_key] = {"total": 0, "passed": 0, "score_pct": 0.0}
        report.by_level[level_key]["total"] += 1
        if result.passed:
            report.by_level[level_key]["passed"] += 1

    for level_key, stats in report.by_level.items():
        stats["score_pct"] = round(
            stats["passed"] / stats["total"] * 100, 1
        ) if stats["total"] else 0.0

    # Agrégation par catégorie
    for result in results:
        cat = result.category
        if cat not in report.by_category:
            report.by_category[cat] = {"total": 0, "passed": 0}
        report.by_category[cat]["total"] += 1
        if result.passed:
            report.by_category[cat]["passed"] += 1

    return report


# ---------------------------------------------------------------------------
# Affichage du rapport
# ---------------------------------------------------------------------------

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
CYAN = "\033[96m"


def print_report(report: EvalReport) -> None:
    """Affiche le rapport en console avec couleurs."""
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}  EDAN 2025 — Rapport d'évaluation{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}\n")

    # Score global
    color = GREEN if report.score_pct >= 80 else (YELLOW if report.score_pct >= 50 else RED)
    print(
        f"  {BOLD}Score global :{RESET} "
        f"{color}{report.passed}/{report.total} ({report.score_pct}%){RESET}"
    )
    print(f"  Durée totale : {report.duration_s}s\n")

    # Par niveau
    print(f"  {BOLD}Par niveau :{RESET}")
    for level, stats in sorted(report.by_level.items()):
        pct = stats["score_pct"]
        color = GREEN if pct >= 80 else (YELLOW if pct >= 50 else RED)
        print(
            f"    Level {level:12s} : "
            f"{color}{stats['passed']}/{stats['total']} ({pct}%){RESET}"
        )

    # Par catégorie
    print(f"\n  {BOLD}Par catégorie :{RESET}")
    for cat, stats in sorted(report.by_category.items()):
        pct = round(stats["passed"] / stats["total"] * 100, 1) if stats["total"] else 0
        color = GREEN if pct >= 80 else (YELLOW if pct >= 50 else RED)
        print(
            f"    {cat:30s} : "
            f"{color}{stats['passed']}/{stats['total']} ({pct}%){RESET}"
        )

    # Détails des cas échoués
    failed = [r for r in report.results if not r.passed]
    if failed:
        print(f"\n  {BOLD}{RED}Cas échoués ({len(failed)}) :{RESET}")
        for r in failed:
            status = f"{RED}ECHEC{RESET}" if not r.error else f"{YELLOW}ERREUR{RESET}"
            print(f"\n  [{r.id}] {status} — {r.question[:60]}")
            print(f"    Latence : {r.latency_ms}ms")
            if r.actual_intent:
                print(f"    Intent  : {r.actual_intent}")
            if r.error:
                print(f"    Erreur  : {r.error}")
            for detail in r.details:
                print(f"    Detail  : {detail}")
    else:
        print(f"\n  {GREEN}{BOLD}Tous les tests sont passés !{RESET}")

    print(f"\n{BOLD}{'=' * 70}{RESET}\n")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suite d'évaluation offline EDAN 2025"
    )
    parser.add_argument(
        "--level",
        type=str,
        default=None,
        help="Filtrer par niveau (1, 2, 3, adversarial). Défaut : tous.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Chemin pour sauvegarder le rapport JSON (optionnel).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Afficher le détail de chaque cas.",
    )
    args = parser.parse_args()

    # Vérification des prérequis
    if not os.getenv("OPENROUTER_API_KEY"):
        logger.error(
            "OPENROUTER_API_KEY non défini. Exporter la variable et relancer."
        )
        sys.exit(1)

    if not DUCKDB_PATH.exists():
        logger.error(
            f"Base DuckDB introuvable : {DUCKDB_PATH}\n"
            "Lancer 'make ingest' pour initialiser la base de données."
        )
        sys.exit(1)

    # Chargement des cas de test
    cases = load_test_cases(level_filter=args.level)
    if not cases:
        logger.warning(f"Aucun cas de test trouvé pour le filtre level={args.level!r}")
        sys.exit(0)

    logger.info(f"Évaluation de {len(cases)} cas de test...")

    # Import tardif — nécessite DB + API key
    from src.observability.pipeline import Pipeline

    pipeline = Pipeline(db_path=str(DUCKDB_PATH), chroma_dir=str(CHROMA_DIR))

    # Évaluation
    eval_results: list[EvalResult] = []
    start_total = time.perf_counter()

    for i, case in enumerate(cases, 1):
        logger.info(f"[{i}/{len(cases)}] {case['id']} — {case['question'][:50]}...")
        result = evaluate_case(case, pipeline)
        eval_results.append(result)

        status = "PASS" if result.passed else "FAIL"
        color = GREEN if result.passed else RED
        if args.verbose:
            print(
                f"  {color}[{status}]{RESET} {case['id']:10s} "
                f"{result.latency_ms:6.0f}ms — {case['question'][:50]}"
            )
            for detail in result.details:
                print(f"           {detail}")

    duration_s = time.perf_counter() - start_total

    # Rapport
    report = aggregate_report(eval_results, duration_s)
    print_report(report)

    # Sauvegarde JSON optionnelle
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            # Convertir les dataclasses en dict pour la sérialisation
            report_dict = asdict(report)
            json.dump(report_dict, f, ensure_ascii=False, indent=2)
        logger.info(f"Rapport sauvegardé : {output_path}")

    # Exit code
    sys.exit(0 if report.score_pct >= 80 else 1)


if __name__ == "__main__":
    main()
