"""DuckDB connection management — no WAL corruption.

Rules:
1. All pipeline queries use read-only connections to parquet files.
2. DuckDB write happens ONCE at the end (s11_deploy.py) to load results.
3. Never hold a connection open across steps.
4. Use context managers everywhere.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import duckdb


@contextmanager
def read_connection():
    """Ephemeral in-memory DuckDB connection for reading parquet files.
    
    This is the workhorse. Every step uses this for queries.
    No WAL, no locking, no corruption risk.
    """
    con = duckdb.connect()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def write_connection(db_path: Path):
    """Connection to the live DuckDB file. Used ONLY in s11_deploy.py.
    
    Opens, writes, closes. Never held open across steps.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"DuckDB file not found: {db_path}")
    con = duckdb.connect(str(db_path))
    try:
        yield con
    finally:
        con.close()
