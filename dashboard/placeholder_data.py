"""
Placeholder data for ad hoc visual design testing of the stream dashboard.

When PLACEHOLDER_DATA=true, the API serves this synthetic data instead of
pipeline output. Real data paths and logic are unchanged; this module is
only used when the env flag is set.

Design spec (underlying concept; API returns aggregated/current views):
- Per day, per standby attraction: 200–300 posted waits (~15 min spacing, occasional gaps),
  5–40 actual, 200–300 predicted actual to fill gaps.
- Per priority attraction: 200–300 priority queue times (minutes until return).
- Future dates: predictions for posted/actual/priority.
"""

from __future__ import annotations

import os
import random
from datetime import date, datetime, timedelta
from typing import Any

# Reproducible for design testing
_SEED = 42

# Static park/property lists (same shape as real API)
PROPERTIES = [
    {"code": "wdw", "name": "Disney World"},
    {"code": "dlr", "name": "Disneyland Resort"},
    {"code": "uor", "name": "Universal Orlando"},
    {"code": "ush", "name": "Universal Hollywood"},
    {"code": "tdr", "name": "Tokyo Disneyland Resort"},
]

PARKS = [
    {"code": "mk", "name": "Magic Kingdom", "property_code": "wdw"},
    {"code": "ep", "name": "EPCOT", "property_code": "wdw"},
    {"code": "hs", "name": "Hollywood Studios", "property_code": "wdw"},
    {"code": "ak", "name": "Animal Kingdom", "property_code": "wdw"},
    {"code": "dl", "name": "Disneyland", "property_code": "dlr"},
    {"code": "ca", "name": "California Adventure", "property_code": "dlr"},
    {"code": "ioa", "name": "Islands of Adventure", "property_code": "uor"},
    {"code": "usf", "name": "Universal Studios Florida", "property_code": "uor"},
    {"code": "eu", "name": "Epic Universe", "property_code": "uor"},
    {"code": "ush", "name": "Universal Studios Hollywood", "property_code": "ush"},
    {"code": "tdl", "name": "Tokyo Disneyland", "property_code": "tdr"},
    {"code": "tds", "name": "Tokyo DisneySea", "property_code": "tdr"},
]

# Per-park sample entities (standby + a few priority) for wait-times list and names
ENTITY_SAMPLES: dict[str, list[tuple[str, str]]] = {
    "mk": [("MK01", "Space Mountain"), ("MK02", "Buzz Lightyear"), ("MK07", "Space Mountain LL"), ("MK08", "Buzz LL")],
    "ep": [("EP01", "Spaceship Earth"), ("EP02", "Test Track"), ("EP08", "Soarin' LL"), ("EP10", "Test Track LL")],
    "hs": [("HS01", "Tower of Terror"), ("HS02", "Rock 'n' Roller"), ("HS06", "Tower LL"), ("HS09", "RnR LL")],
    "ak": [("AK01", "Kilimanjaro Safaris"), ("AK03", "Expedition Everest"), ("AK02", "Safaris LL"), ("AK06", "Everest LL")],
    "dl": [("DL01", "Space Mountain"), ("DL02", "Big Thunder"), ("DL04", "Space LL"), ("DL06", "Big Thunder LL")],
    "ca": [("CA01", "Radiator Springs"), ("CA02", "Incredicoaster"), ("CA07", "Radiator LL"), ("CA10", "Incredicoaster LL")],
    "ioa": [("IA01", "Hagrid's"), ("IA02", "VelociCoaster"), ("IA06", "Hagrid's LL"), ("IA09", "VelociCoaster LL")],
    "usf": [("UF01", "Harry Potter"), ("UF02", "Mummy"), ("UF71", "Diagon Alley")],
    "eu": [("EU01", "Dark Universe"), ("EU02", "How to Train Your Dragon")],
    "ush": [("USH01", "Studio Tour"), ("USH02", "Secret Life of Pets")],
    "tdl": [("TDL01", "Big Thunder"), ("TDL02", "Splash Mountain"), ("TDL13", "Big Thunder FP"), ("TDL16", "Splash FP")],
    "tds": [("TDS01", "Tower of Terror"), ("TDS02", "Toy Story Mania"), ("TDS11", "Tower FP"), ("TDS16", "Toy Story FP")],
}


def _random(lo: float, hi: float) -> float:
    return lo + (hi - lo) * random.random()


def _seed_for_date(d: date) -> None:
    """Seed RNG by date so same date gives same curve shape."""
    random.seed(_SEED + d.toordinal())


def get_placeholder_properties() -> list[dict[str, Any]]:
    return list(PROPERTIES)


def get_placeholder_parks(property_code: str | None = None) -> list[dict[str, Any]]:
    if not property_code or property_code.lower() == "all":
        return list(PARKS)
    return [p for p in PARKS if (p.get("property_code") or "").lower() == property_code.lower()]


