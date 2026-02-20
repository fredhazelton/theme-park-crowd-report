"""
Theme Park Crowd Report — Discord Bot (Hazey)

MVP: /crowd, /best-day, /today slash commands
Reads from pipeline forecast data on disk.
"""

import os
import sys
import discord
from discord import app_commands
from dotenv import load_dotenv
import duckdb
from datetime import datetime, date as date_type, timedelta
from dateutil import parser
import pandas as pd
import re
import io
from pathlib import Path
from forecast_image import generate_forecast_image

# Add theme-park-crowd-report/src to sys.path for live inference model
theme_park_src = os.path.expanduser("~/theme-park-crowd-report/src")
if theme_park_src not in sys.path:
    sys.path.insert(0, theme_park_src)

try:
    from processors.live_inference import LiveInferenceModel
    LIVE_INFERENCE_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ Live inference model not available: {e}")
    LiveInferenceModel = None
    LIVE_INFERENCE_AVAILABLE = False

# Load token from ~/.env
load_dotenv(os.path.expanduser("~/.env"))
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Data paths
# --- Data paths ---
# Primary: shared DuckDB (populated by scraper + daily pipeline)
DUCKDB_PATH = "/mnt/data/pipeline/tpcr_live.duckdb"

# Fallback: direct file paths (used only if DuckDB is unavailable)
WTI_PATH = "/mnt/data/pipeline/wti/wti.parquet"
FORECASTS_PATH = "/mnt/data/pipeline/curves/forecast_parquet/all_forecasts.parquet"
ENTITIES_PATH = "/mnt/data/pipeline/dimension_tables/dimentity.csv"
STAGING_DIR = "/mnt/data/pipeline/staging/queue_times"
FACT_PARQUET_DIR = "/mnt/data/pipeline/fact_tables/parquet"

# DuckDB availability flag
_USE_DUCKDB = os.path.exists(DUCKDB_PATH)


def get_db():
    """Get a read-only DuckDB connection to the shared database."""
    return duckdb.connect(DUCKDB_PATH, read_only=True)

# Global entity name mapping - loaded at startup
entity_names = {}

# Global live inference model - loaded at startup
live_inference_model = None

# Park name mapping — accept everything a human might type
PARK_NAMES = {
    # --- Walt Disney World ---
    # Magic Kingdom
    "magic kingdom": ("MK", "Magic Kingdom"),
    "magic-kingdom": ("MK", "Magic Kingdom"),
    "magickingdom": ("MK", "Magic Kingdom"),
    "mk": ("MK", "Magic Kingdom"),
    # EPCOT
    "epcot": ("EP", "EPCOT"),
    "ep": ("EP", "EPCOT"),
    # Hollywood Studios
    "hollywood studios": ("HS", "Hollywood Studios"),
    "hollywood-studios": ("HS", "Hollywood Studios"),
    "hollywoodstudios": ("HS", "Hollywood Studios"),
    "hollywood": ("HS", "Hollywood Studios"),
    "hs": ("HS", "Hollywood Studios"),
    # Animal Kingdom
    "animal kingdom": ("AK", "Animal Kingdom"),
    "animal-kingdom": ("AK", "Animal Kingdom"),
    "animalkingdom": ("AK", "Animal Kingdom"),
    "ak": ("AK", "Animal Kingdom"),
    # --- Disneyland Resort ---
    # Disneyland
    "disneyland": ("DL", "Disneyland"),
    "dl": ("DL", "Disneyland"),
    # California Adventure
    "california adventure": ("CA", "California Adventure"),
    "california-adventure": ("CA", "California Adventure"),
    "californiaadventure": ("CA", "California Adventure"),
    "dca": ("CA", "California Adventure"),
    "ca": ("CA", "California Adventure"),
    # --- Universal Orlando ---
    # Universal Studios Florida
    "universal studios florida": ("UF", "Universal Studios Florida"),
    "universal studios": ("UF", "Universal Studios Florida"),
    "universal florida": ("UF", "Universal Studios Florida"),
    "usf": ("UF", "Universal Studios Florida"),
    "uf": ("UF", "Universal Studios Florida"),
    # Islands of Adventure
    "islands of adventure": ("IA", "Islands of Adventure"),
    "islands-of-adventure": ("IA", "Islands of Adventure"),
    "ioa": ("IA", "Islands of Adventure"),
    "ia": ("IA", "Islands of Adventure"),
    # Epic Universe
    "epic universe": ("EU", "Epic Universe"),
    "epic": ("EU", "Epic Universe"),
    "eu": ("EU", "Epic Universe"),
    # --- Universal Hollywood ---
    "universal hollywood": ("UH", "Universal Studios Hollywood"),
    "universal studios hollywood": ("UH", "Universal Studios Hollywood"),
    "ush": ("UH", "Universal Studios Hollywood"),
    "uh": ("UH", "Universal Studios Hollywood"),
    # --- Tokyo Disney Resort ---
    # Tokyo Disneyland (WTI uses combined "TD" but entities are TDL*)
    "tokyo disneyland": ("TDL", "Tokyo Disneyland"),
    "tokyo-disneyland": ("TDL", "Tokyo Disneyland"),
    "tdl": ("TDL", "Tokyo Disneyland"),
    # Tokyo DisneySea (WTI uses combined "TD" but entities are TDS*)
    "tokyo disneysea": ("TDS", "Tokyo DisneySea"),
    "tokyo-disneysea": ("TDS", "Tokyo DisneySea"),
    "disneysea": ("TDS", "Tokyo DisneySea"),
    "tds": ("TDS", "Tokyo DisneySea"),
    # Combined Tokyo shortcuts → default to Disneyland
    "tokyo disney": ("TDL", "Tokyo Disneyland"),
    "tokyo disney resort": ("TDL", "Tokyo Disneyland"),
    "tdr": ("TDL", "Tokyo Disneyland"),
    "td": ("TDL", "Tokyo Disneyland"),
}

