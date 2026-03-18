#!/usr/bin/env python3
"""
Test improved scraping methodology against 8 Alabama districts 
with known ground truth from manual review.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime

BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")

# Ground truth from manual review
GROUND_TRUTH = {
    "Satsuma City": {
        "first_day": "2025-08-07", "last_day": "2026-05-22",
        "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02",
        "spring_break_start": "2026-04-13", "spring_break_end": "2026-04-17"
    },
    "Barbour County": {
        "first_day": "2025-08-05", "last_day": "2026-05-21",
        "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02",
        "spring_break_start": "2026-03-30", "spring_break_end": "2026-04-03"
    },
    "Chilton County": {
        "first_day": "2025-08-08", "last_day": "2026-05-21",
        "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02",
        "spring_break_start": "2026-03-23", "spring_break_end": "2026-03-27"
    },
    "Crenshaw County": {
        "first_day": "2025-08-06", "last_day": "2026-05-21",
        "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02",
        "spring_break_start": "2026-03-30", "spring_break_end": "2026-04-03"
    },
    "Daleville City": {
        "first_day": "2025-08-05", "last_day": "2026-05-21",
        "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-06",
        "spring_break_start": "2026-03-23", "spring_break_end": "2026-03-27"
    },
    "Elba City": {
        "first_day": "2025-08-07", "last_day": "2026-05-21",
        "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02",
        "spring_break_start": "2026-03-30", "spring_break_end": "2026-04-03"
    },
    "Midfield City": {
        "first_day": "2025-08-07", "last_day": "2026-05-22",
        "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-05",
        "spring_break_start": "2026-03-23", "spring_break_end": "2026-03-27"
    },
    "Thomasville City": {
        "first_day": "2025-08-07", "last_day": "2026-05-22",
        "winter_break_start": "2025-12-19", "winter_break_end": "2026-01-02",
        "spring_break_start": "2026-03-30", "spring_break_end": "2026-04-03"
    },
}


def brave_search(query):
    """Search Brave API"""
    import urllib.request
    import urllib.parse
    
    params = urllib.parse.urlencode({"q": query, "count": 5})
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_API_KEY
    })
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("web", {}).get("results", [])
    except Exception as e:
        print(f"    Search error: {e}")
        return []


def score_result(r, district_name):
    """Score a search result for calendar quality"""
    url = r.get("url", "")
    title = r.get("title", "").lower()
    desc = r.get("description", "").lower()
    
    score = 0
    if url.endswith(".pdf"): score += 5
    if "calendar" in title: score += 3
    if "2025-2026" in title or "2025-2026" in desc: score += 3
    if "2025" in desc and "2026" in desc: score += 2
    if any(m in desc for m in ["august", "first day", "spring break"]): score += 2
    if ".edu" in url or ".k12" in url or ".us" in url: score += 2
    if "facebook" in url or "twitter" in url or "niche" in url: score -= 5
    if "usnews" in url or "greatschools" in url: score -= 3
    
    return score


def fetch_url_text(url, max_chars=8000):
    """Fetch text from URL (PDF via pdftotext, HTML via simple extraction)"""
    try:
        if url.endswith(".pdf") or "pdf" in url.lower():
            # Download and convert PDF
            pdf_path = "/tmp/cal_test.pdf"
            subprocess.run(["wget", "-q", "--timeout=10", url, "-O", pdf_path], 
                         check=True, timeout=15)
            result = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], 
                                  capture_output=True, text=True, timeout=10)
            return result.stdout[:max_chars]
        else:
            # HTML via wget + basic strip
            import urllib.request
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
            
            # Strip HTML tags roughly
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_chars]
    except Exception as e:
        return f"FETCH_ERROR: {e}"


def extract_dates_with_claude(text, district_name, state):
    """Use Claude to extract dates from calendar text"""
    import urllib.request
    
    prompt = f"""Extract school calendar dates for {district_name} School District ({state}) for the 2025-2026 school year.

RULES:
- Only extract dates you can DIRECTLY see in the text
- If a date is not clearly stated, return null
- First day = first day of school for STUDENTS (not teachers/staff)
- Last day = last day of school for STUDENTS
- Spring break = the week-long spring/Easter break
- Winter break = Christmas/holiday break period
- Return dates in YYYY-MM-DD format
- Alabama schools typically start in early August (Aug 4-11)

TEXT:
{text[:4000]}