def get_placeholder_entities(park_code: str) -> list[dict[str, Any]]:
    code = park_code.lower()
    entities = ENTITY_SAMPLES.get(code, ENTITY_SAMPLES.get("mk", []))
    return [
        {"entity_code": ec, "entity_name": name, "park_code": code.upper()[:2]}
        for ec, name in entities
    ]


def get_placeholder_wait_times(park_code: str, limit: int = 20) -> list[dict[str, Any]]:
    """Current snapshot: 15–20 entities with posted wait minutes (design: 200–300 posted per day, ~15 min; here we show a snapshot)."""
    random.seed(_SEED)
    code = park_code.lower()
    entities = ENTITY_SAMPLES.get(code, ENTITY_SAMPLES.get("mk", []))
    now = datetime.now().isoformat()
    results = []
    for ec, name in entities[: max(limit, 18)]:
        # 10–80 min range for visual variety
        wait_minutes = int(_random(10, 80))
        results.append({
            "entity_code": ec,
            "entity_name": name,
            "wait_minutes": wait_minutes,
            "observed_at": now,
        })
    results.sort(key=lambda x: x["wait_minutes"], reverse=True)
    return results[: limit]


def get_placeholder_stats(park_code: str) -> dict[str, Any]:
    """Stats derived from placeholder wait times + synthetic WTI."""
    random.seed(_SEED)
    waits = get_placeholder_wait_times(park_code, limit=25)
    wait_values = [w["wait_minutes"] for w in waits if w.get("wait_minutes") is not None]
    avg_wait = round(sum(wait_values) / len(wait_values), 1) if wait_values else 22.0
    wti = round(_random(15, 35), 1)
    return {
        "park_code": park_code,
        "date": date.today().isoformat(),
        "avg_wait": avg_wait,
        "best_time": "2 PM",
        "wti": wti,
    }


def _daily_curve_time_slots() -> list[str]:
    """Park day 06:00–02:00 next day, 5-min slots (240 slots). Occasional gaps for temporary closures."""
    slots = []
    for h in range(6, 26):  # 06:00 through 02:00 next day (25:55 = 01:55)
        hour = h % 24
        for m in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
            if h >= 24 and m > 55:
                break
            slots.append(f"{hour:02d}:{m:02d}")
    return slots[: 240]


def get_placeholder_daily_curve(
    park_code: str,
    start_date: date,
    end_date: date,
    entity_code: str | None = None,
) -> list[dict[str, Any]]:
    """
    Daily curve: 200–300 time_slot points (design: posted ~15 min, gaps for closures;
    actual 5–40; predicted actual fills gaps). Here we return ~240 slots with realistic shape.
    """
    slots = _daily_curve_time_slots()
    _seed_for_date(start_date)
    # Realistic shape: low morning, peak midday, drop evening (index 0–239 maps to 06:00–01:55)
    curve = []
    gap_indices = set(random.sample(range(len(slots)), min(4, len(slots) // 20)))  # 4 gaps
    for i, ts in enumerate(slots):
        if i in gap_indices:
            continue  # Simulate temporary closure gap
        # Peak around slot 60–100 (roughly 11:00–14:00)
        t = i / len(slots)
        peak = 0.35 + 0.15 * (1 - 4 * (t - 0.35) ** 2) if 0.2 < t < 0.5 else 0
        base = 12 + 8 * (1 - t)
        avg_wait = base + peak * 25 + _random(-3, 3)
        avg_wait = max(5, min(55, avg_wait))
        curve.append({"time_slot": ts, "avg_wait": round(avg_wait, 1)})
    return curve


def get_placeholder_crowd_level(park_code: str, target_date: date) -> dict[str, Any]:
    """Crowd level 1–10 and WTI from placeholder stats."""
    random.seed(_SEED + target_date.toordinal())
    wti = round(_random(15, 35), 1)
    level = min(10, max(1, int(1 + (wti - 10) / 3)))
    return {
        "park_code": park_code,
        "park_date": target_date.isoformat(),
        "crowd_level": level,
        "wti_minutes": wti,
        "wti_min": round(wti - 5, 1),
        "wti_max": round(wti + 8, 1),
        "n_entities": 12,
        "vs_yesterday_pct": round(_random(-10, 10), 1),
    }


def get_placeholder_forecast(park_code: str, days: int = 7) -> list[dict[str, Any]]:
    """Future dates: predictions for WTI / crowd level."""
    random.seed(_SEED)
    result = []
    for i in range(days):
        d = date.today() + timedelta(days=i)
        wti = round(_random(14, 36), 1)
        level = min(10, max(1, int(1 + (wti - 10) / 3))) if wti else None
        result.append({
            "date": d.isoformat(),
            "crowd_level": level,
            "wti_minutes": wti,
        })
    return result


def get_placeholder_tip(park_code: str) -> str | None:
    """One pro tip from first entity."""
    code = park_code.lower()
    entities = ENTITY_SAMPLES.get(code, ENTITY_SAMPLES.get("mk", []))
    if not entities:
        return None
    name = entities[0][1]
    return f"{name} typically drops to 25 min around 2 PM. Set a reminder to check back then!"
