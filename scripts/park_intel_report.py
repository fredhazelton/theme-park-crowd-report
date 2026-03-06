#!/usr/bin/env python3
"""
Park Intel Report — Daily WTI intelligence feed for Discord.

Posts a formatted report to #park-intel with:
  1. Today's WTI forecasts for all parks
  2. Yesterday's actuals vs seasonal norms
  3. Extreme conditions flags
  4. Week-ahead outlook with best/worst days

Usage:
    python3 park_intel_report.py              # print report to stdout
    python3 park_intel_report.py --post       # print + post to Discord
    python3 park_intel_report.py --dry-run    # just print, don't post (default)
"""

import sys
import json
import os
from datetime import date, timedelta, datetime

import duckdb

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WTI_PARQUET = "/mnt/data/pipeline/wti/wti.parquet"

# Park codes to always ignore (water parks, etc.)
IGNORE_PARKS = {"BB"}  # BB = Blizzard Beach

PARK_NAMES = {
    "MK":  "Magic Kingdom",
    "EP":  "EPCOT",
    "HS":  "Hollywood Studios",
    "AK":  "Animal Kingdom",
    "DL":  "Disneyland",
    "CA":  "California Adventure",
    "IA":  "Islands of Adventure",
    "UF":  "Universal Florida",
    "EU":  "Epic Universe",
    "UH":  "Universal Hollywood",
    "TDL": "Tokyo Disneyland",
    "TDS": "Tokyo DisneySea",
}

# Ordered groups for display
PARK_GROUPS = {
    "🏰 Walt Disney World": ["MK", "EP", "HS", "AK"],
    "🎆 Disneyland Resort": ["DL", "CA"],
    "🦖 Universal": ["UF", "IA", "EU", "UH"],
    "🌍 International": ["TDL", "TDS"],
}

# Benedictus color-scale emoji thresholds
WTI_THRESHOLDS = [
    (10, "❄️"),   # ghost town
    (20, "💎"),   # low
    (30, "⚪"),   # moderate
    (40, "🌸"),   # busy
    (50, "🔥"),   # packed
    (60, "🔴"),   # extreme
    (999, "💀"),  # apocalyptic
]

# How many std devs above/below mean to flag as extreme
EXTREME_SIGMA = 1.5


def wti_emoji(wti: float) -> str:
    """Return the crowd-level emoji for a WTI value."""
    for threshold, emoji in WTI_THRESHOLDS:
        if wti < threshold:
            return emoji
    return "💀"


def wti_label(wti: float) -> str:
    """Human-readable crowd level."""
    if wti < 10:
        return "Ghost Town"
    elif wti < 20:
        return "Low"
    elif wti < 30:
        return "Moderate"
    elif wti < 40:
        return "Busy"
    elif wti < 50:
        return "Packed"
    elif wti < 60:
        return "Extreme"
    else:
        return "Apocalyptic"


