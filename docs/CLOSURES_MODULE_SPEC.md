# Closures Module Specification

## Overview

The closures module handles both temporary and permanent attraction closures to ensure closed attractions are excluded from forecasts and WTI calculations. This module consists of two components that run sequentially in the daily pipeline.

## Pipeline Position

**Insert after:** Dimensions step (after `get_entity_table_from_s3.py`)  
**Insert before:** Impute Hours step  

Current pipeline order:
```
S3 Sync → ETL → CSV→Parquet → Dimensions → **[NEW: Closures]** → Impute Hours → Posted Aggregates → DB Report → Accuracy Evaluation → Hybrid Training V2 → Forecast → WTI
```

## Module Components

### 1. `get_closures_from_s3.py`
Downloads temporary closure data from S3.

### 2. `build_operating_calendar.py`
Processes closure data and builds the master operating calendar.

---

## Component 1: get_closures_from_s3.py

### Purpose
Downloads temporary closure CSV files from S3 and stores them locally for processing.

### S3 Data Source
- **Bucket:** `s3://touringplans_stats/export/closures/`
- **Files:**
  - `current_wdw_closures.csv`
  - `current_dlr_closures.csv`
  - `current_uor_closures.csv`
  - `current_tdr_closures.csv`
  - `current_ush_closures.csv`

### Input Schema (S3 CSV Files)
```
object_type: string    # "attraction", "restaurant", etc.
object_code: string    # Entity code (e.g., "MK01", "CA05")
object_name: string    # Entity name
start_date: string     # YYYY-MM-DD format (closure start)
finish_date: string    # YYYY-MM-DD format (closure end) or empty
```

### Output
- **Location:** `{output_base}/raw_closures/`
- **Files:** Downloaded CSV files with original names
- **Logging:** `{output_base}/logs/get_closures_YYYYMMDD_HHMMSS.log`

### Implementation Pattern
Follow the same pattern as `get_entity_table_from_s3.py`:
- boto3 S3 client with retry logic (MAX_RETRIES=3)
- Error handling for network failures
- Atomic file writes (tmp file → rename)
- Skip missing/failed files, continue with others
- Log download progress and file counts

### Error Handling
- Continue pipeline execution if S3 files are missing
- Log warnings for missing closure files
- If ALL closures files fail, log error but don't halt pipeline
- Downstream module (`build_operating_calendar.py`) handles empty input

---

## Component 2: build_operating_calendar.py

### Purpose
Combines permanent and temporary closure data to create a comprehensive operating calendar.

### Input Sources
1. **Permanent closures:** `{output_base}/dimension_tables/dimentity.csv` (`extinct_on` column)
2. **Temporary closures:** `{output_base}/raw_closures/*.csv` (from S3)
3. **Entity master list:** `{output_base}/dimension_tables/dimentity.csv` (all entities)

### Date Range
- **Start date:** Current date - 30 days (for historical analysis)
- **End date:** Current date + 365 days (forecast window)
- **Configurable:** Via command-line arguments `--start-date` and `--end-date`

### Processing Logic

#### Step 1: Load Entity Dimension
```python
import duckdb
con = duckdb.connect()

entities = con.execute("""
    SELECT code as entity_code, 
           COALESCE(extinct_on, '9999-12-31') as extinct_on
    FROM read_csv('{dim_dir}/dimentity.csv', AUTO_DETECT=TRUE)
""").fetchdf()
```

#### Step 2: Load Temporary Closures
```python
closures_df = con.execute("""
    SELECT object_code as entity_code,
           COALESCE(start_date, '1900-01-01') as closure_start,
           COALESCE(finish_date, '9999-12-31') as closure_end
    FROM read_csv('{raw_closures_dir}/*.csv', AUTO_DETECT=TRUE)
    WHERE object_type = 'attraction'  -- Only include attractions
""").fetchdf()
```

#### Step 3: Generate Date Range
```python
dates_df = con.execute("""
    SELECT CAST(date_series AS DATE) as park_date
    FROM generate_series(
        DATE '{start_date}',
        DATE '{end_date}',
        INTERVAL '1 day'
    ) AS t(date_series)
""").fetchdf()
```

