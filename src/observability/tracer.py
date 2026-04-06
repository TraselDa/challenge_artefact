"""Tracing léger end-to-end — fire-and-forget, jamais de crash.

Usage:
    Activé uniquement si ENABLE_TRACING=true (ou 1/yes).
    Les traces sont écrites en JSONL dans data/traces/traces.jsonl.

    Dans le code production:
        try:
            from src.observability.tracer import new_tracer
            _t = new_tracer(trace_id, question, session_id=...)
            _t.flush(intent="sql", total_latency_ms=142, sql="SELECT ...")
        except Exception:
            pass  # Ne bloque jamais la requête
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("ENABLE_TRACING", "").lower() in ("1", "true", "yes")
_TRACES_DIR: Path = Path(os.getenv("TRACES_DIR", "data/traces"))
_TRACES_FILE: Path = _TRACES_DIR / "traces.jsonl"


@dataclass
class TraceSpan:
    """Un span = une étape mesurée dans le pipeline."""

    step: str
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    """Trace complète d'une requête."""

    trace_id: str
    question: str
    intent: str
    total_latency_ms: float
    timestamp: str
    spans: list[TraceSpan] = field(default_factory=list)
    sql: str | None = None
    error: str | None = None
    session_id: str | None = None
    tokens: dict[str, int] | None = None


class Tracer:
    """Collecteur de traces. No-op si ENABLE_TRACING n'est pas défini."""

    def __init__(
        self,
        trace_id: str,
        question: str,
        session_id: str | None = None,
    ) -> None:
        self._trace_id = trace_id
        self._question = question
        self._session_id = session_id
        self._spans: list[TraceSpan] = []

    def record(self, step: str, latency_ms: float, **metadata: Any) -> None:
        """Enregistre un span. Ne lève jamais d'exception."""
        if not _ENABLED:
            return
        try:
            self._spans.append(
                TraceSpan(
                    step=step,
                    latency_ms=round(latency_ms, 1),
                    metadata=dict(metadata),
                )
            )
        except Exception:
            pass

    def flush(
        self,
        intent: str,
        total_latency_ms: float,
        sql: str | None = None,
        error: str | None = None,
        tokens: dict[str, int] | None = None,
    ) -> None:
        """Écrit la trace en JSONL. Ne lève jamais d'exception."""
        if not _ENABLED:
            return
        try:
            trace = Trace(
                trace_id=self._trace_id,
                question=self._question,
                intent=intent,
                total_latency_ms=round(total_latency_ms, 1),
                timestamp=datetime.now(UTC).isoformat(),
                spans=self._spans,
                sql=sql,
                error=error,
                session_id=self._session_id,
                tokens=tokens,
            )
            _TRACES_DIR.mkdir(parents=True, exist_ok=True)
            with open(_TRACES_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(trace), ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug("Trace flush ignorée (non-critique): %s", exc)


def new_tracer(
    trace_id: str,
    question: str,
    session_id: str | None = None,
) -> Tracer:
    """Crée un Tracer. Toujours sûr à appeler, même si le tracing est désactivé."""
    return Tracer(trace_id=trace_id, question=question, session_id=session_id)
