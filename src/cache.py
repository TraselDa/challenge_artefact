"""Cache LRU simple pour résultats SQL et retrieval RAG.

Pas de dépendances externes — OrderedDict comme backing store.
Invalidation explicite via clear_all_caches().
"""

import logging
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

_SQL_CACHE_MAX = 128
_RETRIEVAL_CACHE_MAX = 64

_sql_cache: OrderedDict[str, Any] = OrderedDict()
_retrieval_cache: OrderedDict[str, Any] = OrderedDict()


def _normalize_sql_key(sql: str) -> str:
    """Normalise le SQL pour en faire une clé de cache stable."""
    import re
    return re.sub(r"\s+", " ", sql.strip().lower())


def get_sql_cached(sql: str) -> Any | None:
    """Retourne le résultat SQL mis en cache, ou None si absent."""
    key = _normalize_sql_key(sql)
    if key in _sql_cache:
        _sql_cache.move_to_end(key)
        logger.debug("Cache SQL hit: %s...", sql[:60])
        return _sql_cache[key]
    return None


def set_sql_cached(sql: str, result: Any) -> None:
    """Met en cache un résultat SQL. Évicte le plus ancien si plein."""
    key = _normalize_sql_key(sql)
    if key in _sql_cache:
        _sql_cache.move_to_end(key)
    _sql_cache[key] = result
    if len(_sql_cache) > _SQL_CACHE_MAX:
        _sql_cache.popitem(last=False)


def get_retrieval_cached(query: str, n_results: int) -> Any | None:
    """Retourne les résultats de retrieval mis en cache, ou None si absent."""
    key = f"{query.strip().lower()}:{n_results}"
    if key in _retrieval_cache:
        _retrieval_cache.move_to_end(key)
        logger.debug("Cache retrieval hit: %s...", query[:40])
        return _retrieval_cache[key]
    return None


def set_retrieval_cached(query: str, n_results: int, results: Any) -> None:
    """Met en cache des résultats de retrieval."""
    key = f"{query.strip().lower()}:{n_results}"
    if key in _retrieval_cache:
        _retrieval_cache.move_to_end(key)
    _retrieval_cache[key] = results
    if len(_retrieval_cache) > _RETRIEVAL_CACHE_MAX:
        _retrieval_cache.popitem(last=False)


def clear_all_caches() -> None:
    """Vide tous les caches (à appeler après un re-ingest)."""
    _sql_cache.clear()
    _retrieval_cache.clear()
    logger.info("Caches SQL et retrieval vidés.")


def cache_stats() -> dict[str, int]:
    """Retourne les statistiques des caches."""
    return {
        "sql_entries": len(_sql_cache),
        "sql_max": _SQL_CACHE_MAX,
        "retrieval_entries": len(_retrieval_cache),
        "retrieval_max": _RETRIEVAL_CACHE_MAX,
    }