#### Step 4: Build Operating Calendar
```python
calendar = con.execute("""
    WITH entity_dates AS (
        SELECT e.entity_code, d.park_date
        FROM entities e
        CROSS JOIN dates d
    ),
    permanent_closures AS (
        SELECT entity_code, park_date,
               CASE 
                   WHEN park_date >= CAST(extinct_on AS DATE) THEN FALSE
                   ELSE TRUE
               END as is_operating_permanent
        FROM entity_dates e
        JOIN entities ent ON e.entity_code = ent.entity_code
    ),
    temporary_closures AS (
        SELECT entity_code, park_date,
               CASE 
                   WHEN park_date >= CAST(closure_start AS DATE) 
                        AND park_date <= CAST(closure_end AS DATE) THEN FALSE
                   ELSE TRUE
               END as is_operating_temp
        FROM entity_dates e
        LEFT JOIN closures_df c ON e.entity_code = c.entity_code
    ),
    combined AS (
        SELECT p.entity_code, p.park_date,
               p.is_operating_permanent AND COALESCE(t.is_operating_temp, TRUE) as is_operating
        FROM permanent_closures p
        LEFT JOIN temporary_closures t ON p.entity_code = t.entity_code 
                                       AND p.park_date = t.park_date
    )
    SELECT entity_code, park_date, is_operating
    FROM combined
    ORDER BY entity_code, park_date
""").fetchdf()
```

### Output Schema
```
entity_code: string      # Entity code (e.g., "MK01", "CA05")
park_date: date         # Date in YYYY-MM-DD format
is_operating: boolean   # TRUE if attraction is operating, FALSE if closed
```

### Output Files
- **Primary:** `{output_base}/operating_calendar/operating_calendar.parquet`
- **Backup CSV:** `{output_base}/operating_calendar/operating_calendar.csv` (for debugging)
- **Logging:** `{output_base}/logs/build_operating_calendar_YYYYMMDD_HHMMSS.log`

### Fred's No-Null Design Implementation

#### Sentinel Dates
- **Unknown start date:** `1900-01-01`
- **Open-ended/unknown end date:** `9999-12-31`
- **Empty extinct_on:** Treat as `9999-12-31` (never extinct)

#### Column Handling
```python
# Ensure no nulls in date columns
closure_data = closure_data.copy()
closure_data['start_date'] = closure_data['start_date'].fillna('1900-01-01')
closure_data['finish_date'] = closure_data['finish_date'].fillna('9999-12-31')
```

### Edge Cases

#### 1. Entities Not in Closures Data
**Assumption:** Operating by default
```python
# LEFT JOIN ensures all entities included
# COALESCE handles missing closure records
is_operating_temp = COALESCE(temp_closure_flag, TRUE)
```

#### 2. Multiple Closure Windows
**Approach:** Union of all closure periods
```python
# If ANY closure window covers the date, mark as closed
WITH closure_coverage AS (
    SELECT entity_code, park_date,
           BOOL_OR(park_date >= closure_start AND park_date <= closure_end) as is_closed
    FROM entity_dates e
    LEFT JOIN closures c ON e.entity_code = c.entity_code
    GROUP BY entity_code, park_date
)
```

#### 3. Seasonal Entities
**Approach:** Rely on existing seasonal logic in pipeline
- Operating calendar shows TRUE/FALSE for scheduled operation
- Seasonal closures (planned) should be in the closures data
- Don't duplicate existing seasonal handling logic

#### 4. Overlapping Temporary and Permanent Closures
**Priority:** If either source shows closed, entity is closed
```python
is_operating = is_operating_permanent AND is_operating_temp
```

#### 5. Invalid Dates in Source Data
**Handling:** Skip invalid records, log warnings
```python
try:
    closure_start = pd.to_datetime(row['start_date']).date()
except:
    logger.warning(f"Invalid start_date for {entity_code}: {row['start_date']}")
    continue
```

---

## Downstream Integration

### Training Pipeline (`hybrid_pipeline_v2.py`)
Filter training data to exclude closed periods:

```python
# Load operating calendar
operating_cal = con.execute(f"""
    SELECT entity_code, park_date, is_operating
    FROM read_parquet('{output_base}/operating_calendar/operating_calendar.parquet')
""").fetchdf()

# Filter training data
training_data = con.execute(f"""
    SELECT w.entity_code, w.park_date, w.wait_time_minutes, w.observed_at_ts
    FROM read_parquet('{parquet_dir}/*.parquet') w
    JOIN read_parquet('{output_base}/operating_calendar/operating_calendar.parquet') oc
        ON w.entity_code = oc.entity_code 
        AND w.park_date = oc.park_date
    WHERE oc.is_operating = TRUE
      AND w.entity_code = '{entity_code}'
      AND w.wait_time_type = 'POSTED'
""").fetchdf()
```

### Forecasting Pipeline
Only generate forecasts for operating attractions:

