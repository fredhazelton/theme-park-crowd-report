#!/usr/bin/env python3
"""
generate_weekly_blog.py — Automated weekly blog post generator for hazeydata.ai

Generates data-driven "This Week" articles for Orlando and Disneyland regions
using live WTI forecast data from DuckDB.

Usage:
    python3 generate_weekly_blog.py --region orlando [--week-of 2026-03-18] [--dry-run]
    python3 generate_weekly_blog.py --region disneyland [--week-of 2026-03-13] [--dry-run]
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

import duckdb

# ── Config ────────────────────────────────────────────────────────────────────

DUCKDB_PATH = "/home/wilma/hazeydata/pipeline/tpcr_live.duckdb"
BLOG_DIR = Path("/home/wilma/hazeydata.ai/theme-park-crowd-report/blog")
BLOG_INDEX = BLOG_DIR / "index.html"
HAZEYDATA_REPO = Path("/home/wilma/hazeydata.ai")

PARK_NAMES = {
    "MK": "Magic Kingdom",
    "EP": "EPCOT",
    "HS": "Hollywood Studios",
    "AK": "Animal Kingdom",
    "UF": "Universal Studios Florida",
    "IA": "Islands of Adventure",
    "EU": "Epic Universe",
    "DL": "Disneyland",
    "CA": "Disney California Adventure",
    "UH": "Universal Studios Hollywood",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
}

# Short names for nav links
PARK_SHORT_NAMES = {
    "MK": "Magic Kingdom",
    "EP": "EPCOT",
    "HS": "Hollywood Studios",
    "AK": "Animal Kingdom",
    "UF": "Universal Studios FL",
    "IA": "Islands of Adventure",
    "EU": "Epic Universe",
    "DL": "Disneyland",
    "CA": "California Adventure",
    "UH": "Universal Hollywood",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
}

REGION_CONFIG = {
    "orlando": {
        "parks": ["MK", "EP", "HS", "AK", "UF", "IA", "EU"],
        "title_prefix": "Orlando Theme Parks This Week",
        "default_weekday": 0,  # Monday
        "meta_tags": ["Weekly Outlook", "WTI"],
        "region_tags": ["Orlando"],
        "description_template": "Your data-driven guide to Orlando theme park crowds for {date_range}. Park-by-park WTI forecasts, best days to visit, and practical advice.",
        "author_sig": 'Written by the <a href="https://hazeydata.ai/theme-park-crowd-report/">Theme Park Crowd Report</a> team — data-driven crowd forecasts for 12 parks across Walt Disney World, Universal Orlando, and more.',
    },
    "disneyland": {
        "parks": ["DL", "CA", "UH"],
        "title_prefix": "Disneyland Resort This Week",
        "default_weekday": 3,  # Thursday
        "meta_tags": ["Weekly Outlook", "WTI"],
        "region_tags": ["Disneyland", "Southern California"],
        "description_template": "Your data-driven guide to Disneyland and Southern California theme park crowds for {date_range}. Park-by-park WTI forecasts, best days to visit, and practical advice.",
        "author_sig": 'Written by the <a href="https://hazeydata.ai/theme-park-crowd-report/">Theme Park Crowd Report</a> team — data-driven crowd forecasts covering Disneyland Resort and Universal Studios Hollywood.',
    },
    "tokyo": {
        "parks": ["TDL", "TDS"],
        "title_prefix": "Tokyo Disney Resort This Week",
        "default_weekday": 1,  # Tuesday
        "meta_tags": ["Weekly Outlook", "WTI"],
        "region_tags": ["Tokyo Disney Resort", "Japan"],
        "description_template": "Your data-driven guide to Tokyo Disney Resort crowds for {date_range}. Park-by-park WTI forecasts, best days to visit, and practical advice.",
        "author_sig": 'Written by the <a href="https://hazeydata.ai/theme-park-crowd-report/">Theme Park Crowd Report</a> team — data-driven crowd forecasts for 12 parks worldwide, including Tokyo Disney Resort.',
    },
}


# ── Crowd Level Labels ────────────────────────────────────────────────────────

def crowd_label(wti: float) -> str:
    """Convert WTI value to human-readable crowd level."""
    if wti < 10:
        return "Very Light"
    elif wti < 15:
        return "Light"
    elif wti < 20:
        return "Moderate"
    elif wti < 25:
        return "Busy"
    elif wti < 30:
        return "Very Busy"
    else:
        return "Extreme"


def crowd_css_class(wti: float, is_min: bool = False, is_max: bool = False) -> str:
    """Return CSS class for WTI cell — light for lightest, peak for busiest."""
    if is_min:
        return "light"
    if is_max:
        return "peak"
    return ""


# ── Date Helpers ──────────────────────────────────────────────────────────────

def next_weekday(dt: datetime.date, weekday: int) -> datetime.date:
    """Find the next occurrence of a given weekday (0=Mon, 6=Sun).
    If today IS that weekday, return today (article covers this week)."""
    days_ahead = weekday - dt.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return dt + datetime.timedelta(days=days_ahead)


def format_date_range(start: datetime.date, end: datetime.date) -> str:
    """Format date range like 'March 18–24, 2026'."""
    if start.month == end.month:
        return f"{start.strftime('%B')} {start.day}–{end.day}, {start.year}"
    else:
        return f"{start.strftime('%B')} {start.day} – {end.strftime('%B')} {end.day}, {start.year}"


def format_date_short(dt: datetime.date) -> str:
    """Format like 'March 18, 2026'."""
    return dt.strftime("%B %-d, %Y")


def format_day_of_week(dt: datetime.date) -> str:
    """Format like 'Wednesday, March 18'."""
    return dt.strftime("%A, %B %-d")


def slug_date(dt: datetime.date) -> str:
    """Format date for filename: 'march-18-2026'."""
    return dt.strftime("%B-%-d-%Y").lower()


# ── Data Layer ────────────────────────────────────────────────────────────────

def fetch_wti_data(park_codes: list, start_date: datetime.date, end_date: datetime.date) -> dict:
    """
    Fetch WTI data from DuckDB, falling back to parquet if DB is locked.
    
    Returns: {park_code: {date: wti_value, ...}, ...}
    """
    try:
        con = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            result = con.execute(
                """
                SELECT park_code, park_date, wti
                FROM wti
                WHERE time_slot = 'daily'
                  AND park_code IN (SELECT UNNEST(?::VARCHAR[]))
                  AND park_date BETWEEN ? AND ?
                ORDER BY park_code, park_date
                """,
                [park_codes, start_date, end_date],
            ).fetchall()
        finally:
            con.close()
    except Exception:
        # DuckDB locked by queue-times collector — read from parquet directly
        parquet_path = Path(DUCKDB_PATH).parent / "wti" / "wti_v3.parquet"
        con = duckdb.connect(":memory:")
        try:
            codes_list = ", ".join(f"'{c}'" for c in park_codes)
            result = con.execute(
                f"""
                SELECT park_code, park_date, wti
                FROM read_parquet('{parquet_path}')
                WHERE park_code IN ({codes_list})
                  AND park_date BETWEEN '{start_date}' AND '{end_date}'
                ORDER BY park_code, park_date
                """,
            ).fetchall()
        finally:
            con.close()

    data = {}
    for park_code, park_date, wti in result:
        if park_code not in data:
            data[park_code] = {}
        data[park_code][park_date] = round(wti, 1)

    return data


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyze_parks(wti_data: dict, park_codes: list) -> dict:
    """
    Analyze WTI data and produce all the insights needed for the article.
    
    Returns a dict with:
        - park_summaries: [{park_code, name, min_wti, max_wti, avg_wti, best_day, best_wti, worst_day, worst_wti, range_str, verdict}, ...]
        - best_days: [{park_code, name, day, wti}, ...]
        - lightest_park: {name, avg_wti, range_str}
        - busiest_park: {name, avg_wti, range_str}
        - biggest_swing: {name, swing, min_wti, max_wti, min_day, max_day}
        - overall_avg: float
    """
    park_summaries = []
    best_days = []

    for code in park_codes:
        if code not in wti_data or not wti_data[code]:
            continue

        daily = wti_data[code]
        values = list(daily.values())
        dates = list(daily.keys())
        avg_wti = round(sum(values) / len(values), 1)
        min_wti = min(values)
        max_wti = max(values)
        min_idx = values.index(min_wti)
        max_idx = values.index(max_wti)
        best_day = dates[min_idx]
        worst_day = dates[max_idx]
        swing = round(max_wti - min_wti, 1)

        # Build WTI range string
        if min_wti == max_wti:
            range_str = f"{min_wti:.0f}"
        else:
            range_str = f"{min_wti:.0f}–{max_wti:.0f}"

        # Generate verdict
        verdict = _generate_verdict(code, avg_wti, min_wti, max_wti, swing)

        park_summaries.append({
            "park_code": code,
            "name": PARK_NAMES[code],
            "min_wti": min_wti,
            "max_wti": max_wti,
            "avg_wti": avg_wti,
            "best_day": best_day,
            "best_wti": min_wti,
            "worst_day": worst_day,
            "worst_wti": max_wti,
            "range_str": range_str,
            "verdict": verdict,
            "swing": swing,
            "daily": daily,
        })

        best_days.append({
            "park_code": code,
            "name": PARK_NAMES[code],
            "day": best_day,
            "wti": min_wti,
        })

    # Sort summaries lightest to busiest by average WTI
    park_summaries.sort(key=lambda x: x["avg_wti"])

    # Sort best_days by WTI ascending
    best_days.sort(key=lambda x: x["wti"])

    # Identify standout parks
    lightest = park_summaries[0] if park_summaries else None
    busiest = park_summaries[-1] if park_summaries else None

    # Find biggest day-to-day swing
    biggest_swing_park = max(park_summaries, key=lambda x: x["swing"]) if park_summaries else None

    overall_avg = round(sum(p["avg_wti"] for p in park_summaries) / len(park_summaries), 1) if park_summaries else 0

    return {
        "park_summaries": park_summaries,
        "best_days": best_days,
        "lightest_park": lightest,
        "busiest_park": busiest,
        "biggest_swing": biggest_swing_park,
        "overall_avg": overall_avg,
    }


def _generate_verdict(code: str, avg_wti: float, min_wti: float, max_wti: float, swing: float) -> str:
    """Generate a short verdict string for the overview table."""
    label = crowd_label(avg_wti)

    if swing >= 8:
        return "Highly variable — pick your day"
    elif avg_wti < 10:
        return "Walk-on territory"
    elif avg_wti < 13:
        return "Very manageable"
    elif avg_wti < 17:
        return "Light crowds expected"
    elif avg_wti < 20:
        return "Moderate — plan your must-dos"
    elif avg_wti < 23:
        return "Busy but workable"
    elif avg_wti < 27:
        return "Consistently busy"
    elif avg_wti < 30:
        return "Very busy all week"
    else:
        return "Packed — brace yourself"


# ── Article Content Generation ────────────────────────────────────────────────

def _overall_vibe(analysis: dict) -> str:
    """One-word overall vibe for the week."""
    avg = analysis["overall_avg"]
    if avg < 12:
        return "light"
    elif avg < 18:
        return "moderate"
    elif avg < 24:
        return "busy"
    else:
        return "very busy"


def generate_article_body(region: str, analysis: dict, start_date: datetime.date, end_date: datetime.date) -> str:
    """Generate the article HTML body content (everything inside <article>)."""
    config = REGION_CONFIG[region]
    date_range = format_date_range(start_date, end_date)
    summaries = analysis["park_summaries"]
    lightest = analysis["lightest_park"]
    busiest = analysis["busiest_park"]
    biggest_swing = analysis["biggest_swing"]
    vibe = _overall_vibe(analysis)

    parts = []

    # ── Opening paragraph ──
    parts.append(_generate_opening(region, analysis, start_date, end_date, vibe))

    # ── Big Picture Table ──
    parts.append(f'\n            <h3>The Big Picture: Where Should You Go?</h3>\n')
    parts.append(_generate_overview_paragraph(region, analysis))
    parts.append(_generate_overview_table(summaries))

    # ── The Big Story ──
    parts.append(_generate_big_story(region, analysis, start_date, end_date))

    # ── Park-by-Park Breakdown ──
    parts.append(_generate_park_breakdown(region, analysis, start_date, end_date))

    # ── Best Day Table ──
    parts.append(_generate_best_day_section(analysis, start_date, end_date))

    # ── Practical Advice ──
    parts.append(_generate_practical_advice(region, analysis, start_date))

    # ── CTA ──
    parts.append("""
            <div class="blog-cta-box">
                <p><strong>Get daily WTI forecasts for all 12 parks.</strong> Just type <code>/today</code> or <code>/crowd</code> in the Discord — free during beta.</p>
                <a href="https://discord.gg/2Estr7sbP7" class="btn btn-primary" target="_blank" style="margin-top: 0.5rem;">Join the Discord — It's Free</a>
            </div>""")

    # ── Author sig ──
    parts.append(f'\n            <p class="author-sig">{config["author_sig"]}</p>')

    return "\n".join(parts)


def _generate_opening(region: str, analysis: dict, start_date: datetime.date, end_date: datetime.date, vibe: str) -> str:
    """Generate the opening paragraph(s) — sets the tone for the article."""
    lightest = analysis["lightest_park"]
    busiest = analysis["busiest_park"]
    overall_avg = analysis["overall_avg"]
    date_range = format_date_range(start_date, end_date)

    # Determine seasonal context
    month = start_date.month
    day = start_date.day

    season_hook = _get_season_hook(start_date)

    if region == "orlando":
        spread = round(busiest["avg_wti"] - lightest["avg_wti"], 1)
        opening = f"""
            <p>{season_hook} But not all parks are created equal — the gap between the lightest and busiest park in Orlando this week is {spread:.0f} WTI points. That's the difference between walking onto rides and waiting over an hour.</p>

            <p>Here's your park-by-park breakdown for the week of {date_range}, based on our Wait Time Index forecasts.</p>"""
    else:  # disneyland
        opening = f"""
            <p>{season_hook} Here's what the data says about crowds at Disneyland, California Adventure, and Universal Studios Hollywood for {date_range}.</p>

            <p>The short version: {lightest["name"]} is your best bet this week (avg WTI {lightest["avg_wti"]:.1f}), while {busiest["name"]} runs the busiest. But the day you go matters almost as much as which park.</p>"""

    return opening