# WTI code mapping — some parks use different codes for WTI vs entities
# (TDL and TDS now have their own WTI scores)
WTI_CODE_MAP = {
    # No mappings needed currently — all park codes match WTI directly
}

# Entity prefix mapping — some parks have multiple entity prefixes
# UH has both UH* and USH* entities
ENTITY_PREFIXES = {
    "UH": ["UH", "USH"],  # Universal Hollywood uses both UH and USH prefixes
}

# WTI color thresholds — median-anchored, data-driven
# p1=8, median=22, p99=50
# Blue = rare good days, White = normal Disney, Pink = plan carefully
def wti_emoji(wti: float) -> str:
    """Benedictus-aligned emoji — median-anchored"""
    if wti <= 12:
        return "❄️"   # Shortest waits
    elif wti <= 18:
        return "💎"   # Below average — great day
    elif wti <= 25:
        return "⚪"   # Normal Disney — typical crowds
    elif wti <= 34:
        return "🌸"   # Above average — plan ahead
    elif wti <= 42:
        return "🔥"   # Busy — rope drop essential
    elif wti <= 50:
        return "🔴"   # Very busy — consider another day
    else:
        return "💀"   # Extreme — avoid at all costs

def wti_label(wti: float) -> str:
    if wti <= 12:
        return "Shortest waits — best day to visit"
    elif wti <= 18:
        return "Short waits — great day to visit"
    elif wti <= 25:
        return "Typical day — moderate waits, plan headliners"
    elif wti <= 34:
        return "Above average — rope drop and Lightning Lane recommended"
    elif wti <= 42:
        return "Long waits — arrive early, plan strategically"
    elif wti <= 50:
        return "Very long waits — consider another day"
    else:
        return "Extreme waits — plan carefully or reschedule"

def get_embed_color(wti: float) -> int:
    """Get embed color based on WTI score — median-anchored Benedictus"""
    if wti <= 12:
        return 0x0A2F8F  # Deep blue — shortest waits
    elif wti <= 18:
        return 0x3C78D2  # Blue — low wait times
    elif wti <= 25:
        return 0xD2C8DC  # Lavender — normal Disney
    elif wti <= 34:
        return 0xFFB1C9  # Light pink — above average
    elif wti <= 42:
        return 0xEB427B  # Hot pink — busy
    elif wti <= 50:
        return 0xA60038  # Deep red — very busy
    else:
        return 0x50001E  # Near-black crimson — extreme

def parse_date(date_str: str) -> date_type:
    """Parse date string using dateutil, handling common formats"""
    date_str = date_str.lower().strip()
    
    # Handle relative dates
    if date_str == "today":
        return date_type.today()
    elif date_str == "tomorrow":
        return date_type.today() + timedelta(days=1)
    elif date_str == "yesterday":
        return date_type.today() - timedelta(days=1)
    
    # Handle date formats like "feb-15", "2026-02-20"
    try:
        # If it's just month-day, assume current year
        if re.match(r'^[a-z]{3}-\d{1,2}$', date_str):
            current_year = date_type.today().year
            date_str = f"{current_year}-{date_str}"
        
        parsed = parser.parse(date_str, default=datetime.now())
        return parsed.date()
    except (ValueError, TypeError):
        raise ValueError(f"Could not parse date: {date_str}")

def load_entity_names():
    """Load entity names from DuckDB (with CSV fallback)."""
    try:
        if _USE_DUCKDB:
            con = get_db()
            df = con.execute("""
                SELECT entity_code, entity_name, short_name, is_extinct
                FROM entities
            """).fetchdf()
            con.close()
            mapping = {}
            for _, row in df.iterrows():
                code = row['entity_code']
                name = row['entity_name'] if pd.notna(row['entity_name']) else code
                short = row['short_name'] if pd.notna(row['short_name']) else name
                extinct = bool(row['is_extinct']) if pd.notna(row['is_extinct']) else False
                mapping[code] = (name, short, extinct)
            print(f"📋 Loaded {len(mapping)} entity names from DuckDB")
            return mapping

        # Fallback: CSV
        entities_df = pd.read_csv(ENTITIES_PATH)
        mapping = {}
        for _, row in entities_df.iterrows():
            code = row['code']
            name = row['name'] if pd.notna(row['name']) else code
            if 'display_name' in entities_df.columns and pd.notna(row.get('display_name')):
                short_name = row['display_name']
            elif pd.notna(row.get('short_name')):
                short_name = row['short_name']
            else:
                short_name = name
            is_extinct = pd.notna(row.get('extinct_on'))
            mapping[code] = (name, short_name, is_extinct)
        return mapping
    except Exception as e:
        print(f"⚠️ Error loading entity names: {e}")
        return {}

def get_wti_score(park_code: str, target_date: date_type) -> float:
    """Get WTI score for park and date (DuckDB with parquet fallback)."""
    try:
        wti_code = WTI_CODE_MAP.get(park_code, park_code)

        if _USE_DUCKDB:
            con = get_db()
            result = con.execute("""
                SELECT wti FROM wti
                WHERE park_code = ? AND park_date = ?
                LIMIT 1
            """, [wti_code, target_date]).fetchone()
            con.close()
            return float(result[0]) if result else None

        # Fallback: parquet
        query = f"""
            SELECT wti 
            FROM read_parquet('{WTI_PATH}')
            WHERE park_code = '{wti_code}' 
              AND park_date = '{target_date}'
            LIMIT 1
        """
        result = duckdb.sql(query).fetchdf()
        if len(result) > 0:
            return float(result.iloc[0]['wti'])
        return None
    except Exception as e:
        print(f"⚠️ Error getting WTI score: {e}")
        return None

