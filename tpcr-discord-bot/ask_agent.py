"""
Ask Agent — AI-powered natural language query engine for TPCR Discord bot.

Uses Anthropic Claude (Haiku) with DuckDB tool access to answer
theme park wait time questions from Discord users.
"""

import json
import duckdb
import anthropic
from datetime import datetime, date
from pathlib import Path
from typing import Optional

DUCKDB_PATH = "/mnt/data/pipeline/tpcr_live.duckdb"

# Schema context for the AI agent
SCHEMA_CONTEXT = """You are a theme park data analyst for the Theme Park Crowd Report (TPCR).
You answer questions about theme park crowds, wait times, and visit planning using real forecast data.

## Database: DuckDB at /mnt/data/pipeline/tpcr_live.duckdb (READ-ONLY)

### Tables

**wti** — Wait Time Index (park-level daily crowd metric, scale ~1-60+)
- park_code: VARCHAR (AK, CA, DL, EP, EU, HS, IA, MK, TDL, TDS, UF, UH)
- park_date: DATE
- time_slot: VARCHAR ('daily' for full-day WTI)
- wti: DOUBLE (lower = less crowded)
- source: VARCHAR ('forecast' or 'actual')

**forecasts** — Ride-level wait time predictions (5-min intervals)
- entity_code: VARCHAR (e.g., 'MK01', 'EP05')
- park_date: DATE
- time_slot: VARCHAR (HH:MM:SS format, e.g., '14:00:00')
- predicted_actual: DOUBLE (predicted actual wait in minutes)
- predicted_posted: DOUBLE (predicted posted wait in minutes)
- prediction_method: VARCHAR

**entities** — Ride/attraction metadata
- entity_code: VARCHAR
- entity_name: VARCHAR
- short_name: VARCHAR
- park_code: VARCHAR
- category: VARCHAR
- has_wait_times: BOOLEAN
- wait_time_type: VARCHAR ('STANDBY', etc.)
- is_extinct: BOOLEAN

**live_waits** — Real-time wait observations (last ~7 days)
- entity_code: VARCHAR
- observed_at: TIMESTAMPTZ
- wait_time_type: VARCHAR
- wait_time_minutes: INTEGER
- park_date: DATE

## Park Code Reference
- MK = Magic Kingdom (Walt Disney World)
- EP = EPCOT (Walt Disney World)
- HS = Hollywood Studios (Walt Disney World)
- AK = Animal Kingdom (Walt Disney World)
- DL = Disneyland (California)
- CA = Disney California Adventure
- UF = Universal Studios Florida
- IA = Islands of Adventure
- EU = Epic Universe
- UH = Universal Studios Hollywood
- TDL = Tokyo Disneyland
- TDS = Tokyo DisneySea

## WTI Interpretation
- ≤12: Well below average — best day to visit
- 13-18: Below average — great day to visit
- 19-25: Typical day — moderate waits
- 26-34: Above average — plan strategically
- 35-42: Well above average — arrive early
- 43-50: Very high — consider another day
- 50+: Extreme — plan carefully or reschedule

## Guidelines
- Today's date is {today}.
- Use the `run_query` tool to query the database. Always use read-only queries (SELECT only).
- When comparing dates, show WTI values and explain what they mean.
- For "best day to visit" questions, query WTI and sort by lowest.
- For ride-specific questions, join forecasts with entities.
- Keep answers concise and helpful — these are Discord messages (max ~1800 chars).
- Use emoji sparingly for readability.
- If you don't have data for something, say so honestly.
- Don't fabricate data. Only report what the database returns.
- NEVER show raw SQL to users. Just show the results naturally.
- Round wait times to whole numbers.
- This is a one-shot interaction — don't ask follow-up questions like "Would you like me to check X?"
  Instead, proactively include that info (e.g., if they ask about a busy day, also show nearby less-busy alternatives).
- If a query returns an error about locks or connectivity, just say "Data is updating right now — try again in a minute!" Don't expose database internals or error messages to users.
- Never mention databases, SQL, DuckDB, queries, or technical infrastructure in your response.
- If asked about data sources, say: "Our data comes from TouringPlans.com (historical wait times), Queue-Times.com (live waits), and official park sources (hours & events)."
- You CANNOT create visuals, charts, graphs, or images. Don't mention that you can't — just provide the data in text form naturally.
- If a user asks you to build a full touring plan / itinerary (ride order, time-by-time schedule, optimized plan),
  give general advice (best times, what to prioritize) but recommend TouringPlans.com for detailed custom plans:
  "For a full optimized touring plan, check out [TouringPlans.com](https://touringplans.com) — they're the best in the business for that!"
  You can still answer specific questions like "what's the best time to ride X" or "which rides have the shortest waits."
"""

