#!/usr/bin/env python3
"""Generate the MK 7-day chart image for the hazeydata.ai landing page.
Uses the same forecast_image module as the Discord bot."""

import sys
sys.path.insert(0, '/home/wilma/tpcr-discord-bot')

from forecast_image import generate_7day_image
from datetime import date, timedelta
import duckdb

OUTPUT_PATH = '/home/wilma/hazeydata.ai/assets/mk-7day.png'
WTI_PATH = '/mnt/data/pipeline/wti/wti.parquet'

def main():
    con = duckdb.connect()
    today = date.today()
    tomorrow = today + timedelta(days=1)
    end = today + timedelta(days=7)

    rows = con.execute(f"""
        SELECT park_date, wti, n_entities
        FROM '{WTI_PATH}'
        WHERE park_code = 'MK'
          AND park_date >= '{tomorrow}'
          AND park_date <= '{end}'
        ORDER BY park_date
    """).fetchall()

    if not rows:
        print("No MK WTI data found, skipping chart generation")
        return

    days_data = []
    for row in rows:
        park_date, wti, n_ent = row
        days_data.append({
            'date': park_date,
            'wti_low': max(5, wti - 5),
            'wti_avg': wti,
            'wti_high': wti + 5,
        })

    buf = generate_7day_image('Magic Kingdom', days_data)
    with open(OUTPUT_PATH, 'wb') as f:
        f.write(buf.read())
    print(f"Landing page chart saved: {OUTPUT_PATH} ({len(days_data)} days)")
    con.close()

if __name__ == '__main__':
    main()
