"""Guardrails SQL: validation et sécurisation des requêtes générées."""

import logging
import re

import sqlparse

logger = logging.getLogger(__name__)

ALLOWED_TABLES: frozenset[str] = frozenset({
    "results",
    "summary_national",
    "vw_winners",
    "vw_turnout",
    "vw_results_by_region",
    "vw_results_by_party",
    "vw_results_by_circonscription",
    "vw_party_scores_by_region",
    "vw_candidates_ranked_by_circonscription",
})

FORBIDDEN_KEYWORDS: frozenset[str] = frozenset({
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "exec",
    "execute",
    "grant",
    "revoke",
    "information_schema",
    "sqlite_master",
    "sqlite_sequence",
    "pg_",
    "xp_cmdshell",
    "sp_",
    "sys.",
    "pragma",
})

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


class SQLGuardError(Exception):
    """Erreur de validation SQL — requête refusée par les guardrails."""


def validate_sql(sql: str) -> str:
    """Valide et normalise une requête SQL.

    Pipeline de validation:
    1. Vérification SELECT uniquement
    2. Vérification des mots-clés dangereux
    3. Vérification de l'allowlist tables
    4. Ajustement du LIMIT

    Args:
        sql: Requête SQL générée par le LLM.

    Returns:
        SQL validé et normalisé (avec LIMIT garanti).

    Raises:
        SQLGuardError: Si la requête est invalide ou dangereuse.
    """
    if not sql or not sql.strip():
        raise SQLGuardError("Requête SQL vide.")

    # Nettoyer: supprimer les point-virgules finaux et les commentaires
    sql = _remove_comments(sql.strip().rstrip(";").strip())

    # Rejeter les requêtes avec des semicolons (risque d'injection multi-statement)
    if ";" in sql:
        raise SQLGuardError(
            "Les requêtes contenant des points-virgules sont interdites "
            "(risque d'injection multi-statement)."
        )

    _check_tautological_injection(sql)
    _check_select_only(sql)
    _check_forbidden_keywords(sql)
    _check_tables_allowlist(sql)

    sql = _ensure_limit(sql, DEFAULT_LIMIT, MAX_LIMIT)

    logger.debug(f"SQL validé: {sql}")
    return sql


def _remove_comments(sql: str) -> str:
    """Supprime les commentaires SQL (-- et /* */)."""
    # Commentaires en ligne
    sql = re.sub(r"--[^\n]*", "", sql)
    # Commentaires multi-lignes
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql.strip()


def _check_select_only(sql: str) -> None:
    """Vérifie que la requête commence par SELECT (ou WITH pour les CTEs).

    Args:
        sql: Requête SQL nettoyée.

    Raises:
        SQLGuardError: Si la requête n'est pas un SELECT.
    """
    # Parser le SQL
    statements = sqlparse.parse(sql)
    if not statements:
        raise SQLGuardError("Impossible de parser la requête SQL.")

    stmt = statements[0]
    stmt_type = stmt.get_type()

    # Autoriser SELECT et WITH (CTEs)
    if stmt_type not in ("SELECT", "UNKNOWN"):
        raise SQLGuardError(
            f"Seules les requêtes SELECT sont autorisées. Type détecté: {stmt_type}"
        )

    # Vérification supplémentaire: le premier token significatif doit être SELECT ou WITH
    first_token = sql.strip().upper().split()[0] if sql.strip() else ""
    if first_token not in ("SELECT", "WITH"):
        raise SQLGuardError(
            f"La requête doit commencer par SELECT ou WITH. Trouvé: '{first_token}'"
        )


def _check_forbidden_keywords(sql: str) -> None:
    """Vérifie l'absence de mots-clés dangereux (case-insensitive).

    Args:
        sql: Requête SQL.

    Raises:
        SQLGuardError: Si un mot-clé dangereux est détecté.
    """
    sql_lower = sql.lower()

    for keyword in FORBIDDEN_KEYWORDS:
        # Utiliser des word boundaries pour éviter les faux positifs
        # Ex: "execution" ne doit pas déclencher "exec"
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, sql_lower):
            raise SQLGuardError(
                f"Mot-clé interdit détecté: '{keyword}'. "
                "Seules les requêtes SELECT de lecture sont autorisées."
            )


def _check_tables_allowlist(sql: str) -> None:
    """Vérifie que seules les tables autorisées sont référencées.

    Args:
        sql: Requête SQL.

    Raises:
        SQLGuardError: Si une table non autorisée est référencée.
    """
    # Extraire les noms de tables avec une regex (FROM et JOIN)
    table_pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        re.IGNORECASE,
    )
    found_tables = set(table_pattern.findall(sql))

    for table in found_tables:
        if table.lower() not in {t.lower() for t in ALLOWED_TABLES}:
            raise SQLGuardError(
                f"Table non autorisée: '{table}'. "
                f"Tables autorisées: {', '.join(sorted(ALLOWED_TABLES))}"
            )


def _check_tautological_injection(sql: str) -> None:
    """Détecte les injections tautologiques classiques (OR '1'='1', OR 1=1, etc.).

    Args:
        sql: Requête SQL.

    Raises:
        SQLGuardError: Si une tautologie d'injection est détectée.
    """
    sql_lower = sql.lower()
    tautology_patterns = [
        r"or\s+'[^']*'\s*=\s*'[^']*'",   # OR 'x'='x'
        r"or\s+\d+\s*=\s*\d+",            # OR 1=1
        r"or\s+true\b",                    # OR true
        r"or\s+1\s*--",                    # OR 1 --
        r"'\s*or\s*'",                     # ' or '
    ]
    for pattern in tautology_patterns:
        if re.search(pattern, sql_lower):
            raise SQLGuardError(
                "Pattern d'injection SQL tautologique détecté. Requête refusée."
            )


def _ensure_limit(sql: str, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT) -> str:
    """Ajoute ou ajuste le LIMIT dans la requête SQL.

    - Si pas de LIMIT: ajoute LIMIT {default_limit}
    - Si LIMIT > max_limit: remplace par LIMIT {max_limit}
    - Si LIMIT <= max_limit: conserve tel quel

    Args:
        sql: Requête SQL.
        default_limit: LIMIT par défaut si absent.
        max_limit: LIMIT maximum autorisé.

    Returns:
        SQL avec LIMIT correct.
    """
    limit_pattern = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)
    match = limit_pattern.search(sql)

    if not match:
        # Pas de LIMIT: ajouter
        return f"{sql} LIMIT {default_limit}"

    current_limit = int(match.group(1))
    if current_limit > max_limit:
        # Dépasse le max: remplacer
        return limit_pattern.sub(f"LIMIT {max_limit}", sql)

    # LIMIT valide: conserver
    return sql
