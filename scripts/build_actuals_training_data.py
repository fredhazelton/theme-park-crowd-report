#!/usr/bin/env python3
"""
Build Actuals-Only Training Data (ACTUALS-FIRST methodology)

Creates training rows for forecast models that predict actual wait time from
temporal features ONLY — no posted_time. POSTED is used only for conversion
(synthetic actuals); forecasting deals in actuals.

Data sources:
- Synthetic actuals (90M+ rows) — weight 1.0
- Real ACTUAL observations (2.5M rows) — weight 3.5×

Output: matched_pairs/actuals_training_v2.parquet
Schema: entity_code, park_date, observed_at, observed_at_ts, actual_time,
        mins_since_6am, mins_since_open, hour_of_day,
        date_group_id, season, season_year,
        date_group_id_encoded, season_encoded, season_year_encoded,
        is_synthetic
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

# Ensure src is on path
if str(Path(__file__).parent.parent / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from utils.park_code import park_code_sql, entity_code_to_park_code

DEFAULT_OUTPUT_BASE = Path("/home/wilma/hazeydata/pipeline")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(__name__)


def build_actuals_training_data(logger, output_base: Path) -> int:
    """Build actuals-only training data (synthetic + real, no posted_time)."""
    synth_dir = output_base / "synthetic_actuals"
    parquet_dir = output_base / "fact_tables" / "parquet"
    dim_dir = output_base / "dimension_tables"
    state_dir = output_base / "state"
    output_dir = output_base / "matched_pairs"
    oc_path = output_base / "operating_calendar" / "operating_calendar.parquet"

    logger.info("=" * 60)
    logger.info("BUILDING ACTUALS-ONLY TRAINING DATA (ACTUALS-FIRST)")
    logger.info("=" * 60)

    start_time = time.time()

    # Check required paths
    if not synth_dir.exists():
        logger.error(f"Synthetic actuals directory not found: {synth_dir}")
        return 0

    dategroupid_path = dim_dir / "dimdategroupid.csv"
    season_path = dim_dir / "dimseason.csv"
    parkhours_path = dim_dir / "dimparkhours.csv"
    entity_path = dim_dir / "dimentity.csv"

    for p in [dategroupid_path, season_path]:
        if not p.exists():
            logger.error(f"Required dimension table not found: {p}")
            return 0

    encodings_path = state_dir / "encoding_mappings.json"
    if not encodings_path.exists():
        logger.error(f"Encoding mappings not found: {encodings_path} (run hybrid_pipeline step 1 first)")
        return 0

    with open(encodings_path) as f:
        encodings = json.load(f)
    dg_mapping = encodings["date_group_id"]
    season_mapping = encodings["season"]
    sy_mapping = encodings["season_year"]

    use_operating_calendar = oc_path.exists()
    if use_operating_calendar:
        logger.info(f"Using operating calendar: {oc_path}")
    else:
        logger.info("Operating calendar not found; assuming all operating")

    con = duckdb.connect()

    synth_pattern = str(synth_dir / "*.parquet").replace("\\", "/")
    parquet_str = str(parquet_dir).replace("\\", "/")
    dg_path = str(dategroupid_path).replace("\\", "/")
    season_path_str = str(season_path).replace("\\", "/")
    ph_path = str(parkhours_path).replace("\\", "/")
    entity_path_str = str(entity_path).replace("\\", "/")

    if use_operating_calendar:
        oc_str = str(oc_path).replace("\\", "/")
        operating_filter = f"""
        operating AS (
            SELECT entity_code, CAST(park_date AS DATE) as park_date
            FROM read_parquet('{oc_str}')
            WHERE is_operating = TRUE
        ),
        """
        actual_filter = "AND EXISTS (SELECT 1 FROM operating o WHERE o.entity_code = a.entity_code AND o.park_date = CAST(a.park_date AS DATE))"
        synth_filter = "AND EXISTS (SELECT 1 FROM operating o WHERE o.entity_code = s.entity_code AND o.park_date = s.park_date)"
    else:
        operating_filter = ""
        actual_filter = ""
        synth_filter = ""

    # Park hours join using canonical park_code
    if parkhours_path.exists():
        parkhours_cte = f"""
        parkhours AS (
            SELECT park, CAST(date AS DATE) as park_date,
                   EXTRACT(HOUR FROM CAST(opening_time AS TIMESTAMP)) as open_hour,
                   EXTRACT(MINUTE FROM CAST(opening_time AS TIMESTAMP)) as open_minute
            FROM read_csv('{ph_path}', AUTO_DETECT=TRUE)
            WHERE opening_time IS NOT NULL
        ),
        """
        parkhours_join_synth = f"""
        LEFT JOIN parkhours ph ON ({park_code_sql("s.entity_code")}) = UPPER(ph.park) AND s.park_date = ph.park_date
        """
        parkhours_join_actual = f"""
        LEFT JOIN parkhours ph ON ({park_code_sql("a.entity_code")}) = UPPER(ph.park) AND a.park_date = ph.park_date
        """
        mins_since_open_synth = """
        CASE WHEN ph.open_hour IS NOT NULL THEN
            (EXTRACT(HOUR FROM CAST(s.observed_at AS TIMESTAMP)) - ph.open_hour) * 60 +
            (EXTRACT(MINUTE FROM CAST(s.observed_at AS TIMESTAMP)) - ph.open_minute)
        ELSE NULL END
        """
        mins_since_open_actual = """
        CASE WHEN ph.open_hour IS NOT NULL THEN
            (EXTRACT(HOUR FROM a.observed_at_ts) - ph.open_hour) * 60 +
            (EXTRACT(MINUTE FROM a.observed_at_ts) - ph.open_minute)
        ELSE NULL END
        """
    else:
        parkhours_cte = ""
        parkhours_join_synth = ""
        parkhours_join_actual = ""
        mins_since_open_synth = "NULL"
        mins_since_open_actual = "NULL"

    # Valid entities (standby only)
    valid_entities = f"""
    valid_entities AS (
        SELECT code as entity_code FROM read_csv_auto('{entity_path_str}')
        WHERE fastpass_booth = FALSE
    ),
    """

    # OOM-safe: chunk by park (per data-access-pattern: >30M rows)
    synth_files = list(synth_dir.glob("*.parquet"))
    entities = [f.stem for f in synth_files if f.stem and not f.stem.startswith(".")]
    park_to_entities = {}
    for e in entities:
        park = entity_code_to_park_code(e)
        park_to_entities.setdefault(park, []).append(e)
    parks = sorted(park_to_entities.keys())
    logger.info(f"Chunking by park: {len(parks)} parks, {len(entities)} entities")

    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir = output_dir / "_actuals_chunks"
    chunk_dir.mkdir(exist_ok=True)

    total_rows = 0
    total_synthetic = 0
    total_real = 0
    for park_idx, park_code in enumerate(parks, 1):
        chunk_entities = park_to_entities[park_code]
        entity_list = "', '".join(chunk_entities)
        entity_filter = f"AND s.entity_code IN ('{entity_list}')"
        entity_filter_actual = f"AND a.entity_code IN ('{entity_list}')"

        query = f"""
        WITH {operating_filter}
        {valid_entities}
        {parkhours_cte}
        synthetic AS (
            SELECT
                s.entity_code,
                s.park_date,
                s.observed_at,
                CAST(s.observed_at AS TIMESTAMP) as observed_at_ts,
                s.synthetic_actual as actual_time,
                dg.date_group_id,
                se.season,
                se.season_year,
                EXTRACT(HOUR FROM CAST(s.observed_at AS TIMESTAMP)) as hour_of_day,
                (EXTRACT(HOUR FROM CAST(s.observed_at AS TIMESTAMP)) - 6) * 60 + EXTRACT(MINUTE FROM CAST(s.observed_at AS TIMESTAMP)) as mins_since_6am,
                {mins_since_open_synth} as mins_since_open
            FROM read_parquet('{synth_pattern}') s
            INNER JOIN valid_entities ve ON s.entity_code = ve.entity_code
            LEFT JOIN read_csv('{dg_path}', AUTO_DETECT=TRUE) dg ON s.park_date = dg.park_date
            LEFT JOIN read_csv('{season_path_str}', AUTO_DETECT=TRUE) se ON s.park_date = se.park_date
            {parkhours_join_synth}
            WHERE dg.date_group_id IS NOT NULL AND se.season IS NOT NULL
              AND s.synthetic_actual > 0
              {entity_filter}
              {synth_filter}
        ),
        real_actuals AS (
            SELECT
                a.entity_code,
                a.park_date,
                a.observed_at,
                a.observed_at_ts,
                a.wait_time_minutes as actual_time,
                dg.date_group_id,
                se.season,
                se.season_year,
                EXTRACT(HOUR FROM a.observed_at_ts) as hour_of_day,
                (EXTRACT(HOUR FROM a.observed_at_ts) - 6) * 60 + EXTRACT(MINUTE FROM a.observed_at_ts) as mins_since_6am,
                {mins_since_open_actual} as mins_since_open
            FROM read_parquet('{parquet_str}/*.parquet') a
            INNER JOIN valid_entities ve ON a.entity_code = ve.entity_code
            LEFT JOIN read_csv('{dg_path}', AUTO_DETECT=TRUE) dg ON a.park_date = dg.park_date
            LEFT JOIN read_csv('{season_path_str}', AUTO_DETECT=TRUE) se ON a.park_date = se.park_date
            {parkhours_join_actual}
            WHERE a.wait_time_type = 'ACTUAL'
              AND a.wait_time_minutes IS NOT NULL
              AND a.wait_time_minutes > 0
              {entity_filter_actual}
              {actual_filter}
        ),
        combined AS (
            SELECT entity_code, park_date, observed_at, observed_at_ts, actual_time,
                   date_group_id, season, season_year, hour_of_day, mins_since_6am, mins_since_open,
                   TRUE as is_synthetic FROM synthetic
            UNION ALL
            SELECT entity_code, park_date, observed_at, observed_at_ts, actual_time,
                   date_group_id, season, season_year, hour_of_day, mins_since_6am, mins_since_open,
                   FALSE as is_synthetic FROM real_actuals
        )
        SELECT * FROM combined ORDER BY entity_code, observed_at
        """

        df = con.execute(query).fetchdf()
        if len(df) == 0:
            logger.info(f"  [{park_idx}/{len(parks)}] {park_code}: 0 rows (skip)")
            continue

        df["date_group_id_encoded"] = df["date_group_id"].astype(str).map(dg_mapping)
        df["season_encoded"] = df["season"].astype(str).map(season_mapping)
        df["season_year_encoded"] = df["season_year"].astype(str).map(sy_mapping)
        df = df.dropna(subset=["date_group_id_encoded", "season_encoded", "season_year_encoded"])
        df["date_group_id_encoded"] = df["date_group_id_encoded"].astype(int)
        df["season_encoded"] = df["season_encoded"].astype(int)
        df["season_year_encoded"] = df["season_year_encoded"].astype(int)

        chunk_path = chunk_dir / f"chunk_{park_code}.parquet"
        df.to_parquet(chunk_path, index=False)
        n_synth = int(df["is_synthetic"].sum())
        n_real = len(df) - n_synth
        total_rows += len(df)
        total_synthetic += n_synth
        total_real += n_real
        logger.info(f"  [{park_idx}/{len(parks)}] {park_code}: {len(df):,} rows (synth: {n_synth:,}, real: {n_real:,})")

    con.close()

    if total_rows == 0:
        logger.error("No actuals training rows generated")
        return 0

    # Keep per-park parquets for OOM-safe Julia training (no 90M-row load)
    output_dir_parks = output_dir / "actuals_training_v2"
    output_dir_parks.mkdir(exist_ok=True)
    for p in chunk_dir.glob("*.parquet"):
        park_code = p.stem.replace("chunk_", "")
        dest = output_dir_parks / f"{park_code}.parquet"
        p.rename(dest)
    chunk_dir.rmdir()

    # Also write combined file for tools that expect single file (streaming)
    park_files = list(output_dir_parks.glob("*.parquet"))
    if park_files:
        combined_path = output_dir / "actuals_training_v2.parquet"
        combined_path_str = str(combined_path).replace("\\", "/")
        pattern = str(output_dir_parks / "*.parquet").replace("\\", "/")
        con2 = duckdb.connect()
        con2.execute(f"""
            COPY (
                SELECT * FROM read_parquet('{pattern}')
                ORDER BY entity_code, observed_at
            ) TO '{combined_path_str}' (FORMAT PARQUET)
        """)
        con2.close()


    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("ACTUALS TRAINING DATA BUILD COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Output: {output_dir_parks}/ (per-park) + {output_dir / 'actuals_training_v2.parquet'}")
    logger.info(f"Rows: {total_rows:,} (synthetic: {total_synthetic:,}, real: {total_real:,})")
    logger.info(f"Entities: {len(entities)}")
    logger.info(f"Features: mins_since_6am, mins_since_open, date_group_id, season, season_year (NO posted_time)")
    logger.info(f"Build time: {elapsed:.1f}s")

    return len(df)


def main():
    parser = argparse.ArgumentParser(description="Build actuals-only training data")
    parser.add_argument("--output-base", type=Path, default=DEFAULT_OUTPUT_BASE)
    args = parser.parse_args()

    logger = setup_logging()
    output_base = args.output_base.resolve()
    n = build_actuals_training_data(logger, output_base)
    if n == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
