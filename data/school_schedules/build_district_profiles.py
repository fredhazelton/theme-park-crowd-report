#!/usr/bin/env python3
"""
Build initial district profiles database from everything we've collected so far.
Every district gets a persistent record that accumulates intelligence over time.
"""
import json
import os
from datetime import datetime
from collections import defaultdict

PROFILES_FILE = "district_profiles.json"

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}

def detect_platform(url):
    """Detect the hosting platform from a URL"""
    if not url: return "unknown"
    url = url.lower()
    if "finalsite.net" in url: return "finalsite"
    if "thrillshare" in url: return "thrillshare"
    if "schoolwires" in url: return "schoolwires"
    if "core-docs.s3" in url: return "core_docs_s3"
    if "myconnectsuite" in url: return "myconnectsuite"
    if "drive.google.com" in url: return "google_drive"
    if "edl.io" in url: return "edlio"
    if "wordpress" in url or "/wp-content/" in url: return "wordpress"
    if "facebook.com" in url: return "facebook"
    if ".k12." in url: return "k12_domain"
    if ".edu" in url: return "edu_domain"
    return "other"

def main():
    print("Building district profiles database...")
    print()
    
    profiles = {}
    
    # 1. Load NCES district list (base records)
    nces = load_json("district_nces_matches.json")
    if isinstance(nces, dict):
        for nces_id, info in nces.items():
            if isinstance(info, dict):
                profiles[nces_id] = {
                    "nces_id": nces_id,
                    "name": info.get("name", ""),
                    "state": info.get("state", ""),
                    "enrollment": info.get("enrollment"),
                    "sources": [],
                    "failed_sources": [],
                    "search_strategies": {"queries_tried": [], "best_query": None},
                    "collection_history": {},
                    "state_doe_source": {"available": False},
                    "notes": []
                }
    
    print(f"  Base records from NCES: {len(profiles)}")
    
    # 2. Merge QA sweep results (records every URL tried and result)
    qa = load_json("qa_sweep_results.json")
    if isinstance(qa, dict):
        for nces_id, info in qa.items():
            if nces_id not in profiles:
                profiles[nces_id] = {
                    "nces_id": nces_id,
                    "name": info.get("name", ""),
                    "state": info.get("state", ""),
                    "enrollment": info.get("enrollment"),
                    "sources": [],
                    "failed_sources": [],
                    "search_strategies": {"queries_tried": [], "best_query": None},
                    "collection_history": {},
                    "state_doe_source": {"available": False},
                    "notes": []
                }
            
            p = profiles[nces_id]
            
            # Record the URL and what happened
            url = info.get("url", "")
            qa_status = info.get("qa_status", "")
            fetch_method = info.get("fetch_method", "")
            
            if url:
                source_record = {
                    "url": url,
                    "type": "pdf" if url.endswith(".pdf") else "html",
                    "hosting": detect_platform(url),
                    "discovered_via": fetch_method,
                    "school_year": "2025-2026",
                    "qa_status": qa_status,
                    "attempted": "2026-03-15",
                }
                
                # Check if we got useful data
                new_dates = info.get("new_dates", {})
                existing_dates = info.get("existing_dates", {})
                
                has_data = any(v for k, v in (new_dates or {}).items() 
                             if k in ['first_day', 'last_day', 'spring_break_start'] and v)
                
                if has_data:
                    source_record["quality"] = "unverified"
                    source_record["fields_extracted"] = [k for k, v in new_dates.items() if v and k != 'school_year' and k != 'confidence']
                    p["sources"].append(source_record)
                    
                    # Record the dates
                    p["collection_history"]["2025-2026"] = {
                        "dates": {k: v for k, v in new_dates.items() if k in 
                                 ['first_day', 'last_day', 'winter_break_start', 'winter_break_end', 
                                  'spring_break_start', 'spring_break_end']},
                        "source": "qa_sweep",
                        "confidence": new_dates.get("confidence", "low"),
                        "collected_date": "2026-03-15"
                    }
                else:
                    source_record["reason"] = f"qa_{qa_status}" if qa_status else "no_data"
                    p["failed_sources"].append(source_record)
            
            # Record existing (v1) data too
            if existing_dates and any(v for k, v in existing_dates.items() 
                                     if k in ['first_day', 'last_day'] and v):
                if "2025-2026" not in p["collection_history"]:
                    p["collection_history"]["2025-2026"] = {}
                p["collection_history"]["2025-2026"]["v1_dates"] = {
                    k: v for k, v in existing_dates.items() if k in 
                    ['first_day', 'last_day', 'winter_break_start', 'winter_break_end', 
                     'spring_break_start', 'spring_break_end']
                }
                p["collection_history"]["2025-2026"]["v1_source"] = existing_dates.get("source", info.get("existing_source", ""))
    
    print(f"  After QA sweep merge: {len(profiles)}")
    
    # 3. Merge state DOE collected data
    doe = load_json("state_doe_collected.json")
    if isinstance(doe, dict) and "districts" in doe:
        for d in doe["districts"]:
            state = d.get("state", "")
            name = d.get("name", "")
            
            # Find matching profile by state + name
            matched = None
            for nces_id, p in profiles.items():
                if p["state"] == state and (
                    name.lower() in p["name"].lower() or 
                    p["name"].lower() in name.lower() or
                    name.lower().replace(" county", "").replace(" city", "") == 
                    p["name"].lower().replace(" county", "").replace(" city", "").replace(" school district", "")
                ):
                    matched = nces_id
                    break
            
            if matched:
                p = profiles[matched]
            else:
                # Create new profile for state DOE districts not in NCES list
                fake_id = f"DOE_{state}_{name.replace(' ', '_')}"
                profiles[fake_id] = {
                    "nces_id": fake_id,
                    "name": name,
                    "state": state,
                    "sources": [],
                    "failed_sources": [],
                    "search_strategies": {"queries_tried": [], "best_query": None},
                    "collection_history": {},
                    "state_doe_source": {"available": False},
                    "notes": []
                }
                p = profiles[fake_id]
            
            # Mark state DOE source
            p["state_doe_source"] = {
                "available": True,
                "url": d.get("source_url", ""),
                "source_name": d.get("source", ""),
                "format": d.get("source_type", "state_doe")
            }
            
            # Record the collection
            dates = {}
            for field in ['first_day', 'last_day', 'winter_break_start', 'winter_break_end',
                         'spring_break_start', 'spring_break_end']:
                if d.get(field):
                    dates[field] = d[field]
            
            if dates:
                p["collection_history"]["2025-2026"] = {
                    "dates": dates,
                    "source": "state_doe",
                    "confidence": "high",
                    "verified_by": "state_doe",
                    "collected_date": "2026-03-15"
                }
                
                p["sources"].append({
                    "url": d.get("source_url", ""),
                    "type": "state_doe",
                    "quality": "verified",
                    "school_year": "2025-2026",
                    "first_seen": "2026-03-15"
                })
    
    # 4. Merge manual review data
    manual = load_json("manual_review_log.json")
    if isinstance(manual, dict) and "reviews" in manual:
        for r in manual["reviews"]:
            name = r.get("name", "")
            state = r.get("state", "")
            
            for nces_id, p in profiles.items():
                if p["state"] == state and name.lower() in p["name"].lower():
                    p["collection_history"]["2025-2026"] = {
                        "dates": r.get("correct_dates", {}),
                        "source": "manual_review",
                        "confidence": "verified",
                        "verified_by": "manual_review",
                        "collected_date": "2026-03-15",
                        "notes": r.get("notes", "")
                    }
                    if r.get("correct_source"):
                        p["sources"].append({
                            "url": r["correct_source"],
                            "type": "manual",
                            "quality": "verified",
                            "school_year": "2025-2026"
                        })
                    break
    
    # 5. Mark state DOE tiers for all states
    doe_survey = load_json("state_doe_calendar_survey.json")
    if isinstance(doe_survey, dict) and "states" in doe_survey:
        for state_name, info in doe_survey["states"].items():
            tier = info.get("tier", "NONE")
            # Apply to all districts in that state
            # Map state names to abbreviations
            state_abbrevs = {
                'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR',
                'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE',
                'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID',
                'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS',
                'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
                'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS',
                'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV',
                'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
                'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
                'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
                'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT',
                'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV',
                'Wisconsin': 'WI', 'Wyoming': 'WY'
            }
            abbrev = state_abbrevs.get(state_name, "")
            if abbrev:
                for nces_id, p in profiles.items():
                    if p.get("state") == abbrev:
                        p["state_doe_source"]["tier"] = tier
                        if info.get("url"):
                            p["state_doe_source"]["portal_url"] = info["url"]
    
    # Stats
    has_dates = sum(1 for p in profiles.values() if p.get("collection_history", {}).get("2025-2026", {}).get("dates"))
    has_verified = sum(1 for p in profiles.values() 
                       if p.get("collection_history", {}).get("2025-2026", {}).get("confidence") in ["high", "verified"])
    has_sources = sum(1 for p in profiles.values() if p.get("sources"))
    has_failed = sum(1 for p in profiles.values() if p.get("failed_sources"))
    has_doe = sum(1 for p in profiles.values() if p.get("state_doe_source", {}).get("available"))
    
    # Platform distribution
    platforms = defaultdict(int)
    for p in profiles.values():
        for s in p.get("sources", []) + p.get("failed_sources", []):
            platforms[s.get("hosting", "unknown")] += 1
    
    print(f"\n{'='*60}")
    print(f"DISTRICT PROFILES DATABASE")
    print(f"{'='*60}")
    print(f"  Total profiles: {len(profiles)}")
    print(f"  With 2025-2026 dates: {has_dates}")
    print(f"  High confidence/verified: {has_verified}")
    print(f"  With known source URLs: {has_sources}")
    print(f"  With failed source URLs: {has_failed}")
    print(f"  With state DOE source: {has_doe}")
    print(f"\n  Platform distribution:")
    for platform, count in sorted(platforms.items(), key=lambda x: -x[1])[:10]:
        print(f"    {platform}: {count}")
    
    # Save
    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=2, default=str)
    
    size_mb = os.path.getsize(PROFILES_FILE) / 1024 / 1024
    print(f"\n  Saved to {PROFILES_FILE} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