def short_name(code: str) -> str:
    return PARK_NAMES.get(code, code)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(today: date):
    """Load all needed data from WTI parquet using DuckDB."""
    con = duckdb.connect()

    yesterday = today - timedelta(days=1)
    week_end = today + timedelta(days=7)

    # Today's forecasts (first forecast date available)
    # The forecast horizon starts after the last historical date.
    # Find the first forecast date >= today
    first_forecast = con.execute(f"""
        SELECT min(park_date)::DATE
        FROM '{WTI_PARQUET}'
        WHERE source = 'forecast' AND park_date >= '{today}'
    """).fetchone()[0]

    # Today's actuals (if available, historical for today)
    today_historical = {}
    rows = con.execute(f"""
        SELECT park_code, wti
        FROM '{WTI_PARQUET}'
        WHERE park_date = '{today}' AND source = 'historical'
          AND park_code != 'BB'
        ORDER BY park_code
    """).fetchall()
    for code, wti in rows:
        today_historical[code] = wti

    # Yesterday's actuals
    yesterday_actuals = {}
    rows = con.execute(f"""
        SELECT park_code, wti
        FROM '{WTI_PARQUET}'
        WHERE park_date = '{yesterday}' AND source = 'historical'
          AND park_code != 'BB'
        ORDER BY park_code
    """).fetchall()
    for code, wti in rows:
        yesterday_actuals[code] = wti

    # Today's forecast (the nearest forecast date)
    today_forecast = {}
    if first_forecast:
        rows = con.execute(f"""
            SELECT park_code, wti
            FROM '{WTI_PARQUET}'
            WHERE park_date = '{first_forecast}' AND source = 'forecast'
              AND park_code != 'BB'
            ORDER BY park_code
        """).fetchall()
        for code, wti in rows:
            today_forecast[code] = wti

    # Week-ahead forecasts (next 7 days from first_forecast)
    week_forecasts = {}  # {date_str: {park_code: wti}}
    if first_forecast:
        wk_end = first_forecast + timedelta(days=7)
        rows = con.execute(f"""
            SELECT park_code, park_date::DATE as pd, wti
            FROM '{WTI_PARQUET}'
            WHERE source = 'forecast'
              AND park_date >= '{first_forecast}'
              AND park_date < '{wk_end}'
              AND park_code != 'BB'
            ORDER BY park_date, park_code
        """).fetchall()
        for code, pd, wti in rows:
            d = str(pd)
            if d not in week_forecasts:
                week_forecasts[d] = {}
            week_forecasts[d][code] = wti

    # Historical stats per park (for normals / extremes)
    park_stats = {}  # {code: (mean, std)}
    rows = con.execute(f"""
        SELECT park_code, avg(wti), stddev(wti)
        FROM '{WTI_PARQUET}'
        WHERE source = 'historical' AND park_code != 'BB'
        GROUP BY park_code
    """).fetchall()
    for code, mean, std in rows:
        park_stats[code] = (mean, std)

    # Same-week historical averages (for seasonal context)
    # Use ±7 days around today's day-of-year across all years
    doy = today.timetuple().tm_yday
    seasonal_avg = {}
    rows = con.execute(f"""
        SELECT park_code, avg(wti) as avg_wti
        FROM '{WTI_PARQUET}'
        WHERE source = 'historical'
          AND park_code != 'BB'
          AND abs(dayofyear(park_date) - {doy}) <= 7
        GROUP BY park_code
    """).fetchall()
    for code, avg_wti in rows:
        seasonal_avg[code] = avg_wti

    con.close()

    return {
        "first_forecast_date": first_forecast,
        "today_historical": today_historical,
        "yesterday_actuals": yesterday_actuals,
        "today_forecast": today_forecast,
        "week_forecasts": week_forecasts,
        "park_stats": park_stats,
        "seasonal_avg": seasonal_avg,
    }


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report(today: date, data: dict) -> list[str]:
    """Build the report as a list of Discord message chunks (≤2000 chars each)."""

    first_fc = data["first_forecast_date"]
    today_fc = data["today_forecast"]
    today_hist = data["today_historical"]
    yesterday = data["yesterday_actuals"]
    week_fc = data["week_forecasts"]
    stats = data["park_stats"]
    seasonal = data["seasonal_avg"]

    day_name = today.strftime("%A")
    date_str = today.strftime("%B %-d, %Y")

    sections = []

    # ── Header ──
    header = f"# 🎢 Park Intel Report — {day_name}, {date_str}\n"
    sections.append(header)

    # ── Section 1: Today's Forecast ──
    if today_fc:
        fc_date = first_fc.strftime("%a %-m/%-d") if first_fc != today else "Today"
        avg_wti = sum(today_fc.values()) / len(today_fc) if today_fc else 0

        s = f"## 📡 {'Todays' if first_fc == today else 'Next'} Forecast — {fc_date}\n"
        s += f"*Avg WTI across all parks: **{avg_wti:.1f}** {wti_emoji(avg_wti)} {wti_label(avg_wti)}*\n\n"

        for group_name, codes in PARK_GROUPS.items():
            park_lines = []
            for c in codes:
                if c in today_fc:
                    wti = today_fc[c]
                    em = wti_emoji(wti)
                    vs_seasonal = ""
                    if c in seasonal:
                        diff = wti - seasonal[c]
                        arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
                        vs_seasonal = f" ({arrow}{abs(diff):.1f} vs norm)"
                    park_lines.append(f"{em} **{short_name(c)}** — {wti:.1f}{vs_seasonal}")
            if park_lines:
                s += f"**{group_name}**\n"
                s += "\n".join(park_lines) + "\n\n"
        sections.append(s)

    # ── Section 2: Yesterday's Actuals ──
    if yesterday:
        y_date = (today - timedelta(days=1)).strftime("%a %-m/%-d")
        avg_y = sum(yesterday.values()) / len(yesterday)

        s = f"## 📊 Yesterday's Actuals — {y_date}\n"
        s += f"*Avg WTI: **{avg_y:.1f}** {wti_emoji(avg_y)}*\n\n"

        # Show each park with comparison to seasonal norm
        lines = []
        for c in sorted(yesterday.keys(), key=lambda x: yesterday[x], reverse=True):
            wti = yesterday[c]
            em = wti_emoji(wti)
            vs = ""
            if c in seasonal:
                diff = wti - seasonal[c]
                if abs(diff) >= 2:
                    arrow = "📈" if diff > 0 else "📉"
                    vs = f" {arrow} {abs(diff):.1f} vs seasonal"
            lines.append(f"{em} **{c}** {wti:.1f}{vs}")

        s += " · ".join(lines) + "\n"
        sections.append(s)

    # ── Section 3: Extreme Conditions ──
    # Check forecast values against historical norms
    check_data = today_fc if today_fc else today_hist
    if check_data and stats:
        extremes_high = []
        extremes_low = []

        for code, wti in check_data.items():
            if code in stats:
                mean, std = stats[code]
                if std > 0:
                    z = (wti - mean) / std
                    if z >= EXTREME_SIGMA:
                        extremes_high.append((code, wti, z))
                    elif z <= -EXTREME_SIGMA:
                        extremes_low.append((code, wti, z))

        if extremes_high or extremes_low:
            s = "## ⚠️ Extreme Conditions\n"
            if extremes_high:
                for code, wti, z in sorted(extremes_high, key=lambda x: -x[2]):
                    s += f"🔴 **{short_name(code)}** — WTI {wti:.1f} ({z:+.1f}σ above normal)\n"
            if extremes_low:
                for code, wti, z in sorted(extremes_low, key=lambda x: x[2]):
                    s += f"❄️ **{short_name(code)}** — WTI {wti:.1f} ({z:+.1f}σ below normal)\n"
            s += "\n"
            sections.append(s)

    # ── Section 4: Week Ahead Outlook ──
    if week_fc:
        sorted_dates = sorted(week_fc.keys())

        s = "## 🗓️ Week Ahead Outlook\n"

        # Find best and worst days across all parks
        day_avgs = {}
        for d in sorted_dates:
            parks = week_fc[d]
            day_avgs[d] = sum(parks.values()) / len(parks) if parks else 0

        best_day = min(day_avgs, key=day_avgs.get)
        worst_day = max(day_avgs, key=day_avgs.get)

        best_dt = datetime.strptime(best_day, "%Y-%m-%d")
        worst_dt = datetime.strptime(worst_day, "%Y-%m-%d")

        s += f"✅ **Best day:** {best_dt.strftime('%A %-m/%-d')} — avg WTI {day_avgs[best_day]:.1f} {wti_emoji(day_avgs[best_day])}\n"
        s += f"❌ **Worst day:** {worst_dt.strftime('%A %-m/%-d')} — avg WTI {day_avgs[worst_day]:.1f} {wti_emoji(day_avgs[worst_day])}\n\n"

        # Compact daily summary
        for d in sorted_dates:
            dt = datetime.strptime(d, "%Y-%m-%d")
            avg = day_avgs[d]
            em = wti_emoji(avg)

            # Find the park with highest and lowest WTI that day
            parks = week_fc[d]
            if parks:
                hot_park = max(parks, key=parks.get)
                cold_park = min(parks, key=parks.get)
                day_label = dt.strftime("%a %-m/%-d")
                marker = ""
                if d == best_day:
                    marker = " ← best"
                elif d == worst_day:
                    marker = " ← worst"
                s += (
                    f"{em} **{day_label}** avg {avg:.1f}"
                    f" · 🔺 {hot_park} {parks[hot_park]:.0f}"
                    f" · 🔻 {cold_park} {parks[cold_park]:.0f}"
                    f"{marker}\n"
                )

        sections.append(s)

    # ── Footer ──
    sections.append(
        f"\n-# 🤖 Generated {datetime.now().strftime('%H:%M')} ET"
        f" · WTI scale: ❄️<10 💎<20 ⚪<30 🌸<40 🔥<50 🔴<60 💀60+"
    )

    # Combine into chunks ≤ 2000 chars for Discord
    chunks = []
    current = ""
    for section in sections:
        if len(current) + len(section) > 1950:
            chunks.append(current.strip())
            current = section
        else:
            current += section
    if current.strip():
        chunks.append(current.strip())

    return chunks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    today = date.today()
    post = "--post" in sys.argv

    print(f"[park-intel] Loading data for {today}...")
    data = load_data(today)

    print(f"[park-intel] Building report...")
    chunks = format_report(today, data)

    # Always print to stdout
    for i, chunk in enumerate(chunks):
        print(f"\n{'='*60}")
        print(f"  Message {i+1}/{len(chunks)} ({len(chunk)} chars)")
        print(f"{'='*60}")
        print(chunk)

    if post:
        print(f"\n[park-intel] Posting {len(chunks)} message(s) to Discord...")
        # Write chunks to a temp file for the posting mechanism
        output_path = "/tmp/park_intel_report.json"
        with open(output_path, "w") as f:
            json.dump({"chunks": chunks, "generated": datetime.now().isoformat()}, f)
        print(f"[park-intel] Report saved to {output_path}")
        print("[park-intel] Done! Use Clawdbot message tool to post.")
    else:
        print("\n[park-intel] Dry run complete. Use --post to save for Discord posting.")


if __name__ == "__main__":
    main()