def _get_season_hook(start_date: datetime.date) -> str:
    """Return a seasonal/contextual opening sentence based on the date."""
    month = start_date.month
    day = start_date.day

    # Spring Break (roughly mid-Feb through mid-April)
    if (month == 2 and day >= 15) or month == 3 or (month == 4 and day <= 20):
        hooks = [
            "Spring break season rolls on, and the crowds reflect it.",
            "Another week of spring break, another week of split crowds across the parks.",
            "Spring break continues to dominate the crowd picture this week.",
            "We're deep into spring break territory, but the data shows clear winners and losers.",
        ]
        # Pick based on week number for deterministic variety
        week_num = start_date.isocalendar()[1]
        return hooks[week_num % len(hooks)]

    # Summer (May-August)
    elif month >= 5 and month <= 8:
        if month == 5 and day < 25:
            return "The pre-summer lull is one of the best-kept secrets in theme parks."
        elif month == 5:
            return "Memorial Day weekend kicks off the summer season."
        elif month == 6:
            return "Summer crowds are settling into their pattern."
        elif month == 7:
            return "Peak summer is here, and the parks are feeling it."
        else:
            return "August means back-to-school season is starting to thin the crowds."

    # Fall (Sep-Nov)
    elif month >= 9 and month <= 11:
        if month == 9:
            return "Post-Labor Day means lighter crowds are finally here."
        elif month == 10:
            return "Fall is festival season, and event overlays are shifting the crowd picture."
        else:
            return "The holiday season is approaching, but we're in a sweet spot right now."

    # Holiday/Winter (Dec-Feb)
    else:
        if month == 12 and day >= 20:
            return "The holiday week is one of the busiest of the year — but some parks handle it better."
        elif month == 12:
            return "December crowds are building toward the holiday peak."
        elif month == 1:
            return "January is traditionally one of the lightest months — let's see what the data says."
        else:
            return "February is a tale of two halves: quiet weekdays, busy holiday weekends."


