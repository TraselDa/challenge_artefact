#!/usr/bin/env python3
"""Vérifie les régressions par rapport au baseline d'évaluation.

Usage:
    python scripts/regression_check.py
    python scripts/regression_check.py --baseline tests/eval/baseline_report.json
    python scripts/regression_check.py --current data/traces/eval_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_BASELINE = REPO_ROOT / "tests" / "eval" / "baseline_report.json"
DEFAULT_CURRENT = REPO_ROOT / "data" / "traces" / "eval_report.json"

# Seuil de régression acceptable par niveau : -10%
REGRESSION_THRESHOLD = 10.0

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"


def load_report(path: Path) -> dict:
    if not path.exists():
        print(f"Fichier introuvable: {path}")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Vérification des régressions d'évaluation EDAN 2025")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--current", default=str(DEFAULT_CURRENT))
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    baseline = load_report(Path(args.baseline))
    current = load_report(Path(args.current))

    if not baseline:
        print("Baseline vide ou absent. Lancer 'make eval-baseline' d'abord.")
        sys.exit(0)

    if not current:
        print("Rapport courant absent. Lancer 'make eval-report' d'abord.")
        sys.exit(1)

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  EDAN 2025 — Rapport de régression{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}\n")

    regressions: list[str] = []

    # Score global
    base_global = baseline.get("score_pct", 0)
    curr_global = current.get("score_pct", 0)
    delta = curr_global - base_global
    color = GREEN if delta >= 0 else (YELLOW if delta > -REGRESSION_THRESHOLD else RED)
    print(f"  Score global : {base_global}% → {curr_global}% ({color}{delta:+.1f}%{RESET})")

    # Par niveau
    print(f"\n  {BOLD}Par niveau :{RESET}")
    base_levels = baseline.get("by_level", {})
    curr_levels = current.get("by_level", {})
    all_levels = sorted(set(list(base_levels.keys()) + list(curr_levels.keys())))

    for level in all_levels:
        base_pct = base_levels.get(level, {}).get("score_pct", 0)
        curr_pct = curr_levels.get(level, {}).get("score_pct", 0)
        delta = curr_pct - base_pct
        color = GREEN if delta >= 0 else (YELLOW if delta > -REGRESSION_THRESHOLD else RED)
        print(f"    Level {level:12s} : {base_pct}% → {curr_pct}% ({color}{delta:+.1f}%{RESET})")
        if delta <= -REGRESSION_THRESHOLD:
            regressions.append(f"Level {level}: {base_pct}% → {curr_pct}% ({delta:+.1f}%)")

    # Par métrique (si disponible)
    base_metrics = baseline.get("scores_by_metric", {})
    curr_metrics = current.get("scores_by_metric", {})
    if base_metrics and curr_metrics:
        print(f"\n  {BOLD}Par métrique :{RESET}")
        for metric in sorted(set(list(base_metrics.keys()) + list(curr_metrics.keys()))):
            base_pct = base_metrics.get(metric, 0)
            curr_pct = curr_metrics.get(metric, 0)
            delta = curr_pct - base_pct
            color = GREEN if delta >= 0 else (YELLOW if abs(delta) <= REGRESSION_THRESHOLD else RED)
            print(f"    {metric:15s} : {base_pct}% → {curr_pct}% ({color}{delta:+.1f}%{RESET})")

    print(f"\n{BOLD}{'=' * 60}{RESET}\n")

    if regressions:
        print(f"{RED}{BOLD}RÉGRESSIONS DÉTECTÉES ({len(regressions)}) :{RESET}")
        for r in regressions:
            print(f"  - {r}")
        print()
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}Aucune régression détectée.{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