def _entity_filter_sql(park_code: str) -> str:
    """Build SQL WHERE clause for entity_code matching, handling multi-prefix parks."""
    prefixes = ENTITY_PREFIXES.get(park_code, [park_code])
    if len(prefixes) == 1:
        return f"entity_code LIKE '{prefixes[0]}%'"
    conditions = " OR ".join(f"entity_code LIKE '{p}%'" for p in prefixes)
    return f"({conditions})"


def get_forecasts(park_code: str, target_date: date_type):
    """Get entity forecasts for park and date (DuckDB with parquet fallback)."""
    try:
        entity_filter = _entity_filter_sql(park_code)

        if _USE_DUCKDB:
            con = get_db()
            result = con.execute(f"""
                SELECT entity_code, 
                       AVG(predicted_actual) as avg_wait,
                       MAX(predicted_actual) as peak_wait
                FROM forecasts
                WHERE {entity_filter}
                  AND park_date = ?
                  AND CAST(time_slot AS VARCHAR) BETWEEN '08:00' AND '22:00'
                GROUP BY entity_code
                ORDER BY avg_wait DESC
            """, [target_date]).fetchdf()
            con.close()
            return result

        # Fallback: parquet
        query = f"""
            SELECT entity_code, 
                   AVG(predicted_actual) as avg_wait,
                   MAX(predicted_actual) as peak_wait
            FROM read_parquet('{FORECASTS_PATH}')
            WHERE {entity_filter}
              AND park_date = '{target_date}'
              AND time_slot BETWEEN '08:00' AND '22:00'
            GROUP BY entity_code
            ORDER BY avg_wait DESC
        """
        result = duckdb.sql(query).fetchdf()
        return result
    except Exception as e:
        print(f"⚠️ Error getting forecasts: {e}")
        return pd.DataFrame()

def get_archived_forecasts(park_code: str, target_date: date_type):
    """Get forecast from archived forecast files (for today/past dates not in current forecast)."""
    try:
        archive_dir = "/mnt/data/pipeline/accuracy/archive"
        if not os.path.exists(archive_dir):
            return pd.DataFrame()
        
        # Find archived forecasts made BEFORE the target date
        archive_files = sorted([
            os.path.join(archive_dir, f)
            for f in os.listdir(archive_dir)
            if f.startswith("forecast_") and f.endswith(".parquet")
            and f.replace("forecast_", "").replace(".parquet", "") <= str(target_date)
        ])
        
        if not archive_files:
            return pd.DataFrame()
        
        # Use the most recent archive that was made before/on the target date
        forecast_archive = archive_files[-1]
        print(f"📂 Using archived forecast: {os.path.basename(forecast_archive)} for {target_date}")
        
        entity_filter = _entity_filter_sql(park_code)
        query = f"""
            SELECT entity_code,
                   AVG(predicted_actual) as avg_wait,
                   MAX(predicted_actual) as peak_wait
            FROM read_parquet('{forecast_archive}')
            WHERE {entity_filter}
              AND park_date = '{target_date}'
              AND time_slot BETWEEN '08:00' AND '22:00'
            GROUP BY entity_code
            ORDER BY avg_wait DESC
        """
        result = duckdb.sql(query).fetchdf()
        return result
    except Exception as e:
        print(f"⚠️ Error getting archived forecasts: {e}")
        return pd.DataFrame()


def get_live_waits(park_code: str, target_date: date_type):
    """Get actual posted wait times for today/past dates (DuckDB with file fallback)."""
    try:
        entity_filter = _entity_filter_sql(park_code)

        if _USE_DUCKDB:
            con = get_db()
            result = con.execute(f"""
                SELECT entity_code,
                       ROUND(AVG(wait_time_minutes), 0) as avg_wait,
                       MAX(wait_time_minutes) as peak_wait,
                       MAX(observed_at) as latest_obs
                FROM live_waits
                WHERE {entity_filter}
                  AND park_date = ?
                  AND wait_time_type = 'POSTED'
                  AND wait_time_minutes > 0
                GROUP BY entity_code
                ORDER BY avg_wait DESC
            """, [target_date]).fetchdf()
            con.close()
            return result

        # Fallback: CSV/parquet file scanning
        month_str = target_date.strftime("%Y-%m")
        staging_month = os.path.join(STAGING_DIR, month_str)
        sources = []
        if os.path.exists(staging_month):
            date_str = target_date.strftime("%Y-%m-%d")
            staging_files = [
                os.path.join(staging_month, f)
                for f in os.listdir(staging_month)
                if date_str in f and f.endswith(".csv")
            ]
            if staging_files:
                sources.extend(staging_files)
        if not sources:
            parquet_file = os.path.join(FACT_PARQUET_DIR, f"{month_str}.parquet")
            if os.path.exists(parquet_file):
                sources.append(parquet_file)
            else:
                return pd.DataFrame()
        csv_sources = [s for s in sources if s.endswith(".csv")]
        pq_sources = [s for s in sources if s.endswith(".parquet")]
        parts = []
        if csv_sources:
            file_list = "', '".join(csv_sources)
            df = duckdb.sql(f"""
                SELECT entity_code, ROUND(AVG(wait_time_minutes), 0) as avg_wait,
                       MAX(wait_time_minutes) as peak_wait, MAX(observed_at) as latest_obs
                FROM read_csv(['{file_list}'], AUTO_DETECT=TRUE)
                WHERE {entity_filter} AND wait_time_type = 'POSTED' AND wait_time_minutes > 0
                GROUP BY entity_code ORDER BY avg_wait DESC
            """).fetchdf()
            parts.append(df)
        if pq_sources:
            file_list = "', '".join(pq_sources)
            df = duckdb.sql(f"""
                SELECT entity_code, ROUND(AVG(wait_time_minutes), 0) as avg_wait,
                       MAX(wait_time_minutes) as peak_wait, MAX(observed_at_ts)::VARCHAR as latest_obs
                FROM read_parquet(['{file_list}'])
                WHERE {entity_filter} AND wait_time_type = 'POSTED' AND park_date = '{target_date}' AND wait_time_minutes > 0
                GROUP BY entity_code ORDER BY avg_wait DESC
            """).fetchdf()
            parts.append(df)
        if parts:
            result = pd.concat(parts, ignore_index=True)
            result = result.sort_values("latest_obs", ascending=False).drop_duplicates("entity_code")
            return result.sort_values("avg_wait", ascending=False)
        return pd.DataFrame()
    except Exception as e:
        print(f"⚠️ Error getting live waits: {e}")
        return pd.DataFrame()