def _generate_overview_paragraph(region: str, analysis: dict) -> str:
    """Short paragraph before the overview table."""
    lightest = analysis["lightest_park"]
    busiest = analysis["busiest_park"]

    if region == "orlando":
        return f"""
            <p>If you're in Orlando this week and have any flexibility, the WTI data makes the choice pretty clear:</p>
"""
    else:
        return f"""
            <p>Here's how the three parks stack up this week:</p>
"""


def _generate_overview_table(summaries: list) -> str:
    """Generate the overview WTI table sorted lightest to busiest."""
    lightest_avg = summaries[0]["avg_wti"] if summaries else 0
    busiest_avg = summaries[-1]["avg_wti"] if summaries else 0

    rows = []
    for i, s in enumerate(summaries):
        is_lightest = (i == 0)
        is_busiest = (i == len(summaries) - 1)

        range_cls = ""
        verdict_cls = ""
        if is_lightest:
            range_cls = ' class="light"'
            verdict_cls = ' class="light"'
        elif is_busiest:
            range_cls = ' class="peak"'
            verdict_cls = ' class="peak"'

        rows.append(f"""                    <tr>
                        <td>{s["name"]}</td>
                        <td{range_cls}>{s["range_str"]}</td>
                        <td{verdict_cls}>{s["verdict"]}</td>
                    </tr>""")

    return f"""            <table class="wti-table">
                <thead>
                    <tr>
                        <th>Park</th>
                        <th>WTI Range This Week</th>
                        <th>Verdict</th>
                    </tr>
                </thead>
                <tbody>
{chr(10).join(rows)}
                </tbody>
            </table>
"""


