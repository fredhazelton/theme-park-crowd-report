"""DuckDB connection management — no WAL corruption.

Rules:
1. All pipeline queries use read-only connections to parquet files.
2. DuckDB write happens ONCE at the end (s11_deploy.py) to load results.
3. Never hold a connection open across steps.
4. Use context managers everywhere.
"""

from __future__ import annotations

import time
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
def write_connection(db_path: Path, retries: int = 5, backoff_sec: float = 30.0):
    """Connection to the live DuckDB file. Used ONLY in s11_deploy.py.
    
    Opens, writes, closes. Never held open across steps.

    Retries with backoff if the database is locked by another process
    (e.g., the live data collector). DuckDB only supports one writer
    at a time — this handles the race gracefully.

    Default: 5 retries × 30s backoff = up to 2.5 minutes of waiting.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"DuckDB file not found: {db_path}")

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            con = duckdb.connect(str(db_path))
            try:
                yield con
            finally:
                con.close()
            return  # success — exit the retry loop
        except duckdb.IOException as e:
            last_error = e
            if attempt < retries:
                wait = backoff_sec * attempt
                print(f"DuckDB locked (attempt {attempt}/{retries}): {e}")
                print(f"  Retrying in {wait:.0f}s...")
                time.sleep(wait)
            else:
                print(f"DuckDB locked after {retries} attempts — giving up")
                raise
        except Exception:
            # Non-lock errors (e.g., corruption) should fail immediately
            raise

    # Should never reach here, but just in case
    raise last_error  # type: ignore