def get_current_waits(park_code: str, target_date: date_type):
    """Get most recent posted wait times (not daily averages) for live display.
    DuckDB primary, CSV/parquet fallback."""
    try:
        entity_filter = _entity_filter_sql(park_code)

        if _USE_DUCKDB:
            con = get_db()
            result = con.execute(f"""
                WITH latest AS (
                    SELECT entity_code, MAX(observed_at) as max_obs
                    FROM live_waits
                    WHERE {entity_filter}
                      AND park_date = ?
                      AND wait_time_type = 'POSTED'
                      AND wait_time_minutes > 0
                    GROUP BY entity_code
                )
                SELECT w.entity_code,
                       w.wait_time_minutes as current_wait,
                       w.observed_at as latest_obs
                FROM live_waits w
                JOIN latest l ON w.entity_code = l.entity_code
                             AND w.observed_at = l.max_obs
                WHERE w.wait_time_type = 'POSTED'
                  AND w.wait_time_minutes > 0
                ORDER BY w.wait_time_minutes DESC
            """, [target_date]).fetchdf()
            con.close()
            return result

        # Fallback: CSV/parquet file scanning
        month_str = target_date.strftime("%Y-%m")
        staging_month = os.path.join(STAGING_DIR, month_str)
        sources = []
        if os.path.exists(staging_month):
            date_str = target_date.strftime("%Y-%m-%d")
            staging_files = [
                os.path.join(staging_month, f)
                for f in os.listdir(staging_month)
                if date_str in f and f.endswith(".csv")
            ]
            if staging_files:
                sources.extend(staging_files)
        if not sources:
            parquet_file = os.path.join(FACT_PARQUET_DIR, f"{month_str}.parquet")
            if os.path.exists(parquet_file):
                sources.append(parquet_file)
            else:
                return pd.DataFrame()
        csv_sources = [s for s in sources if s.endswith(".csv")]
        pq_sources = [s for s in sources if s.endswith(".parquet")]
        parts = []
        if csv_sources:
            file_list = "', '".join(csv_sources)
            df = duckdb.sql(f"""
                WITH latest_obs AS (
                    SELECT entity_code, MAX(observed_at) as max_observed_at
                    FROM read_csv(['{file_list}'], AUTO_DETECT=TRUE)
                    WHERE {entity_filter} AND wait_time_type = 'POSTED' AND wait_time_minutes > 0
                    GROUP BY entity_code
                )
                SELECT w.entity_code, w.wait_time_minutes as current_wait, w.observed_at as latest_obs
                FROM read_csv(['{file_list}'], AUTO_DETECT=TRUE) w
                INNER JOIN latest_obs l ON w.entity_code = l.entity_code AND w.observed_at = l.max_observed_at
                WHERE w.{entity_filter} AND w.wait_time_type = 'POSTED' AND w.wait_time_minutes > 0
                ORDER BY w.wait_time_minutes DESC
            """).fetchdf()
            parts.append(df)
        if pq_sources:
            file_list = "', '".join(pq_sources)
            df = duckdb.sql(f"""
                WITH latest_obs AS (
                    SELECT entity_code, MAX(observed_at_ts) as max_observed_at_ts
                    FROM read_parquet(['{file_list}'])
                    WHERE {entity_filter} AND wait_time_type = 'POSTED' AND park_date = '{target_date}' AND wait_time_minutes > 0
                    GROUP BY entity_code
                )
                SELECT w.entity_code, w.wait_time_minutes as current_wait, w.observed_at_ts::VARCHAR as latest_obs
                FROM read_parquet(['{file_list}']) w
                INNER JOIN latest_obs l ON w.entity_code = l.entity_code AND w.observed_at_ts = l.max_observed_at_ts
                WHERE w.{entity_filter} AND w.wait_time_type = 'POSTED' AND w.park_date = '{target_date}' AND w.wait_time_minutes > 0
                ORDER BY w.wait_time_minutes DESC
            """).fetchdf()
            parts.append(df)
        if parts:
            result = pd.concat(parts, ignore_index=True)
            result = result.sort_values("latest_obs", ascending=False).drop_duplicates("entity_code")
            return result.sort_values("current_wait", ascending=False)
        return pd.DataFrame()
    except Exception as e:
        print(f"⚠️ Error getting current waits: {e}")
        return pd.DataFrame()


def get_wti_range(park_code: str, target_date: date_type) -> dict:
    """Get low/avg/high WTI for a park on a date (from time-slot level forecasts).
    DuckDB primary, parquet fallback."""
    try:
        entity_filter = _entity_filter_sql(park_code)

        if _USE_DUCKDB:
            con = get_db()
            result = con.execute(f"""
                SELECT CAST(time_slot AS VARCHAR) as time_slot, AVG(predicted_actual) as slot_avg
                FROM forecasts
                WHERE {entity_filter}
                  AND park_date = ?
                  AND CAST(time_slot AS VARCHAR) BETWEEN '08:00' AND '22:00'
                GROUP BY time_slot
                ORDER BY time_slot
            """, [target_date]).fetchdf()
            con.close()
        else:
            query = f"""
                SELECT time_slot, AVG(predicted_actual) as slot_avg
                FROM read_parquet('{FORECASTS_PATH}')
                WHERE {entity_filter}
                  AND park_date = '{target_date}'
                  AND time_slot BETWEEN '08:00' AND '22:00'
                GROUP BY time_slot
                ORDER BY time_slot
            """
            result = duckdb.sql(query).fetchdf()

        if len(result) == 0:
            return None
        return {
            "wti_low": float(result["slot_avg"].min()),
            "wti_avg": float(result["slot_avg"].mean()),
            "wti_high": float(result["slot_avg"].max()),
        }
    except Exception as e:
        print(f"⚠️ Error getting WTI range: {e}")
        return None