def _generate_big_story(region: str, analysis: dict, start_date: datetime.date, end_date: datetime.date) -> str:
    """Generate the 'big story' section — the most interesting data point of the week."""
    lightest = analysis["lightest_park"]
    busiest = analysis["busiest_park"]
    biggest_swing = analysis["biggest_swing"]

    parts = []

    spread = round(busiest["avg_wti"] - lightest["avg_wti"], 1)

    # Determine what the big story is
    # Priority: 1) Huge spread between parks, 2) A surprisingly light park, 3) A wildcard swing park

    if spread >= 15:
        # Massive spread — lead with the contrast
        parts.append(f"""
            <h3>The Story: {lightest["name"]} vs. {busiest["name"]}</h3>

            <p>The headline this week is the gap between parks. <strong>{busiest["name"]} is running WTI values around {busiest["avg_wti"]:.0f}</strong> — solidly {crowd_label(busiest["avg_wti"]).lower()} — while <strong>{lightest["name"]} is forecasting an average WTI of just {lightest["avg_wti"]:.1f}.</strong> That's {crowd_label(lightest["avg_wti"]).lower()} territory.</p>

            <p>If you have flexibility in which park you visit, the math here is straightforward. {lightest["name"]} will give you a dramatically better experience this week.</p>""")

    elif lightest["avg_wti"] < 12:
        # Surprisingly light park
        parts.append(f"""
            <h3>The Surprise: {lightest["name"]} Is Quiet</h3>

            <p>{lightest["name"]} is the clear winner this week, with WTI values in the {lightest["range_str"]} range. That's {crowd_label(lightest["avg_wti"]).lower()} — you'll walk onto most rides, and even headliners should be reasonable.</p>

            <p>Meanwhile, {busiest["name"]} sits at the other end with WTI {busiest["range_str"]} ({crowd_label(busiest["avg_wti"]).lower()}). The contrast is stark.</p>""")

    elif biggest_swing and biggest_swing["swing"] >= 8:
        # A park with huge day-to-day variation
        parts.append(f"""
            <h3>The Wildcard: {biggest_swing["name"]}</h3>

            <p>{biggest_swing["name"]} is the most variable park this week, swinging from WTI {biggest_swing["min_wti"]:.1f} to {biggest_swing["max_wti"]:.1f} — a {biggest_swing["swing"]:.0f}-point range. That's the difference between {crowd_label(biggest_swing["min_wti"]).lower()} and {crowd_label(biggest_swing["max_wti"]).lower()}. Your day choice here matters more than at any other park.</p>

            <p>Best day: <strong>{format_day_of_week(biggest_swing["best_day"])}</strong> (WTI {biggest_swing["min_wti"]:.1f}). Worst: <strong>{format_day_of_week(biggest_swing["worst_day"])}</strong> (WTI {biggest_swing["max_wti"]:.1f}).</p>""")

    else:
        # Generic lead — focus on overall picture
        vibe = _overall_vibe(analysis)
        parts.append(f"""
            <h3>The Big Picture</h3>

            <p>Overall, it's a {vibe} week across the board. {busiest["name"]} runs busiest (WTI {busiest["range_str"]}), while {lightest["name"]} is your best bet (WTI {lightest["range_str"]}). The spread isn't dramatic, but your day choice still matters.</p>""")

    return "\n".join(parts)


def _generate_park_breakdown(region: str, analysis: dict, start_date: datetime.date, end_date: datetime.date) -> str:
    """Generate the park-by-park detailed breakdown."""
    summaries = analysis["park_summaries"]
    parts = []

    if region == "orlando":
        # Group into Disney parks and Universal parks
        disney_parks = [s for s in summaries if s["park_code"] in ("MK", "EP", "HS", "AK")]
        universal_parks = [s for s in summaries if s["park_code"] in ("UF", "IA", "EU")]

        if disney_parks:
            disney_avg = round(sum(p["avg_wti"] for p in disney_parks) / len(disney_parks), 1)
            disney_label = crowd_label(disney_avg).lower()
            parts.append(f"""
            <h3>Walt Disney World: {crowd_label(disney_avg)} Overall</h3>

            <p>Across the four WDW parks, the average WTI this week is {disney_avg:.1f} — {disney_label}. Here's the breakdown:</p>
""")
            for p in sorted(disney_parks, key=lambda x: x["avg_wti"], reverse=True):
                parts.append(_format_park_detail(p))

        if universal_parks:
            uni_avg = round(sum(p["avg_wti"] for p in universal_parks) / len(universal_parks), 1)
            uni_label = crowd_label(uni_avg).lower()
            parts.append(f"""
            <h3>Universal Orlando: {crowd_label(uni_avg)} Overall</h3>
""")
            for p in sorted(universal_parks, key=lambda x: x["avg_wti"], reverse=True):
                parts.append(_format_park_detail(p))

    else:
        # Disneyland — just go park by park
        parts.append(f"""
            <h3>Park-by-Park Breakdown</h3>
""")
        for p in sorted(summaries, key=lambda x: x["avg_wti"], reverse=True):
            parts.append(_format_park_detail(p))

    return "\n".join(parts)


def _format_park_detail(park: dict) -> str:
    """Format a single park's detail paragraph."""
    code = park["park_code"]
    name = park["name"]
    avg = park["avg_wti"]
    min_wti = park["min_wti"]
    max_wti = park["max_wti"]
    best_day = park["best_day"]
    worst_day = park["worst_day"]
    swing = park["swing"]
    label = crowd_label(avg).lower()

    # Build contextual commentary based on the data
    if swing >= 6:
        day_advice = f" There's a {swing:.0f}-point swing between the best and worst days — target <strong>{format_day_of_week(best_day)}</strong> (WTI {min_wti:.1f}) over {format_day_of_week(worst_day)} (WTI {max_wti:.1f}) if you can."
    elif swing >= 3:
        day_advice = f" {format_day_of_week(best_day)} is your best bet (WTI {min_wti:.1f}) — a meaningful improvement over the rest of the week."
    else:
        day_advice = f" Crowds are consistent all week, so your day choice doesn't matter much here."

    if avg < 12:
        mood = "This is walk-on territory for most rides."
    elif avg < 16:
        mood = "You'll have a great day with minimal planning."
    elif avg < 20:
        mood = "Plan your headliners and you'll be fine."
    elif avg < 25:
        mood = "Come with a strategy — Lightning Lane or rope drop will pay off."
    elif avg < 30:
        mood = "It's going to be a test of patience. Prioritize ruthlessly."
    else:
        mood = "Expect long waits everywhere. Only go if you have to."

    return f"""            <p><strong>{name} (WTI {min_wti:.0f}–{max_wti:.0f}):</strong> {mood}{day_advice}</p>
"""


