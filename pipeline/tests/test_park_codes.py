"""Tests for park code mappings.

The USH→UH bug of 2026-03-07 happened because someone rolled their own.
These tests ensure the canonical mapping stays correct.
"""

from pipeline_v3.core.park_codes import entity_to_park, park_code_sql


def test_standard_parks():
    assert entity_to_park("MK01") == "MK"
    assert entity_to_park("EP42") == "EP"
    assert entity_to_park("HS17") == "HS"
    assert entity_to_park("AK03") == "AK"
    assert entity_to_park("DL55") == "DL"
    assert entity_to_park("CA12") == "CA"
    assert entity_to_park("UF08") == "UF"
    assert entity_to_park("IA22") == "IA"
    assert entity_to_park("EU05") == "EU"


def test_ush_to_uh():
    """The bug that started it all. USH entities must map to UH."""
    assert entity_to_park("USH01") == "UH"
    assert entity_to_park("USH99") == "UH"
    assert entity_to_park("UH01") == "UH"  # Both prefixes work


def test_tokyo_parks():
    """Tokyo parks use 3-char codes."""
    assert entity_to_park("TDL05") == "TDL"
    assert entity_to_park("TDS12") == "TDS"


def test_empty_and_edge_cases():
    assert entity_to_park("") == ""
    assert entity_to_park("X") == "X"
    assert entity_to_park("MK") == "MK"  # No digits


def test_park_code_sql_returns_string():
    """SQL expression should be a non-empty string."""
    sql = park_code_sql("entity_code")
    assert isinstance(sql, str)
    assert "CASE" in sql
    assert "USH" in sql
    assert "TDL" in sql
    assert "TDS" in sql