@client.event
async def on_ready():
    global entity_names, live_inference_model
    print(f"✅ Logged in as {client.user} (ID: {client.user.id})")
    print(f"💾 Data mode: {'DuckDB (' + DUCKDB_PATH + ')' if _USE_DUCKDB else 'File fallback (parquet/CSV)'}")
    
    # Load entity names at startup
    print("📋 Loading entity names...")
    entity_names = load_entity_names()
    print(f"✅ Loaded {len(entity_names)} entity names")
    
    # Load live inference model at startup
    if LIVE_INFERENCE_AVAILABLE:
        try:
            print("🤖 Loading live inference model...")
            live_inference_model = LiveInferenceModel(output_base=Path("/mnt/data/pipeline"))
            print("✅ Live inference model loaded successfully")
        except Exception as e:
            print(f"⚠️ Failed to load live inference model: {e}")
            live_inference_model = None
    else:
        print("⚠️ Live inference model not available")
    
    # Sync to test guild for instant updates (no global rate limit)
    TEST_GUILD = discord.Object(id=1471374656253591695)
    try:
        # Clear existing guild commands first to force refresh
        tree.clear_commands(guild=TEST_GUILD)
        tree.copy_global_to(guild=TEST_GUILD)
        synced = await tree.sync(guild=TEST_GUILD)
        print(f"✅ Slash commands synced to test guild: {[c.name for c in synced]}")
        # Verify what Discord actually has
        fetched = await tree.fetch_commands(guild=TEST_GUILD)
        for cmd in fetched:
            print(f"   → /{cmd.name}: {cmd.description}")
            for opt in cmd.options:
                print(f"     param '{opt.name}': {opt.description} | choices={[c.name for c in opt.choices] if opt.choices else 'none'}")
    except Exception as e:
        print(f"❌ Command sync failed: {e}")
    await client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="the queues 👀"
        )
    )


# Autocomplete choices for park parameter
PARK_CHOICES = [
    # Walt Disney World
    app_commands.Choice(name="Magic Kingdom", value="magic kingdom"),
    app_commands.Choice(name="EPCOT", value="epcot"),
    app_commands.Choice(name="Hollywood Studios", value="hollywood studios"),
    app_commands.Choice(name="Animal Kingdom", value="animal kingdom"),
    # Disneyland Resort
    app_commands.Choice(name="Disneyland", value="disneyland"),
    app_commands.Choice(name="California Adventure", value="california adventure"),
    # Universal Orlando
    app_commands.Choice(name="Universal Studios Florida", value="universal studios florida"),
    app_commands.Choice(name="Islands of Adventure", value="islands of adventure"),
    app_commands.Choice(name="Epic Universe", value="epic universe"),
    # Universal Hollywood
    app_commands.Choice(name="Universal Studios Hollywood", value="universal hollywood"),
    # Tokyo Disney Resort
    app_commands.Choice(name="Tokyo Disneyland", value="tokyo disneyland"),
    app_commands.Choice(name="Tokyo DisneySea", value="tokyo disneysea"),
]