def _generate_best_day_section(analysis: dict, start_date: datetime.date, end_date: datetime.date) -> str:
    """Generate the Best Day at Each Park table and surrounding text."""
    best_days = analysis["best_days"]
    summaries = analysis["park_summaries"]

    # Find the min and max WTI across all best days
    all_best_wtis = [b["wti"] for b in best_days]
    min_best = min(all_best_wtis) if all_best_wtis else 0
    max_best = max(all_best_wtis) if all_best_wtis else 0

    rows = []
    for b in sorted(best_days, key=lambda x: x["wti"]):
        wti_cls = ""
        if b["wti"] == min_best:
            wti_cls = ' class="light"'
        elif b["wti"] == max_best:
            wti_cls = ' class="peak"'

        rows.append(f"""                    <tr>
                        <td>{b["name"]}</td>
                        <td>{format_day_of_week(b["day"])}</td>
                        <td{wti_cls}>{b["wti"]:.1f}</td>
                    </tr>""")

    # Determine the best overall day of the week
    day_totals = {}
    for s in summaries:
        for date, wti in s["daily"].items():
            if date not in day_totals:
                day_totals[date] = []
            day_totals[date].append(wti)

    best_overall_date = None
    best_overall_avg = float("inf")
    for date, wtis in day_totals.items():
        avg = sum(wtis) / len(wtis)
        if avg < best_overall_avg:
            best_overall_avg = avg
            best_overall_date = date

    comment = ""
    if best_overall_date:
        comment = f"""
            <p><strong>{format_day_of_week(best_overall_date)}</strong> shapes up as the best overall day across parks (average WTI {best_overall_avg:.1f}). If you're picking one day this week, that's your answer.</p>"""

    return f"""
            <h3>Best Day at Each Park</h3>

            <p>If you can pick your day, here are the lowest-WTI days at each park:</p>

            <table class="wti-table">
                <thead>
                    <tr>
                        <th>Park</th>
                        <th>Best Day</th>
                        <th>WTI</th>
                    </tr>
                </thead>
                <tbody>
{chr(10).join(rows)}
                </tbody>
            </table>
{comment}"""


def _generate_practical_advice(region: str, analysis: dict, start_date: datetime.date) -> str:
    """Generate the practical takeaway section."""
    lightest = analysis["lightest_park"]
    busiest = analysis["busiest_park"]
    biggest_swing = analysis["biggest_swing"]
    overall_avg = analysis["overall_avg"]

    parts = []
    parts.append("""
            <h3>The Takeaway</h3>
""")

    tips = []

    # Tip 1: Best park choice
    if lightest["avg_wti"] < 15:
        tips.append(f'<strong>{lightest["name"]}</strong> is the standout this week — {crowd_label(lightest["avg_wti"]).lower()} crowds mean shorter waits across the board.')
    else:
        tips.append(f'<strong>{lightest["name"]}</strong> is your lightest option this week (WTI {lightest["range_str"]}), though no park is truly empty.')

    # Tip 2: Avoid or manage the busiest
    if busiest["avg_wti"] >= 25:
        tips.append(f'<strong>{busiest["name"]}</strong> is the park to avoid if possible (WTI {busiest["range_str"]}). If you must go, arrive at rope drop and prioritize your top 2–3 rides.')
    else:
        tips.append(f'Even the busiest park ({busiest["name"]}, WTI {busiest["range_str"]}) is manageable with a plan.')

    # Tip 3: Day flexibility
    if biggest_swing and biggest_swing["swing"] >= 5:
        tips.append(f'Day choice matters most at <strong>{biggest_swing["name"]}</strong> — there\'s a {biggest_swing["swing"]:.0f}-point WTI swing between best and worst days.')

    # Tip 4: General advice
    if overall_avg >= 20:
        tips.append("This is a week where rope drop and Lightning Lane / Express Pass really pay off. Don't wing it.")
    elif overall_avg >= 15:
        tips.append("Moderate crowds mean you can be flexible, but a loose plan will still save you time on headliners.")
    else:
        tips.append("Light crowds mean you can be spontaneous. Enjoy the rare luxury of not needing a strict plan.")

    tips.append("The data updates daily. Check the Discord for tomorrow's numbers if your plans are still flexible.")

    # Build HTML list
    tip_html = "\n".join(f"                <li>{t}</li>" for t in tips)
    parts.append(f"""            <ul>
{tip_html}
            </ul>
""")

    return "\n".join(parts)


# ── HTML Template ─────────────────────────────────────────────────────────────

