"""Rapport de traces — lit data/traces/traces.jsonl et affiche les statistiques.

Usage:
    python scripts/trace_report.py
    python scripts/trace_report.py --last 20
    python scripts/trace_report.py --intent sql
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

TRACES_FILE = Path("data/traces/traces.jsonl")

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
CYAN = "\033[96m"


def load_traces(intent_filter: str | None = None) -> list[dict]:
    if not TRACES_FILE.exists():
        return []
    traces = []
    with open(TRACES_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
                if intent_filter is None or t.get("intent") == intent_filter:
                    traces.append(t)
            except json.JSONDecodeError:
                pass
    return traces


def main() -> None:
    parser = argparse.ArgumentParser(description="Rapport de traces EDAN 2025")
    parser.add_argument("--last", type=int, default=10, help="Nombre de dernières requêtes à afficher (défaut: 10)")
    parser.add_argument("--intent", type=str, default=None, help="Filtrer par intent (sql, rag, out_of_scope, ...)")
    args = parser.parse_args()

    if not TRACES_FILE.exists():
        print(f"\n{YELLOW}Aucun fichier de traces trouvé : {TRACES_FILE}{RESET}")
        print(f"Activez le tracing avec {CYAN}ENABLE_TRACING=true{RESET} et relancez l'app.\n")
        sys.exit(0)

    traces = load_traces(intent_filter=args.intent)

    if not traces:
        msg = f"Aucune trace enregistrée"
        if args.intent:
            msg += f" pour intent={args.intent!r}"
        print(f"\n{YELLOW}{msg}.{RESET}\n")
        sys.exit(0)

    total = len(traces)
    latencies = [t["total_latency_ms"] for t in traces]
    avg_latency = sum(latencies) / total
    p50 = sorted(latencies)[total // 2]
    p95 = sorted(latencies)[int(total * 0.95)]

    by_intent: dict[str, list[float]] = defaultdict(list)
    for t in traces:
        by_intent[t.get("intent", "unknown")].append(t["total_latency_ms"])

    errors = [t for t in traces if t.get("error")]

    print(f"\n{BOLD}{'=' * 65}{RESET}")
    print(f"{BOLD}  EDAN 2025 — Rapport de traces{RESET}", end="")
    if args.intent:
        print(f" (intent={args.intent})", end="")
    print(f"\n{BOLD}{'=' * 65}{RESET}\n")

    print(f"  {BOLD}Statistiques globales ({total} requêtes) :{RESET}")
    print(f"    Latence moyenne : {avg_latency:.0f} ms")
    print(f"    Médiane (p50)   : {p50:.0f} ms")
    print(f"    p95             : {p95:.0f} ms")
    if errors:
        print(f"    {RED}Erreurs         : {len(errors)}/{total}{RESET}")

    print(f"\n  {BOLD}Par intent :{RESET}")
    for intent_key, lats in sorted(by_intent.items(), key=lambda x: -len(x[1])):
        avg = sum(lats) / len(lats)
        mn = min(lats)
        mx = max(lats)
        print(
            f"    {intent_key:25s} : {len(lats):4d} req"
            f" | moy={avg:5.0f}ms | min={mn:5.0f}ms | max={mx:5.0f}ms"
        )

    last_n = traces[-args.last:]
    print(f"\n  {BOLD}{args.last} dernières requêtes :{RESET}")
    for t in last_n:
        intent_str = t.get("intent", "?")
        latency = t.get("total_latency_ms", 0)
        question = t.get("question", "")[:55]
        ts = t.get("timestamp", "")[:19].replace("T", " ")
        err_marker = f" {RED}[ERR]{RESET}" if t.get("error") else ""
        print(
            f"    {CYAN}{ts}{RESET} [{intent_str:12s}] "
            f"{latency:5.0f}ms — {question}{err_marker}"
        )

    print(f"\n{BOLD}{'=' * 65}{RESET}\n")
    print(f"  Fichier : {TRACES_FILE}  ({TRACES_FILE.stat().st_size // 1024} KB)\n")


if __name__ == "__main__":
    main()
