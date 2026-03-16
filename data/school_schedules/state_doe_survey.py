#!/usr/bin/env python3
"""
Survey all 50 states for centralized school calendar databases.
"""
import json
import time
import requests
import os

BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "BSAEB_N4ZkM3WOQN6bokdPKGkL6HWuN")

STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California",
    "Colorado", "Connecticut", "Delaware", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
    "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
    "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
    "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming"
]

# Pre-known results
KNOWN = {
    "Alaska": {
        "tier": "GOLD",
        "url": "https://education.alaska.gov/DOE_Rolodex/SchoolCalendar/Home/Districts",
        "description": "Full per-district calendar portal with day-by-day codes (O=opens, C=closes, V=vacation, H=holiday, I=inservice). All districts listed with IDs.",
        "format": "Structured HTML per district",
        "verified": True
    },
    "Utah": {
        "tier": "GOLD",
        "url": "https://schools.utah.gov/schoolcalendars/2526DistrictCalendar.pdf",
        "description": "Single PDF with all districts: opening, first day, fall recess, thanksgiving, winter break, spring break, last day, plus links to full calendars.",
        "format": "PDF table",
        "verified": True
    }
}

def brave_search(query, count=5):
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"}
    params = {"q": query, "count": count}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [{
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", "")
        } for r in data.get("web", {}).get("results", [])]
    except Exception as e:
        print(f"  Search error: {e}")
        return []

def survey_state(state):
    if state in KNOWN:
        print(f"  ✅ Pre-known: {KNOWN[state]['tier']}")
        return KNOWN[state]
    
    # Search queries
    queries = [
        f'"{state} department of education" school district calendar 2025-2026',
        f'site:*.gov "{state}" school calendar all districts 2025-2026',
    ]
    
    all_results = []
    for q in queries:
        results = brave_search(q, count=5)
        all_results.extend(results)
        time.sleep(0.5)
    
    # Analyze results
    tier = "NONE"
    best_url = None
    best_desc = None
    
    for r in all_results:
        url = r["url"].lower()
        title = r["title"].lower()
        desc = r["description"].lower()
        combined = f"{title} {desc} {url}"
        
        # Look for centralized calendar indicators
        is_gov = ".gov" in url or ".state." in url or "education" in url
        has_calendar = "calendar" in combined
        has_districts = "district" in combined and ("all" in combined or "calendar" in combined)
        
        if is_gov and has_calendar:
            if any(kw in combined for kw in ["all districts", "district calendar", "school calendar database", "school calendars"]):
                if "pdf" in url or "spreadsheet" in combined or "download" in combined:
                    tier = "GOLD"
                    best_url = r["url"]
                    best_desc = f"{r['title']} — {r['description'][:200]}"
                    break
                else:
                    if tier != "GOLD":
                        tier = "SILVER"
                        best_url = r["url"]
                        best_desc = f"{r['title']} — {r['description'][:200]}"
            elif tier == "NONE":
                tier = "BRONZE"
                best_url = r["url"]
                best_desc = f"{r['title']} — {r['description'][:200]}"
    
    return {
        "tier": tier,
        "url": best_url,
        "description": best_desc,
        "format": "unknown",
        "verified": False,
        "search_results": len(all_results),
        "top_results": [{"title": r["title"], "url": r["url"]} for r in all_results[:5]]
    }

def main():
    print("=" * 60)
    print("🔍 50-STATE DOE CALENDAR SURVEY")
    print("=" * 60)
    
    results = {}
    
    for i, state in enumerate(STATES):
        print(f"\n[{i+1}/50] {state}")
        result = survey_state(state)
        results[state] = result
        icon = {"GOLD": "🥇", "SILVER": "🥈", "BRONZE": "🥉", "NONE": "⬜"}.get(result["tier"], "?")
        print(f"  {icon} {result['tier']}: {result.get('url', 'none')[:80] if result.get('url') else 'none'}")
        
        if state not in KNOWN:
            time.sleep(1)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    
    tiers = {"GOLD": [], "SILVER": [], "BRONZE": [], "NONE": []}
    for state, data in results.items():
        tiers[data["tier"]].append(state)
    
    for tier in ["GOLD", "SILVER", "BRONZE", "NONE"]:
        icon = {"GOLD": "🥇", "SILVER": "🥈", "BRONZE": "🥉", "NONE": "⬜"}[tier]
        print(f"\n{icon} {tier} ({len(tiers[tier])} states):")
        for s in tiers[tier]:
            url = results[s].get("url", "none")
            print(f"  {s}: {url[:80] if url else 'none'}")
    
    # Save
    output = {
        "survey_date": "2026-03-15",
        "total_states": 50,
        "gold": len(tiers["GOLD"]),
        "silver": len(tiers["SILVER"]),
        "bronze": len(tiers["BRONZE"]),
        "none": len(tiers["NONE"]),
        "states": results
    }
    
    with open("state_doe_calendar_survey.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nSaved to state_doe_calendar_survey.json")

if __name__ == "__main__":
    main()