def generate_full_html(region: str, analysis: dict, start_date: datetime.date, end_date: datetime.date, prev_post: dict = None) -> str:
    """Generate the complete HTML page."""
    config = REGION_CONFIG[region]
    date_range = format_date_range(start_date, end_date)
    title = f"{config['title_prefix']}: {date_range}"
    meta_date = format_date_short(start_date)
    slug = f"{region}-this-week-{slug_date(start_date)}"
    filename = f"{slug}.html"
    url = f"https://hazeydata.ai/theme-park-crowd-report/blog/{filename}"
    description = config["description_template"].format(date_range=date_range)
    cache_bust = start_date.strftime("%Y%m%d")

    # Tags
    all_tags = config["meta_tags"] + config["region_tags"]
    tags_html = "\n                ".join(f'<span class="tag">{t}</span>' for t in all_tags)

    # Article body
    body = generate_article_body(region, analysis, start_date, end_date)

    # Prev/Next navigation
    nav_html = _generate_nav_html(prev_post, None)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | Theme Park Crowd Report</title>
    <meta name="description" content="{description}">
    <link rel="icon" type="image/png" sizes="32x32" href="../assets/icon-32.png">
    <link rel="apple-touch-icon" sizes="180x180" href="../assets/icon-180.png">
    <meta name="theme-color" content="#0a1628">
    <link rel="canonical" href="{url}">

    <!-- Open Graph -->
    <meta property="og:type" content="article">
    <meta property="og:url" content="{url}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{description}">
    <meta property="og:image" content="https://hazeydata.ai/assets/banner.jpg">

    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:site" content="@disneystatswhiz">
    <meta name="twitter:title" content="{title}">
    <meta name="twitter:description" content="{description}">
    <meta name="twitter:image" content="https://hazeydata.ai/assets/banner.jpg">

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="../styles.css?v={cache_bust}">
    <link rel="stylesheet" href="blog.css?v={cache_bust}">
    <style>
        .wti-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1.5rem 0;
            font-size: 0.9rem;
        }}
        .wti-table th {{
            background: rgba(60, 120, 210, 0.15);
            color: var(--mid-blue);
            font-weight: 600;
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 2px solid var(--border);
        }}
        .wti-table td {{
            padding: 0.65rem 1rem;
            color: var(--text-secondary);
            border-bottom: 1px solid var(--border);
        }}
        .wti-table tr:last-child td {{
            border-bottom: none;
        }}
        .wti-table tr:hover td {{
            background: rgba(60, 120, 210, 0.05);
        }}
        .wti-table .peak {{
            color: var(--hot-pink);
            font-weight: 600;
        }}
        .wti-table .light {{
            color: #22c55e;
            font-weight: 600;
        }}
        @media (max-width: 768px) {{
            .wti-table {{
                font-size: 0.8rem;
            }}
            .wti-table th, .wti-table td {{
                padding: 0.5rem 0.6rem;
            }}
        }}
    </style>
</head>
<body>
    <section class="hero blog-hero">
        <div class="hero-bg"></div>
        <nav class="nav">
            <div class="nav-logo">
                <a href="/"><img src="../assets/icon.jpg" alt="TPCR" class="nav-icon"></a>
                <a href="/" class="nav-title">Theme Park Crowd Report</a>
            </div>
            <button class="nav-hamburger" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')" aria-label="Menu">
                <span></span><span></span><span></span>
            </button>
            <div class="nav-links">
                <a href="/">Home</a>
                <a href="/theme-park-crowd-report/blog/">Blog</a>
                <a href="https://discord.gg/2Estr7sbP7" class="btn btn-sm" target="_blank">Join Discord</a>
            </div>
        </nav>
        <div class="hero-content">
            <h1>Blog</h1>
            <p>Data-driven insights on theme park crowds, wait times, and trip planning.</p>
        </div>
    </section>

    <div class="blog-container">
        <a href="/theme-park-crowd-report/blog/" class="blog-back">← All posts</a>

        <article class="blog-post">
            <div class="blog-post-meta">
                <span>{meta_date}</span>
                {tags_html}
            </div>
            <h2>{title}</h2>
{body}
        </article>

        <!-- Prev / Next -->
{nav_html}
    </div>

    <footer class="blog-footer">
        <div class="footer-content">
            <div class="footer-brand">
                <img src="../assets/icon.jpg" alt="" class="footer-icon">
                <span>Theme Park Crowd Report</span>
            </div>
            <div class="footer-links">
                <a href="/">Home</a>
                <a href="/theme-park-crowd-report/blog/">Blog</a>
                <a href="/theme-park-crowd-report/bio.html">About</a>
                <a href="https://discord.gg/2Estr7sbP7" target="_blank">Discord</a>
                <a href="https://twitter.com/disneystatswhiz" target="_blank">Twitter</a>
                <a href="mailto:fred@hazeydata.ai">Contact</a>
            </div>
            <p class="footer-copy">© {start_date.year} hazeydata.ai</p>
        </div>
    </footer>
