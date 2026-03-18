-- School Schedules Database v3
-- Star schema: dim_district, dim_calendar_source, fact_school_day

CREATE TABLE IF NOT EXISTS dim_district (
    district_id     TEXT PRIMARY KEY,       -- Our generated ID (slug: state_nces_id)
    nces_id         TEXT UNIQUE,            -- Federal NCES LEAID
    district_name   TEXT NOT NULL,
    state           TEXT NOT NULL,           -- 2-letter code
    city            TEXT,
    county          TEXT,
    zip             TEXT,
    lat             REAL,
    lon             REAL,
    enrollment      INTEGER,
    district_url    TEXT,                    -- District website
    district_email  TEXT,                    -- General contact email
    contact_name    TEXT,                    -- Superintendent or contact person name
    calendar_type   TEXT DEFAULT 'traditional',  -- traditional / year_round / modified
    phone           TEXT,                    -- District phone number
    mailing_address TEXT,                    -- Mailing address
    physical_address TEXT,                   -- Physical address
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dim_calendar_source (
    source_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    district_id     TEXT NOT NULL REFERENCES dim_district(district_id),
    school_year     TEXT NOT NULL,           -- e.g. '2025-2026'
    calendar_url    TEXT,                    -- URL where calendar was found
    scrape_method   TEXT,                    -- pdf / html / firecrawl / email / manual / barney_manual_v3
    scrape_date     TEXT DEFAULT (date('now')),
    raw_key_dates   TEXT,                    -- JSON blob of extracted key dates
    quality_confidence TEXT DEFAULT 'medium', -- high / medium / low
    notes           TEXT,
    is_primary      INTEGER DEFAULT 1,       -- 1 = primary source, 0 = secondary/QA
    UNIQUE(district_id, school_year, scrape_method)
);

CREATE TABLE IF NOT EXISTS fact_school_day (
    district_id     TEXT NOT NULL REFERENCES dim_district(district_id),
    source_id       INTEGER REFERENCES dim_calendar_source(source_id),
    date            TEXT NOT NULL,           -- YYYY-MM-DD
    day_of_week     INTEGER,                -- 0=Mon, 6=Sun (Python weekday)
    day_name        TEXT,                    -- Monday, Tuesday, etc.
    is_in_session   INTEGER NOT NULL,        -- 1 = school day, 0 = no school
    day_type        TEXT NOT NULL,           -- SCHOOL_DAY / WEEKEND / BREAK / HOLIDAY / TEACHER_WORKDAY / HALF_DAY / SUMMER
    break_name      TEXT,                    -- NULL if in session, else: WINTER, SPRING, FALL, THANKSGIVING, MARDI_GRAS, MLK_DAY, etc.
    notes           TEXT,                    -- e.g. "early release 12pm", "first day", "last day"
    school_year     TEXT NOT NULL,           -- e.g. '2025-2026'
    PRIMARY KEY (district_id, date, school_year)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_fact_date ON fact_school_day(date);
CREATE INDEX IF NOT EXISTS idx_fact_school_year ON fact_school_day(school_year);
CREATE INDEX IF NOT EXISTS idx_fact_day_type ON fact_school_day(day_type);
CREATE INDEX IF NOT EXISTS idx_fact_break_name ON fact_school_day(break_name);
CREATE INDEX IF NOT EXISTS idx_fact_is_in_session ON fact_school_day(date, is_in_session);
CREATE INDEX IF NOT EXISTS idx_district_state ON dim_district(state);
CREATE INDEX IF NOT EXISTS idx_source_year ON dim_calendar_source(school_year);
CREATE INDEX IF NOT EXISTS idx_source_district ON dim_calendar_source(district_id);