@tree.command(name="crowd", description="Get the crowd forecast for a park on a given date")
@app_commands.describe(
    park="Which park?",
    date="Date to check (default: today; e.g., tomorrow, feb-15, 2026-02-20)"
)
@app_commands.choices(park=PARK_CHOICES)
async def crowd_command(interaction: discord.Interaction, park: str, date: str = "today"):
    print(f"📥 /crowd called: park='{park}' date='{date}' by {interaction.user}")
    park_key = park.lower().strip()
    
    if park_key not in PARK_NAMES:
        await interaction.response.send_message(
            f"🤔 I don't recognize **{park}**. Try: `Magic Kingdom`, `EPCOT`, `Hollywood Studios`, `Animal Kingdom`, `Disneyland`, or `California Adventure`",
            ephemeral=True
        )
        return
    
    park_code, park_full = PARK_NAMES[park_key]
    
    # Parse the date
    try:
        target_date = parse_date(date)
    except ValueError as e:
        await interaction.response.send_message(
            f"🤔 I couldn't understand that date. Try: `today`, `tomorrow`, `feb-15`, or `2026-02-20`",
            ephemeral=True
        )
        return
    
    # Defer response since we're doing database queries
    await interaction.response.defer()
    
    # For today: try archived forecasts first (yesterday's prediction for today)
    # For future: use current forecast file
    # For past: use archived forecasts
    forecasts_df = get_forecasts(park_code, target_date)
    
    if len(forecasts_df) == 0 and target_date <= date_type.today():
        # Not in current forecast file — check archived forecasts
        forecasts_df = get_archived_forecasts(park_code, target_date)
    
    if len(forecasts_df) == 0:
        await interaction.followup.send(
            f"😔 No forecast data available for **{park_full}** on **{target_date.strftime('%B %d, %Y')}**.\n"
            f"This usually means the pipeline hasn't generated forecasts for this date yet.\n"
            f"Try **tomorrow** or a future date!",
            ephemeral=True
        )
        return
    
    # Get WTI score
    wti_score = get_wti_score(park_code, target_date)
    
    if wti_score is None:
        await interaction.followup.send(
            f"😔 I don't have forecast data for **{park_full}** on **{target_date.strftime('%B %d, %Y')}**.\n"
            f"Try a different date or park!",
            ephemeral=True
        )
        return
    
    # Process forecasts to get headliners and low waits (skip extinct entities)
    headliners = []
    low_waits = []
    
    for _, row in forecasts_df.iterrows():
        entity_code = row['entity_code']
        avg_wait = row['avg_wait']
        
        # Skip extinct entities
        if entity_code in entity_names and entity_names[entity_code][2]:  # is_extinct
            continue
        
        if entity_code in entity_names:
            display_name = entity_names[entity_code][1]
        else:
            display_name = entity_code
        if avg_wait > 25:
            headliners.append((display_name, int(avg_wait)))
        elif avg_wait > 0:
            low_waits.append((display_name, int(avg_wait)))
    
    headliners = sorted(headliners, key=lambda x: x[1], reverse=True)[:5]
    low_waits = sorted(low_waits, key=lambda x: x[1])[:5]
    
    embed = discord.Embed(
        title=f"{wti_emoji(wti_score)} {park_full} — {target_date.strftime('%b %d')}",
        url=f"https://hazeydata.ai/year-view?park={park_code}",
        description=f"**{wti_label(wti_score)}.** WTI {wti_score:.0f} — expect {int(wti_score*0.7)}-{int(wti_score*1.2)} min on headliners.",
        color=get_embed_color(wti_score),
    )
    
    if headliners:
        headliner_text = "\n".join([f"{name}: {wait} min" for name, wait in headliners])
        embed.add_field(name="🎢 Headliners", value=headliner_text, inline=True)
    if low_waits:
        low_wait_text = "\n".join([f"{name}: {wait} min" for name, wait in low_waits])
        embed.add_field(name="✨ Low Waits", value=low_wait_text, inline=True)
    
    # Park-appropriate priority queue tips
    if park_code in ("UF", "IA", "EU", "UH"):
        priority_tip = "Universal Express"
    elif park_code in ("TDL", "TDS"):
        priority_tip = "Priority Pass"
    else:
        priority_tip = "Lightning Lane"  # Disney WDW + DLR

    if wti_score > 50:
        tip = f"💡 Very busy day — use {priority_tip} and arrive early"
    elif wti_score > 35:
        tip = "💡 Hit headliners at rope drop or after 7pm"
    else:
        tip = "💡 Great day to enjoy everything at your pace"
    
    embed.set_footer(text=f"{tip}  •  Theme Park Crowd Report")
    
    await interaction.followup.send(embed=embed)


TIMEFRAME_CHOICES = [
    app_commands.Choice(name="Next 7 days", value=7),
    app_commands.Choice(name="Next 30 days", value=30),
    app_commands.Choice(name="Next 90 days", value=90),
    app_commands.Choice(name="Next 1 year", value=365),
]

@tree.command(name="best-day", description="Find the best day to visit a park (lowest wait times)")
@app_commands.describe(
    park="Which park?",
    timeframe="How far ahead to look (default: 7 days)"
)
@app_commands.choices(park=PARK_CHOICES, timeframe=TIMEFRAME_CHOICES)
async def best_day_command(interaction: discord.Interaction, park: str, timeframe: int = 7):
    print(f"📥 /best-day called: park='{park}' timeframe={timeframe} by {interaction.user}")

    # NOTE: Premium gate removed during alpha — all features free
    # TODO: Re-enable premium gates when ready to monetize

    park_key = park.lower().strip()

    if park_key not in PARK_NAMES:
        await interaction.response.send_message(
            f"🤔 I don't recognize **{park}**. Try the dropdown!",
            ephemeral=True
        )
        return

    park_code, park_full = PARK_NAMES[park_key]
    await interaction.response.defer()

    from datetime import timedelta
    start = date_type.today() + timedelta(days=1)  # tomorrow
    end = date_type.today() + timedelta(days=timeframe)

    try:
        wti_code = WTI_CODE_MAP.get(park_code, park_code)
        if _USE_DUCKDB:
            con = get_db()
            df = con.execute("""
                SELECT park_date, wti FROM wti
                WHERE park_code = ? AND park_date BETWEEN ? AND ?
                ORDER BY park_date
            """, [wti_code, start, end]).fetchdf()
            con.close()
        else:
            query = f"""
                SELECT park_date, wti
                FROM read_parquet('{WTI_PATH}')
                WHERE park_code = '{wti_code}'
                  AND park_date BETWEEN '{start}' AND '{end}'
                ORDER BY park_date
            """
            df = duckdb.sql(query).fetchdf()
    except Exception as e:
        print(f"⚠️ Error in /best-day: {e}")
        await interaction.followup.send("😔 Something went wrong querying the data.", ephemeral=True)
        return

    if len(df) == 0:
        await interaction.followup.send(
            f"😔 No forecast data for **{park_full}** in the next {timeframe} days.",
            ephemeral=True
        )
        return

    # Build per-day WTI ranges (low/avg/high from time slots)
    days_data = []
    for _, row in df.iterrows():
        d = row['park_date']
        if isinstance(d, pd.Timestamp):
            d = d.date()
        wti_range = get_wti_range(park_code, d)
        if wti_range:
            days_data.append({
                "date": d,
                "wti_low": wti_range["wti_low"],
                "wti_avg": wti_range["wti_avg"],
                "wti_high": wti_range["wti_high"],
            })

    if not days_data:
        await interaction.followup.send(
            f"😔 No detailed forecasts for **{park_full}** in the next {timeframe} days yet.",
            ephemeral=True
        )
        return

    # Sort by date for the image (chronological)
    days_data.sort(key=lambda x: x["date"])

    # Generate the forecast image
    img_buf = generate_forecast_image(park_full, days_data)
    file = discord.File(fp=img_buf, filename="forecast.png")

    # Find best and worst days
    best = min(days_data, key=lambda x: x["wti_avg"])
    worst = max(days_data, key=lambda x: x["wti_avg"])

    embed = discord.Embed(
        title=f"📅 {park_full} — Next {timeframe} Days",
        url=f"https://hazeydata.ai/year-view?park={park_code}",
        description=f"Daily wait times: **low** · avg · **high** WTI",
        color=get_embed_color(best["wti_avg"]),
    )
    embed.set_image(url="attachment://forecast.png")

    tip = f"💡 Best day: {best['date'].strftime('%A %b %d')} — {wti_label(best['wti_avg']).lower()}"
    embed.set_footer(text=f"{tip}  •  Theme Park Crowd Report")

    await interaction.followup.send(embed=embed, file=file)