```python
# Get entities operating on forecast dates
forecast_entities = con.execute(f"""
    SELECT DISTINCT entity_code
    FROM read_parquet('{output_base}/operating_calendar/operating_calendar.parquet')
    WHERE park_date BETWEEN '{forecast_start}' AND '{forecast_end}'
      AND is_operating = TRUE
""").fetchdf()['entity_code'].tolist()
```

### WTI Calculation
Exclude closed attractions from crowd level calculations:

```python
# Filter WTI inputs
wti_data = con.execute(f"""
    SELECT w.entity_code, w.park_date, w.wait_time_minutes
    FROM wait_time_data w
    JOIN read_parquet('{output_base}/operating_calendar/operating_calendar.parquet') oc
        ON w.entity_code = oc.entity_code 
        AND w.park_date = oc.park_date
    WHERE oc.is_operating = TRUE
""").fetchdf()
```

---

## Performance Considerations

### Memory Usage
- **Entity count:** ~2,000 entities
- **Date range:** ~395 days (30 historical + 365 forecast)
- **Total records:** ~790,000 rows
- **Estimated size:** ~20MB uncompressed, ~5MB parquet
- **Memory impact:** Minimal (< 100MB peak)

### Execution Time
- **DuckDB operations:** < 10 seconds
- **File I/O:** < 5 seconds  
- **Total runtime:** < 30 seconds

### File Storage
- **Parquet:** ~5MB daily
- **CSV backup:** ~15MB daily
- **S3 raw files:** ~1MB daily
- **Retention:** 30 days of raw files

---

## Testing Strategy

### Unit Tests
```python
def test_sentinel_dates():
    # Test null handling with sentinel dates
    
def test_multiple_closures():
    # Test overlapping closure windows
    
def test_missing_entities():
    # Test entities not in closure data
    
def test_date_range_generation():
    # Test proper date range coverage
```

### Integration Tests
```python
def test_e2e_pipeline():
    # Test full S3 download → calendar build → parquet output
    
def test_downstream_integration():
    # Test training pipeline can read operating calendar
    
def test_performance():
    # Test execution time < 30 seconds
```

### Data Validation
```python
def validate_operating_calendar():
    # All entities present
    # No missing dates in range
    # Boolean values only (no nulls)
    # Reasonable closure percentages (< 50% of entity-days)
```

---

## Monitoring & Alerts

### Pipeline Health Checks
- **File existence:** Operating calendar parquet exists and is recent
- **Data completeness:** All active entities have records for date range
- **Data quality:** No null values in is_operating column
- **Performance:** Execution time under 30 seconds

### Logging Requirements
- **S3 download:** Files found/missing, download success/failure
- **Processing:** Entity counts, date ranges, closure percentages
- **Output:** File sizes, record counts, validation results
- **Errors:** Invalid dates, missing data, processing failures

### Alerting Thresholds
- **ERROR:** Operating calendar file not created
- **WARN:** > 20% of entities closed on any single day  
- **WARN:** S3 closure files missing for > 24 hours
- **INFO:** Execution time > 20 seconds

---

## Command Line Interface

### get_closures_from_s3.py
```bash
python src/get_closures_from_s3.py [--output-base PATH]
```

### build_operating_calendar.py  
```bash
python src/build_operating_calendar.py [OPTIONS]

Options:
  --output-base PATH     Pipeline output directory [from config]
  --start-date DATE      Start date (YYYY-MM-DD) [today - 30 days]
  --end-date DATE        End date (YYYY-MM-DD) [today + 365 days]
  --force                Overwrite existing files
  --validate             Run data validation checks
```

---

## Migration Plan

### Phase 1: Module Development
1. Implement `get_closures_from_s3.py`
2. Implement `build_operating_calendar.py`
3. Add unit and integration tests
4. Validate against existing data

### Phase 2: Pipeline Integration
1. Add closures steps to cron job
2. Update downstream modules to use operating calendar
3. Monitor performance and data quality
4. Deploy to production

### Phase 3: Optimization
1. Monitor S3 costs and optimize download frequency
2. Tune date range based on actual usage patterns
3. Add additional validation and monitoring
4. Document lessons learned

---

## Configuration

### Environment Variables
```bash
# S3 credentials (shared with existing pipeline)
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION
```

### Config File Updates (config/config.json)
```json
{
  "closures": {
    "s3_bucket": "touringplans_stats",
    "s3_prefix": "export/closures/",
    "date_range_days_back": 30,
    "date_range_days_forward": 365,
    "retry_attempts": 3
  }
}
```

This specification provides a complete roadmap for implementing the closures module while maintaining consistency with the existing pipeline architecture and Fred's design principles.