</body>
</html>"""


def _generate_nav_html(prev_post: dict = None, next_post: dict = None) -> str:
    """Generate prev/next navigation HTML."""
    parts = []
    parts.append('        <div class="blog-nav-arrows">')

    if prev_post:
        parts.append(f"""            <a href="/theme-park-crowd-report/blog/{prev_post['filename']}" class="blog-nav-prev">
                <span class="blog-nav-label">Previous</span>
                <span class="blog-nav-title">← {prev_post['short_title']}</span>
            </a>""")
    else:
        parts.append("            <div></div>")

    if next_post:
        parts.append(f"""            <a href="/theme-park-crowd-report/blog/{next_post['filename']}" class="blog-nav-next">
                <span class="blog-nav-label">Next</span>
                <span class="blog-nav-title">{next_post['short_title']} →</span>
            </a>""")
    else:
        parts.append("            <div></div>")

    parts.append("        </div>")
    return "\n".join(parts)


# ── Blog Index Update ─────────────────────────────────────────────────────────

def find_previous_post() -> dict:
    """Find the most recent blog post (the current newest in the index)."""
    if not BLOG_INDEX.exists():
        return None

    content = BLOG_INDEX.read_text()

    # Find the first blog-card link
    match = re.search(r'<a href="/theme-park-crowd-report/blog/([^"]+)" class="blog-card">', content)
    if not match:
        return None

    filename = match.group(1)

    # Extract the title from the h3 inside that card
    card_match = re.search(
        r'<a href="/theme-park-crowd-report/blog/' + re.escape(filename) + r'"[^>]*>.*?<h3>(.*?)</h3>',
        content,
        re.DOTALL,
    )
    title = card_match.group(1) if card_match else filename

    # Make a short title for nav
    short_title = title
    if len(short_title) > 50:
        short_title = short_title[:47] + "..."

    return {
        "filename": filename,
        "title": title,
        "short_title": short_title,
    }


def update_blog_index(region: str, start_date: datetime.date, end_date: datetime.date, analysis: dict) -> str:
    """Add the new post to the top of the blog index. Returns the updated HTML."""
    config = REGION_CONFIG[region]
    date_range = format_date_range(start_date, end_date)
    title = f"{config['title_prefix']}: {date_range}"
    meta_date = format_date_short(start_date)
    slug = f"{region}-this-week-{slug_date(start_date)}"
    filename = f"{slug}.html"

    lightest = analysis["lightest_park"]
    busiest = analysis["busiest_park"]

    # Build description/teaser
    teaser = f"Your weekly WTI forecast for {date_range}. {lightest['name']} is the lightest park (WTI {lightest['range_str']}), while {busiest['name']} runs busiest ({busiest['range_str']}). See the full breakdown."

    # Tags
    all_tags = config["meta_tags"] + config["region_tags"]
    tags_html = "\n                    ".join(f'<span class="tag">{t}</span>' for t in all_tags)

    new_card = f"""            <!-- Article — {title} -->
            <a href="/theme-park-crowd-report/blog/{filename}" class="blog-card">
                <div class="blog-card-meta">
                    <span>{meta_date}</span>
                    {tags_html}
                </div>
                <h3>{title}</h3>
                <p>{teaser}</p>
                <span class="read-more">Read article →</span>
            </a>"""

    content = BLOG_INDEX.read_text()

    # Insert after <div class="blog-list"> and before the first blog-card
    insert_marker = '<div class="blog-list">'
    if insert_marker not in content:
        print("ERROR: Could not find blog-list div in index.html", file=sys.stderr)
        return content

    # Check if this post already exists in the index
    if filename in content:
        print(f"Post {filename} already exists in index — skipping index update.", file=sys.stderr)
        return content

    content = content.replace(
        insert_marker,
        f"{insert_marker}\n{new_card}\n",
    )

    return content


def update_previous_post_nav(prev_filename: str, new_filename: str, new_short_title: str):
    """Update the previous post's HTML to add a 'Next' link to the new post."""
    prev_path = BLOG_DIR / prev_filename
    if not prev_path.exists():
        print(f"Warning: Previous post {prev_filename} not found — skipping nav update.", file=sys.stderr)
        return None

    content = prev_path.read_text()

    # Find the nav arrows section and add/update the next link
    # Pattern: look for the blog-nav-arrows div
    nav_pattern = r'(<div class="blog-nav-arrows">.*?)(</div>\s*</div>)'
    nav_match = re.search(nav_pattern, content, re.DOTALL)

    if not nav_match:
        print(f"Warning: Could not find nav arrows in {prev_filename}", file=sys.stderr)
        return None

    nav_section = nav_match.group(0)

    # Check if there's already a next link
    if 'blog-nav-next' in nav_section:
        print(f"Previous post {prev_filename} already has a next link — skipping.", file=sys.stderr)
        return content

    # Replace the empty <div></div> at the end with a next link
    next_link = f"""<a href="/theme-park-crowd-report/blog/{new_filename}" class="blog-nav-next">
                <span class="blog-nav-label">Next</span>
                <span class="blog-nav-title">{new_short_title} →</span>
            </a>"""

    # Find and replace the trailing empty div before closing </div>
    # The structure is: <div class="blog-nav-arrows"> ... <div></div> </div>
    # We need to replace the last <div></div> with our next link
    new_nav = nav_section
    # Replace the last empty div placeholder
    if '<div></div>' in new_nav:
        # Replace the last occurrence
        idx = new_nav.rfind('<div></div>')
        new_nav = new_nav[:idx] + next_link + new_nav[idx + len('<div></div>'):]

    content = content.replace(nav_section, new_nav)
    return content


# ── Git Operations ────────────────────────────────────────────────────────────

def git_commit_and_push(filename: str, region: str, date_range: str):
    """Commit the new blog post and push to remote."""
    os.chdir(HAZEYDATA_REPO)

    files_to_add = [
        f"blog/{filename}",
        "blog/index.html",
    ]

    # Also stage any modified prev post
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd=HAZEYDATA_REPO,
    )
    for line in result.stdout.strip().split("\n"):
        if line.startswith("blog/") and line.endswith(".html"):
            files_to_add.append(line)

    for f in files_to_add:
        subprocess.run(["git", "add", f], cwd=HAZEYDATA_REPO)

    commit_msg = f"blog: {region} this week {date_range}"
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=HAZEYDATA_REPO)
    subprocess.run(["git", "push"], cwd=HAZEYDATA_REPO)
    print(f"Committed and pushed: {commit_msg}")


# ── Verification ──────────────────────────────────────────────────────────────

