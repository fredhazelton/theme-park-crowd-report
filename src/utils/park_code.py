"""
Canonical entity_code → park_code mapping.

Use this everywhere we derive park_code from entity_code. Avoids TD/US mismatches
for TDL/TDS/USH entities (which would incorrectly map to TD, TD, US).
"""

from __future__ import annotations

import re

# Entity prefix → canonical park code (uppercase)
# USH* → UH (Universal Studios Hollywood)
# TDL* → TDL (Tokyo Disneyland)
# TDS* → TDS (Tokyo DisneySea)
# All others: first 2 alpha chars (MK, EP, HS, AK, DL, CA, IA, UF, EU, etc.)
_PREFIX_TO_PARK: dict[str, str] = {
    "USH": "UH",
    "TDL": "TDL",
    "TDS": "TDS",
}


def entity_code_to_park_code(entity_code: str) -> str:
    """
    Derive canonical park code from entity_code.

    Handles 3-char prefixes: USH→UH, TDL→TDL, TDS→TDS.
    Everything else uses first 2 alpha chars (MK, EP, HS, etc.).

    Returns uppercase park code (e.g. "MK", "TDL", "UH").
    """
    if not entity_code:
        return ""
    s = str(entity_code).upper().strip()
    m = re.search(r"\d", s)
    prefix = s[: m.start()] if m else s
    return _PREFIX_TO_PARK.get(prefix, prefix[:2] if len(prefix) >= 2 else prefix)


def park_code_sql(col: str = "entity_code") -> str:
    """
    Return DuckDB/SQL CASE expression that maps entity_code to canonical park_code.

    Use in raw SQL when deriving park_code from entity_code column.
    """
    return f"""CASE
        WHEN {col} LIKE 'USH%' THEN 'UH'
        WHEN {col} LIKE 'TDL%' THEN 'TDL'
        WHEN {col} LIKE 'TDS%' THEN 'TDS'
        ELSE UPPER(LEFT({col}, 2))
    END"""