@tree.command(name="today", description="Quick overview of all parks today")
async def today_command(interaction: discord.Interaction):
    print(f"📥 /today called by {interaction.user}")
    await interaction.response.defer()

    target_date = date_type.today()
    date_display = target_date.strftime("%A, %B %d")

    # Parks grouped by resort
    park_groups = [
        ("🏰 Walt Disney World", [
            ("MK", "Magic Kingdom"),
            ("EP", "EPCOT"),
            ("HS", "Hollywood Studios"),
            ("AK", "Animal Kingdom"),
        ]),
        ("🎠 Disneyland Resort", [
            ("DL", "Disneyland"),
            ("CA", "California Adventure"),
        ]),
        ("🦈 Universal Orlando", [
            ("UF", "Universal Studios Florida"),
            ("IA", "Islands of Adventure"),
            ("EU", "Epic Universe"),
        ]),
        ("🎬 Universal Hollywood", [
            ("UH", "Universal Studios Hollywood"),
        ]),
        ("🗼 Tokyo Disney Resort", [
            ("TDL", "Tokyo Disneyland"),
            ("TDS", "Tokyo DisneySea"),
        ]),
    ]


    embed = discord.Embed(
        title=f"\U0001f3f0 All Parks \u2014 {date_display}",
        url="https://hazeydata.ai",
        color=0x0A2F8F,
    )

    best_picks = []  # (resort_name, park_name, wti) per resort group

    for group_name, parks in park_groups:
        lines = []
        group_best_park = None
        group_best_wti = 999
        for park_code, park_name in parks:
            wti = get_wti_score(park_code, target_date)
            if wti is not None:
                emoji = wti_emoji(wti)
                label = wti_label(wti)
                lines.append(f"{emoji} **{park_name}** \u2014 WTI {wti:.0f}\n\u2570 *{label}*")
                if wti < group_best_wti:
                    group_best_wti = wti
                    group_best_park = park_name
            else:
                lines.append(f"\u2b1c **{park_name}** \u2014 No data")

        if lines:
            embed.add_field(name=group_name, value="\n".join(lines), inline=False)

        if group_best_park and len(parks) > 1:
            best_picks.append((group_name, group_best_park, group_best_wti))

    if best_picks:
        picks_text = "\n".join(
            f"\u2b50 **{park}** (WTI {wti:.0f})" for _, park, wti in best_picks
        )
        embed.add_field(name="Best picks by resort", value=picks_text, inline=False)

    embed.set_footer(text="\U0001f4a1 /now [park] for live wait times \u2022 /crowd [park] for forecasts  \u2022  hazeydata.ai")

    await interaction.followup.send(embed=embed)


def _wait_dot(minutes: int) -> str:
    """Color dot based on estimated actual wait time."""
    if minutes >= 60:
        return "\U0001f534"
    elif minutes >= 30:
        return "\U0001f7e0"
    elif minutes >= 15:
        return "\U0001f7e1"
    return "\U0001f7e2"


@tree.command(name="now", description="Live wait times right now for a park")
@app_commands.describe(park="Which park?")
@app_commands.choices(park=PARK_CHOICES)
async def now_command(interaction: discord.Interaction, park: str):
    print(f"\U0001f4e5 /now called: park='{park}' by {interaction.user}")
    await interaction.response.defer()

    park_key = park.lower().strip()
    if park_key not in PARK_NAMES:
        await interaction.followup.send(
            f"\U0001f914 I don't recognize **{park}**. Try the dropdown!", ephemeral=True
        )
        return

    park_code, park_full = PARK_NAMES[park_key]
    target_date = date_type.today()

    # Get current waits
    current_waits = get_current_waits(park_code, target_date)

    if current_waits.empty:
        wti = get_wti_score(park_code, target_date)
        wti_str = f" (WTI {wti:.0f})" if wti is not None else ""
        await interaction.followup.send(
            f"\U0001f634 No live wait time data for **{park_full}**{wti_str} right now. "
            f"The park may be closed.\n\n\U0001f4a1 Try `/crowd {park}` for today's forecast.",
            ephemeral=True
        )
        return

    # Get WTI for header
    wti = get_wti_score(park_code, target_date)
    wti_str = f" \u2014 WTI {wti:.0f}" if wti is not None else ""

    embed = discord.Embed(
        title=f"\u23f1\ufe0f {park_full}{wti_str}",
        url=f"https://hazeydata.ai/year-view?park={park_code}",
        description="Live estimated wait times",
        color=0x0A2F8F,
    )

    ride_lines = []
    for _, row in current_waits.iterrows():
        entity_code = row['entity_code']
        posted_wait = int(row['current_wait'])

        # Get ride name
        if entity_code in entity_names:
            ride_name = entity_names[entity_code][1]  # short_name
        else:
            ride_name = entity_code

        # Convert posted -> estimated actual
        estimated = posted_wait
        if live_inference_model is not None:
            try:
                obs_dt = parser.parse(str(row['latest_obs']))
                pred = live_inference_model.predict(entity_code, float(posted_wait), obs_dt)
                estimated = pred['predicted_actual']
            except Exception as e:
                print(f"\u26a0\ufe0f Live inference failed for {entity_code}: {e}")

        dot = _wait_dot(estimated)
        ride_lines.append((ride_name, estimated, dot))

    # Sort by wait time descending
    ride_lines.sort(key=lambda x: -x[1])

    # Build the display
    lines_text = []
    for name, wait, dot in ride_lines:
        if wait > 0:
            lines_text.append(f"{dot} **{name}** \u2014 {wait} min")

    # Discord field value limit is 1024 chars - split if needed
    if lines_text:
        chunk = []
        chunk_len = 0
        field_num = 1
        for line in lines_text:
            if chunk_len + len(line) + 1 > 1000:
                label = "Rides" if field_num == 1 else "\u200b"
                embed.add_field(name=label, value="\n".join(chunk), inline=False)
                chunk = []
                chunk_len = 0
                field_num += 1
            chunk.append(line)
            chunk_len += len(line) + 1
        if chunk:
            label = "Rides" if field_num == 1 else "\u200b"
            embed.add_field(name=label, value="\n".join(chunk), inline=False)

    embed.set_footer(text="\u23f1\ufe0f Updated every 5 min  \u2022  /crowd for forecasts  \u2022  hazeydata.ai")

    await interaction.followup.send(embed=embed)