def verify_article(html: str, wti_data: dict, analysis: dict) -> tuple[bool, list[str]]:
    """
    Cross-check every WTI number in the generated HTML against source data.
    
    Returns (passed: bool, issues: list[str])
    """
    issues = []
    
    # Build set of all valid WTI values from source data (rounded to 1 decimal)
    valid_values = set()
    for park_data in wti_data.values():
        for wti in park_data.values():
            valid_values.add(round(wti, 1))
    
    # Also add derived values from analysis (averages, ranges)
    for ps in analysis.get("park_summaries", []):
        valid_values.add(round(ps["min_wti"], 1))
        valid_values.add(round(ps["max_wti"], 1))
        valid_values.add(round(ps["avg_wti"], 1))
        valid_values.add(round(ps["best_wti"], 1))
        valid_values.add(round(ps["worst_wti"], 1))
    if "overall_avg" in analysis:
        valid_values.add(round(analysis["overall_avg"], 1))
    if "biggest_swing" in analysis and analysis["biggest_swing"]:
        valid_values.add(round(analysis["biggest_swing"]["swing"], 1))
    
    # Also add integer-rounded versions (ranges display as "31–33" etc.)
    int_values = set()
    for v in valid_values:
        int_values.add(float(int(round(v))))
    valid_values.update(int_values)
    
    # Extract all WTI-like numbers from the HTML (numbers in table cells, in text near "WTI")
    # Pattern: numbers like 12.4, 22, 33.1 that appear in td elements or near WTI mentions
    # Also match ranges like "12–14" in td cells
    td_numbers = re.findall(r'<td[^>]*>\s*(\d+(?:\.\d)?)\s*</td>', html)
    td_ranges = re.findall(r'<td[^>]*>\s*(\d+(?:\.\d)?)\s*[–—-]\s*(\d+(?:\.\d)?)\s*</td>', html)
    
    # Add range endpoints to the check list
    for lo, hi in td_ranges:
        td_numbers.extend([lo, hi])
    
    # Check each extracted number
    for num_str in td_numbers:
        val = float(num_str)
        if val > 5 and val < 50:  # WTI-range numbers
            if val not in valid_values:
                issues.append(f"WTI value {val} in table not found in source data")
    
    # Verify park count
    park_count_in_data = len([p for p in wti_data if wti_data[p]])
    park_names_in_html = len(re.findall(r'<td>(Magic Kingdom|EPCOT|Hollywood Studios|Animal Kingdom|Universal Studios Florida|Islands of Adventure|Epic Universe|Disneyland(?! Resort)|Disney California Adventure|Universal Studios Hollywood|Tokyo Disneyland|Tokyo DisneySea)</td>', html))
    
    # Each park appears in overview table + best day table = 2x
    expected_mentions = park_count_in_data * 2
    if park_names_in_html != expected_mentions:
        issues.append(f"Expected {expected_mentions} park name mentions in tables ({park_count_in_data} parks × 2 tables), found {park_names_in_html}")
    
    # Verify date range in title matches content
    title_match = re.search(r'<title>(.*?)</title>', html)
    if not title_match:
        issues.append("No <title> tag found")
    
    # Verify canonical URL exists
    if 'rel="canonical"' not in html:
        issues.append("Missing canonical URL")
    
    # Verify OG tags
    for tag in ['og:title', 'og:description', 'og:url']:
        if tag not in html:
            issues.append(f"Missing {tag} meta tag")
    
    # Verify Discord CTA exists
    if 'discord.gg' not in html:
        issues.append("Missing Discord CTA link")
    
    passed = len(issues) == 0
    return passed, issues


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate weekly blog post for hazeydata.ai")
    parser.add_argument("--region", required=True, choices=["orlando", "disneyland", "tokyo"],
                        help="Region to generate article for")
    parser.add_argument("--week-of", dest="week_of", default=None,
                        help="Start date YYYY-MM-DD (defaults to next Monday for Orlando, next Thursday for Disneyland)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Print HTML to stdout without writing files or committing")
    parser.add_argument("--verify-only", dest="verify_only", action="store_true",
                        help="Verify an existing article's numbers against source data")
    args = parser.parse_args()

    config = REGION_CONFIG[args.region]

    # Determine start date
    if args.week_of:
        start_date = datetime.date.fromisoformat(args.week_of)
    else:
        today = datetime.date.today()
        start_date = next_weekday(today, config["default_weekday"])

    end_date = start_date + datetime.timedelta(days=6)
    date_range = format_date_range(start_date, end_date)

    print(f"Generating {args.region} article for {date_range}", file=sys.stderr)

    # Fetch data
    wti_data = fetch_wti_data(config["parks"], start_date, end_date)

    # Validate we have data
    missing_parks = [p for p in config["parks"] if p not in wti_data or not wti_data[p]]
    if missing_parks:
        print(f"WARNING: No WTI data for parks: {', '.join(missing_parks)}", file=sys.stderr)

    if not wti_data:
        print("ERROR: No WTI data found for any park. Aborting.", file=sys.stderr)
        sys.exit(1)

    # Analyze
    analysis = analyze_parks(wti_data, config["parks"])

    # Find previous post for nav links
    prev_post = find_previous_post()

    # Generate HTML
    html = generate_full_html(args.region, analysis, start_date, end_date, prev_post)

    # Verify article data integrity
    passed, issues = verify_article(html, wti_data, analysis)
    if passed:
        print("✅ Verification passed: all numbers match source data", file=sys.stderr)
    else:
        print(f"⚠️  Verification found {len(issues)} issue(s):", file=sys.stderr)
        for issue in issues:
            print(f"   - {issue}", file=sys.stderr)
        if not args.dry_run and not args.verify_only:
            print("ERROR: Article failed verification. Use --dry-run to inspect. Aborting.", file=sys.stderr)
            sys.exit(1)

    slug = f"{args.region}-this-week-{slug_date(start_date)}"
    filename = f"{slug}.html"

    if args.verify_only:
        print(f"Verification {'PASSED' if passed else 'FAILED'} for {filename}", file=sys.stderr)
        sys.exit(0 if passed else 1)

    if args.dry_run:
        print(html)
        print(f"\n<!-- Filename: {filename} -->", file=sys.stderr)
        print(f"<!-- Previous post: {prev_post['filename'] if prev_post else 'None'} -->", file=sys.stderr)
        return

    # Write the article
    output_path = BLOG_DIR / filename
    output_path.write_text(html)
    print(f"Wrote: {output_path}", file=sys.stderr)

    # Update blog index
    updated_index = update_blog_index(args.region, start_date, end_date, analysis)
    BLOG_INDEX.write_text(updated_index)
    print(f"Updated: {BLOG_INDEX}", file=sys.stderr)

    # Update previous post's next link
    if prev_post:
        short_title = f"{config['title_prefix'].split(':')[0]} This Week: {date_range}"
        if len(short_title) > 50:
            short_title = f"{args.region.title()} This Week: {date_range}"

        updated_prev = update_previous_post_nav(
            prev_post["filename"],
            filename,
            short_title,
        )
        if updated_prev:
            (BLOG_DIR / prev_post["filename"]).write_text(updated_prev)
            print(f"Updated nav in: {prev_post['filename']}", file=sys.stderr)

    # Git commit and push
    git_commit_and_push(filename, args.region, date_range)


if __name__ == "__main__":
    main()