# Usage tracking (simple JSON file)
USAGE_FILE = Path("/home/wilma/theme-park-crowd-report/tpcr-discord-bot/ask_usage.json")
QUESTION_LOG = Path("/home/wilma/theme-park-crowd-report/tpcr-discord-bot/ask_questions.jsonl")


def _load_usage() -> dict:
    if USAGE_FILE.exists():
        return json.loads(USAGE_FILE.read_text())
    return {}


def _save_usage(data: dict):
    USAGE_FILE.write_text(json.dumps(data, indent=2))


def track_usage(user_id: str) -> tuple[int, int]:
    """Track usage and return (used_this_month, limit). Returns (-1, -1) if no limit."""
    data = _load_usage()
    month_key = date.today().strftime("%Y-%m")

    if month_key not in data:
        data[month_key] = {}

    user_key = str(user_id)
    count = data[month_key].get(user_key, 0) + 1
    data[month_key][user_key] = count
    _save_usage(data)

    return count, -1  # No limit for now (free launch)


def log_question(user_id: str, username: str, question: str, answer: str, duration_ms: int):
    """Append question + answer to JSONL log for analysis."""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "user_id": str(user_id),
        "username": username,
        "question": question,
        "answer": answer[:2000],
        "duration_ms": duration_ms,
    }
    with open(QUESTION_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def run_duckdb_query(sql: str, max_retries: int = 3) -> str:
    """Execute a read-only DuckDB query and return results as string."""
    import time

    for attempt in range(max_retries):
        try:
            con = duckdb.connect(DUCKDB_PATH, read_only=True)
            result = con.execute(sql).fetchall()
            columns = [desc[0] for desc in con.description]
            con.close()

            if not result:
                return "No results found."

            # Format as readable text (not full table — keep it compact)
            lines = [" | ".join(columns)]
            lines.append("-" * len(lines[0]))
            for row in result[:50]:  # Cap at 50 rows
                lines.append(" | ".join(str(v) for v in row))

            if len(result) > 50:
                lines.append(f"... ({len(result)} total rows, showing first 50)")

            return "\n".join(lines)
        except Exception as e:
            error_str = str(e).lower()
            if ("lock" in error_str or "busy" in error_str) and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))  # Back off: 2s, 4s, 6s
                continue
            return f"Query error: {str(e)}"

    return "Database is temporarily busy. Please try again in a minute."


async def ask_agent(question: str, user_id: str, api_key: str, username: str = "unknown") -> str:
    """
    Process a natural language question about theme park data.
    Uses Claude Haiku with DuckDB tool access.
    """
    # Track usage
    used, limit = track_usage(user_id)

    import time as _time
    _start = _time.monotonic()

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = SCHEMA_CONTEXT.format(today=date.today().isoformat())

    tools = [
        {
            "name": "run_query",
            "description": "Execute a read-only SQL query against the TPCR DuckDB database. Use SELECT statements only. Returns results as formatted text.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL SELECT query to execute"
                    }
                },
                "required": ["sql"]
            }
        }
    ]

    messages = [{"role": "user", "content": question}]

    # Allow up to 5 tool-use rounds
    for _ in range(5):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        # Check if we need to handle tool use
        if response.stop_reason == "tool_use":
            # Process all tool calls
            tool_results = []
            assistant_content = response.content

            for block in response.content:
                if block.type == "tool_use":
                    sql = block.input.get("sql", "")

                    # Safety: reject non-SELECT queries
                    sql_upper = sql.strip().upper()
                    if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
                        result = "Error: Only SELECT queries are allowed."
                    else:
                        result = run_duckdb_query(sql)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})
        else:
            # Final text response
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            answer = "\n".join(text_parts)

            # Trim if too long for Discord
            if len(answer) > 1900:
                answer = answer[:1900] + "..."

            duration_ms = int((_time.monotonic() - _start) * 1000)
            log_question(user_id, username, question, answer, duration_ms)
            return answer

    fallback = "I wasn't able to fully answer that question. Try rephrasing or asking something more specific!"
    duration_ms = int((_time.monotonic() - _start) * 1000)
    log_question(user_id, username, question, fallback, duration_ms)
    return fallback
