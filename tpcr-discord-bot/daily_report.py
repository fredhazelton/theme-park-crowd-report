"""
Daily Crowd Report — Posts to #crowd-reports every morning.
Run via cron at 7:00 AM EST.
"""

import os
import requests
import duckdb
from datetime import date
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"))

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CROWD_REPORTS_CHANNEL = "1471935476238651432"  # #crowd-reports
DUCKDB_PATH = "/mnt/data/pipeline/tpcr_live.duckdb"
WTI_PATH = "/mnt/data/pipeline/wti/wti.parquet"
_USE_DUCKDB = os.path.exists(DUCKDB_PATH)

HEADERS = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json",
}

# WTI code mapping (TDL and TDS now have their own WTI scores)
WTI_CODE_MAP = {}


def wti_emoji(wti: float) -> str:
    if wti <= 12: return "❄️"
    elif wti <= 18: return "💎"
    elif wti <= 25: return "⚪"
    elif wti <= 34: return "🌸"
    elif wti <= 42: return "🔥"
    elif wti <= 50: return "🔴"
    else: return "💀"


def wti_label(wti: float) -> str:
    if wti <= 12: return "Shortest waits"
    elif wti <= 18: return "Short waits"
    elif wti <= 25: return "Typical day"
    elif wti <= 34: return "Above average"
    elif wti <= 42: return "Long waits"
    elif wti <= 50: return "Very long waits"
    else: return "Extreme"


def get_embed_color(wti: float) -> int:
    if wti <= 12: return 0x0A2F8F
    elif wti <= 18: return 0x3C78D2
    elif wti <= 25: return 0xD2C8DC
    elif wti <= 34: return 0xFFB1C9
    elif wti <= 42: return 0xEB427B
    elif wti <= 50: return 0xA60038
    else: return 0x50001E


def get_wti(park_code: str, target_date: date) -> float:
    wti_code = WTI_CODE_MAP.get(park_code, park_code)
    try:
        if _USE_DUCKDB:
            con = duckdb.connect(DUCKDB_PATH, read_only=True)
            r = con.execute("SELECT wti FROM wti WHERE park_code = ? AND park_date = ? LIMIT 1",
                           [wti_code, target_date]).fetchone()
            con.close()
            return float(r[0]) if r else None
        r = duckdb.sql(f"""
            SELECT wti FROM read_parquet('{WTI_PATH}')
            WHERE park_code = '{wti_code}' AND park_date = '{target_date}'
            LIMIT 1
        """).fetchone()
        return float(r[0]) if r else None
    except:
        return None


def main():
    today = date.today()
    date_display = today.strftime("%A, %B %d, %Y")

    park_groups = [
        ("🏰 Walt Disney World", [
            ("MK", "Magic Kingdom"), ("EP", "EPCOT"),
            ("HS", "Hollywood Studios"), ("AK", "Animal Kingdom"),
        ]),
        ("🎠 Disneyland Resort", [
            ("DL", "Disneyland"), ("CA", "California Adventure"),
        ]),
        ("🦈 Universal Orlando", [
            ("UF", "Universal Studios Florida"), ("IA", "Islands of Adventure"),
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

    fields = []
    best_picks = []

    for group_name, parks in park_groups:
        lines = []
        group_best_park = None
        group_best_wti = 999
        for park_code, park_name in parks:
            wti = get_wti(park_code, today)
            if wti is not None:
                emoji = wti_emoji(wti)
                label = wti_label(wti)
                lines.append(f"{emoji} **{park_name}** — WTI {wti:.0f} (*{label}*)")
                if wti < group_best_wti:
                    group_best_wti = wti
                    group_best_park = park_name
            else:
                lines.append(f"⬜ **{park_name}** — No data")
        if lines:
            fields.append({"name": group_name, "value": "\n".join(lines), "inline": False})
        if group_best_park and len(parks) > 1:
            best_picks.append((group_name, group_best_park, group_best_wti))

    if best_picks:
        picks_text = "\n".join(f"⭐ **{park}** (WTI {wti:.0f})" for _, park, wti in best_picks)
        fields.append({"name": "Best picks by resort", "value": picks_text, "inline": False})

    # --- Accuracy & Bias Correction section ---
    accuracy_path = "/home/wilma/hazeydata/pipeline/accuracy/accuracy_summary.json"
    try:
        import json
        with open(accuracy_path) as f:
            acc = json.load(f)
        
        lines = []
        
        # Entity-level MAE
        entity_mae = acc.get("overall_mae")
        if entity_mae is not None:
            dates_eval = acc.get("dates_evaluated", 0)
            lines.append(f"🎯 Entity MAE: **{entity_mae:.1f} min** ({dates_eval} days evaluated)")
        
        # WTI-level accuracy
        wti_mae = acc.get("wti_mae")
        wti_bias = acc.get("wti_bias")
        if wti_mae is not None:
            wti_dates = acc.get("wti_dates_evaluated", 0)
            lines.append(f"📊 WTI MAE: **{wti_mae:.1f}** | Bias: **{wti_bias:+.1f}** ({wti_dates} days)")
        
        # Bias correction applied
        # Read from latest pipeline log
        import glob
        log_files = sorted(glob.glob("/home/wilma/hazeydata/pipeline/logs/calculate_wti_simple_*.log"))
        if log_files:
            with open(log_files[-1]) as lf:
                for line in lf:
                    if "Bias correction applied" in line:
                        # Extract the correction value
                        correction_str = line.split("applied:")[1].strip().split(" ")[0]
                        lines.append(f"⚖️ Bias correction: **{correction_str} WTI points**")
                        break
        
        if lines:
            fields.append({
                "name": "📈 Forecast Accuracy",
                "value": "\n".join(lines),
                "inline": False
            })
    except Exception as e:
        print(f"⚠️ Accuracy section skipped: {e}")

    embed = {
        "title": f"📊 Daily Wait Time Report — {date_display}",
        "color": get_embed_color(best_picks[0][2]) if best_picks else 0xD2C8DC,
        "fields": fields,
        "footer": {"text": "Updated daily at 7 AM EST  •  Use /crowd [park] for details  •  hazeydata.ai"},
    }

    payload = {"embeds": [embed]}

    r = requests.post(
        f"https://discord.com/api/v10/channels/{CROWD_REPORTS_CHANNEL}/messages",
        headers=HEADERS, json=payload
    )

    if r.ok:
        print(f"✅ Daily report posted to #crowd-reports for {today}")
    else:
        print(f"❌ Failed: {r.status_code} {r.text[:200]}")


if __name__ == "__main__":
    main()