@tree.command(name="ping", description="Check if the bot is alive")
async def ping_command(interaction: discord.Interaction):
    latency = round(client.latency * 1000)
    await interaction.response.send_message(f"🏰 Pong! {latency}ms — I'm watching the queues.")


@tree.command(name="health", description="Check data pipeline health and freshness")
async def health_command(interaction: discord.Interaction):
    """Show data freshness status — alerts if data is stale."""
    from datetime import datetime, timezone
    await interaction.response.defer(ephemeral=True)

    if not _USE_DUCKDB:
        await interaction.followup.send(
            "⚠️ DuckDB not initialized — running in fallback file mode.", ephemeral=True
        )
        return

    try:
        con = get_db()
        now = datetime.now(timezone.utc)

        # Data freshness from tracking table
        freshness = con.execute("SELECT source, last_updated, row_count, notes FROM data_freshness").fetchdf()

        # Latest live wait observation
        latest_live = con.execute("""
            SELECT MAX(observed_at) as latest, COUNT(DISTINCT entity_code) as entities
            FROM live_waits WHERE park_date = CURRENT_DATE
        """).fetchone()

        # Table counts
        counts = {}
        for table in ['live_waits', 'wti', 'forecasts', 'entities']:
            counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        con.close()

        # Build status
        lines = ["**📊 Data Pipeline Health**\n"]

        # Scraper status
        scraper_row = freshness[freshness['source'] == 'scraper']
        if not scraper_row.empty:
            scraper_ts = pd.to_datetime(scraper_row.iloc[0]['last_updated'])
            if scraper_ts.tzinfo is None:
                scraper_ts = scraper_ts.tz_localize('UTC')
            age_min = (now - scraper_ts).total_seconds() / 60
            if age_min > 15:
                lines.append(f"🔴 **Scraper:** Last update {age_min:.0f} min ago — STALE")
            elif age_min > 10:
                lines.append(f"🟡 **Scraper:** Last update {age_min:.0f} min ago")
            else:
                lines.append(f"🟢 **Scraper:** Last update {age_min:.0f} min ago")
        else:
            lines.append("⚪ **Scraper:** No data")

        # Pipeline status
        for source in ['wti', 'forecasts']:
            row = freshness[freshness['source'] == source]
            if not row.empty:
                ts = pd.to_datetime(row.iloc[0]['last_updated'])
                if ts.tzinfo is None:
                    ts = ts.tz_localize('UTC')
                age_hr = (now - ts).total_seconds() / 3600
                status = "🟢" if age_hr < 26 else "🔴" if age_hr > 48 else "🟡"
                lines.append(f"{status} **{source.upper()}:** Updated {age_hr:.1f}h ago ({row.iloc[0]['row_count']:,} rows)")
            else:
                lines.append(f"⚪ **{source.upper()}:** No data")

        # Live data today
        if latest_live and latest_live[0]:
            lines.append(f"\n**Today:** {latest_live[1]} entities reporting, latest obs: {str(latest_live[0])[:19]}")

        # Table sizes
        lines.append(f"\n**Tables:** {counts['live_waits']:,} waits · {counts['wti']:,} WTI · {counts['forecasts']:,} forecasts · {counts['entities']:,} entities")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❌ Health check failed: {e}", ephemeral=True)


@tree.command(name="about", description="Learn about Theme Park Crowd Report")
async def about_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏰 Theme Park Crowd Report",
        description=(
            "**The Wait Time Index (WTI)** is the #1 most consistent metric that "
            "tells you how long you're going to wait in line.\n\n"
            "Built by **Fred Hazelton**, former TouringPlans analyst."
        ),
        color=0x0A2F8F,
    )
    embed.add_field(
        name="🤖 Commands",
        value=(
            "`/today` — All parks at a glance\n"
            "`/crowd [park] [date]` — Detailed park forecast\n"
            "`/best-day [park] [days]` — Find the lowest-crowd day\n"
            "`/ping` — Check if I'm alive"
        ),
        inline=False
    )
    embed.add_field(
        name="📊 What's Inside",
        value=(
            "• **12 parks:** WDW, Disneyland, Universal, Tokyo Disney\n"
            "• **WTI Score:** One number = whole-park wait time level\n"
            "• **Ride-by-ride:** Top headliners and low-wait picks\n"
            "• **Updated daily** from real queue data"
        ),
        inline=False
    )
    embed.add_field(
        name="🔗 Links",
        value="[hazeydata.ai](https://hazeydata.ai)",
        inline=False
    )
    embed.set_footer(text="Theme Park Crowd Report  •  Alpha")
    await interaction.response.send_message(embed=embed)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_BOT_TOKEN not found in ~/.env")
        exit(1)
    client.run(TOKEN)