Return ONLY valid JSON:
{{"first_day": "YYYY-MM-DD or null", "last_day": "YYYY-MM-DD or null", "winter_break_start": "YYYY-MM-DD or null", "winter_break_end": "YYYY-MM-DD or null", "spring_break_start": "YYYY-MM-DD or null", "spring_break_end": "YYYY-MM-DD or null"}}"""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # Try reading from config
        try:
            result = subprocess.run(["clawdbot", "gateway", "config.get"], capture_output=True, text=True)
            # Just use a simple approach
            return None
        except:
            pass
    
    body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}]
    })
    
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body.encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            text_resp = data["content"][0]["text"]
            # Find JSON in response
            json_match = re.search(r'\{[^}]+\}', text_resp, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
    except Exception as e:
        print(f"    Claude error: {e}")
    
    return None


def test_district(name, state="AL"):
    """Run improved methodology on one district"""
    print(f"\n{'='*60}")
    print(f"  {name}, {state}")
    print(f"{'='*60}")
    
    # Step 1: Targeted search
    queries = [
        f'"{name}" school district Alabama 2025-2026 calendar PDF',
        f'"{name}" schools Alabama first day of school 2025',
    ]
    
    all_results = []
    for q in queries:
        results = brave_search(q)
        all_results.extend(results)
        time.sleep(0.5)
    
    # Deduplicate by URL
    seen = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append(r)
    
    # Score and rank
    scored = [(score_result(r, name), r) for r in unique]
    scored.sort(key=lambda x: -x[0])
    
    print(f"  Found {len(unique)} unique results")
    for score, r in scored[:5]:
        print(f"    [{score:+d}] {r['title'][:60]}")
        print(f"         {r['url'][:80]}")
    
    # Step 2: Fetch top 3 results
    best_text = ""
    best_url = ""
    for score, r in scored[:3]:
        if score < 0:
            continue
        url = r["url"]
        print(f"\n  Fetching: {url[:80]}...")
        text = fetch_url_text(url)
        if "FETCH_ERROR" in text:
            print(f"    {text}")
            continue
        
        # Check if text has calendar-like content
        cal_keywords = ["august", "september", "first day", "last day", "spring break", "winter", "grading period"]
        hits = sum(1 for kw in cal_keywords if kw in text.lower())
        print(f"    Calendar keyword hits: {hits}/7, text length: {len(text)}")
        
        if hits >= 2 and len(text) > len(best_text):
            best_text = text
            best_url = url
    
    if not best_text:
        print("  ❌ No usable calendar text found")
        return {"error": "no_calendar_text"}
    
    print(f"\n  Best source: {best_url[:80]}")
    
    # Step 3: Extract with Claude
    print("  Extracting with Claude...")
    dates = extract_dates_with_claude(best_text, name, state)
    
    if dates:
        dates["source_url"] = best_url
        print(f"  Extracted:")
        for k, v in dates.items():
            if k != "source_url":
                print(f"    {k}: {v}")
    
    return dates


def main():
    print("=" * 70)
    print("IMPROVED METHODOLOGY VALIDATION TEST")
    print(f"Testing 8 Alabama districts against ground truth")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)
    
    results = {}
    
    for name in GROUND_TRUTH:
        dates = test_district(name)
        results[name] = dates
        time.sleep(1)
    
    # Compare
    print("\n" + "=" * 70)
    print("RESULTS COMPARISON")
    print("=" * 70)
    
    fields = ['first_day', 'last_day', 'winter_break_start', 'winter_break_end', 'spring_break_start', 'spring_break_end']
    total = 0
    correct = 0
    wrong = 0
    null = 0
    
    for name, truth in GROUND_TRUTH.items():
        extracted = results.get(name, {}) or {}
        print(f"\n{name}:")
        for f in fields:
            t = truth.get(f)
            e = extracted.get(f)
            total += 1
            if t == e:
                correct += 1
                mark = "✅"
            elif not e or e == "null":
                null += 1
                mark = "⬜"
            else:
                wrong += 1
                mark = "❌"
            print(f"  {mark} {f:<22} truth={t}  got={e}")
    
    print(f"\n{'='*70}")
    print(f"FINAL SCORE: {correct}/{total} correct ({correct/total*100:.0f}%), {wrong} wrong, {null} null")
    print(f"Compare to V1: 13/48 = 27%")
    print(f"Compare to QA sweep: 13/48 = 27%")
    
    # Save results
    with open("al_validation_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "methodology": "improved_v2_targeted_search",
            "results": results,
            "ground_truth": GROUND_TRUTH,
            "score": {"correct": correct, "wrong": wrong, "null": null, "total": total}
        }, f, indent=2)
    
    print(f"\nSaved to al_validation_results.json")


if __name__ == "__main__":
    main()
