"""Canonical park code mappings — the ONE source of truth.

Import from here. Never roll your own. The USH→UH bug of 2026-03-07
happened because entity_wti_diagnostics.py had its own version.

This is a copy of src/utils/park_code.py, kept in pipeline_v3 to avoid
cross-package imports. If the canonical mapping changes, update BOTH.
"""

from __future__ import annotations

import re

# Entity prefix → canonical park code (uppercase)
_PREFIX_TO_PARK: dict[str, str] = {
    "USH": "UH",
    "TDL": "TDL",
    "TDS": "TDS",
}

# Park code → IANA timezone
PARK_TIMEZONE: dict[str, str] = {
    "TDL": "Asia/Tokyo",
    "TDS": "Asia/Tokyo",
    "MK": "America/New_York",
    "EP": "America/New_York",
    "HS": "America/New_York",
    "AK": "America/New_York",
    "DL": "America/Los_Angeles",
    "CA": "America/Los_Angeles",
    "IA": "America/New_York",
    "UF": "America/New_York",
    "EU": "America/New_York",
    "UH": "America/Los_Angeles",
}

# Park code → display name
PARK_NAMES: dict[str, str] = {
    "MK": "Magic Kingdom",
    "EP": "EPCOT",
    "HS": "Hollywood Studios",
    "AK": "Animal Kingdom",
    "DL": "Disneyland",
    "CA": "California Adventure",
    "UF": "Universal Studios Florida",
    "IA": "Islands of Adventure",
    "EU": "Epic Universe",
    "UH": "Universal Hollywood",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
}


def entity_to_park(entity_code: str) -> str:
    """Derive canonical park code from entity_code.

    USH01 → UH, TDL05 → TDL, MK01 → MK, EU12 → EU.
    """
    if not entity_code:
        return ""
    s = str(entity_code).upper().strip()
    m = re.search(r"\d", s)
    prefix = s[: m.start()] if m else s
    return _PREFIX_TO_PARK.get(prefix, prefix[:2] if len(prefix) >= 2 else prefix)


def park_code_sql(col: str = "entity_code") -> str:
    """DuckDB SQL CASE expression for entity_code → park_code."""
    return f"""CASE
        WHEN {col} LIKE 'USH%' THEN 'UH'
        WHEN {col} LIKE 'TDL%' THEN 'TDL'
        WHEN {col} LIKE 'TDS%' THEN 'TDS'
        ELSE UPPER(LEFT({col}, 2))
    END"""
