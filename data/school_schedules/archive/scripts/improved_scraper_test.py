#!/usr/bin/env python3
"""
Improved scraper test - v2 methodology
Tests against the 11 manually-verified districts to compare results.

Key changes from v1:
1. Search for actual calendar page/PDF, not just homepage
2. Multiple targeted search queries per district  
3. Explicit text anchor extraction
4. Confidence scoring - reject rather than hallucinate
"""

import json
import os
import time
import requests
from datetime import datetime

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")

# Load manually verified districts
with open("manual_review_log.json") as f:
    manual_log = json.load(f)

districts = manual_log["reviews"]

def brave_search(query, count=5):
    """Search Brave for a query."""
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"X-Subscription-Token": BRAVE_API_KEY, "Accept": "application/json"}
    params = {"q": query, "count": count}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("web", {}).get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", "")
            })
        return results
    except Exception as e:
        print(f"  Search error: {e}")
        return []

def firecrawl_fetch(url, timeout=30):
    """Fetch a page using Firecrawl for better content extraction."""
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "url": url,
                "formats": ["markdown"],
                "timeout": 20000
            },
            timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            return data.get("data", {}).get("markdown", "")
    except Exception as e:
        print(f"  Firecrawl error for {url}: {e}")
    return None

def basic_fetch(url, timeout=15):
    """Basic HTTP fetch as fallback."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SchoolCalendarBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text[:50000]
    except Exception as e:
        print(f"  Basic fetch error for {url}: {e}")
        return None

def extract_dates_with_claude(district_name, state, school_year, page_content, source_url):
    """Use Claude to extract school dates from page content."""
    if not ANTHROPIC_API_KEY:
        print("  No Anthropic API key - skipping LLM extraction")
        return None
    
    prompt = f"""Extract school calendar dates for {district_name} ({state}) for the {school_year} school year from the following web page content.

CRITICAL RULES:
1. ONLY extract dates that are EXPLICITLY stated in the text. Do NOT guess, infer, or hallucinate.
2. If you cannot find a specific date with confidence, set it to null. It is MUCH BETTER to return null than to guess wrong.
3. Look for these specific phrases: "First Day of School", "First Day for Students", "Spring Break", "Winter Break", "Christmas Break", "Christmas Holidays", "Last Day of School", "Last Day for Students"
4. Also look for Nine Weeks/Grading Period tables - the first period start = first day, last period end = last day.
5. IGNORE: event calendars, sports schedules, PTA meetings, news posts, ski meets, concerts. Only extract from the OFFICIAL ACADEMIC CALENDAR.
6. Verify dates are for {school_year}, not a different school year.
7. Spring break is typically 5-10 consecutive weekdays. If you find a 2-3 day "spring break", you're probably reading an event, not the break.
8. Winter/Christmas break typically starts mid-to-late December and ends early January.

Return ONLY valid JSON (no markdown, no explanation, no code fences):
{{"first_day": "YYYY-MM-DD or null", "last_day": "YYYY-MM-DD or null", "spring_break_start": "YYYY-MM-DD or null", "spring_break_end": "YYYY-MM-DD or null", "winter_break_start": "YYYY-MM-DD or null", "winter_break_end": "YYYY-MM-DD or null", "confidence": "high|medium|low|none", "source_type": "academic_calendar|pdf_calendar|event_feed|no_calendar_found", "notes": "brief explanation of what source you found and extracted from"}}

Page content from {source_url}:
{page_content[:20000]}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 500,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        resp.raise_for_status()
        content = resp.json()["content"][0]["text"].strip()
        # Try to parse JSON
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content)
    except Exception as e:
        print(f"  Claude extraction error: {e}")
        return None

def search_district_calendar(district):
    """Multi-query search strategy for a district's calendar."""
    name = district["name"]
    state = district["state"]
    
    # Fred's insight: district names are accurate, use them directly
    queries = [
        f'"{name}" "2025-2026" school calendar',
        f'"{name}" school district first day of school 2025',
        f'"{name}" {state} school calendar spring break 2026',
    ]
    
    all_results = []
    seen_urls = set()
    
    for query in queries:
        print(f"  🔍 {query}")
        results = brave_search(query, count=5)
        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)
        time.sleep(0.5)
    
    return all_results

def score_result(result):
    """Score a search result for likelihood of being the actual calendar."""
    score = 0
    url = result["url"].lower()
    title = result["title"].lower()
    desc = result["description"].lower()
    combined = f"{title} {desc}"
    
    # Strong positive signals - calendar content
    if "calendar" in title: score += 3
    if "2025-2026" in combined or "2025-26" in combined: score += 3
    if "calendar" in url: score += 2
    if any(ext in url for ext in [".pdf"]): score += 4  # PDFs are gold
    if "first day" in combined: score += 2
    if "spring break" in combined: score += 2
    if "school year" in combined: score += 1
    if "student calendar" in combined: score += 3
    
    # Platform signals (where calendars typically live)
    calendar_hosts = ["finalsite.net", "edl.io", "thrillshare", "parentsquare", "sharepoint", "boarddocs"]
    if any(host in url for host in calendar_hosts): score += 2
    
    # Negative signals - not the calendar
    if "facebook.com" in url: score -= 1
    if "twitter.com" in url or "x.com" in url: score -= 3
    if "event" in title and "calendar" not in title: score -= 2
    if "news" in url and "calendar" not in url: score -= 2
    if "agenda" in title: score -= 2
    if "minutes" in title: score -= 2
    if "niche.com" in url: score -= 3
    if "greatschools.org" in url: score -= 3
    if "zillow" in url: score -= 5
    
    return score

def test_district(district):
    """Test the improved methodology on one district."""
    name = district["name"]
    state = district["state"]
    nces_id = district["nces_id"]
    correct = district["correct_dates"]
    
    print(f"\n{'='*60}")
    print(f"📋 {name}, {state} (NCES: {nces_id})")
    print(f"{'='*60}")
    
    # Step 1: Search
    results = search_district_calendar(district)
    print(f"  Found {len(results)} unique results")
    
    # Step 2: Score and rank
    scored = [(score_result(r), r) for r in results]
    scored.sort(key=lambda x: -x[0])
    
    if scored:
        print(f"  Top results:")
        for score, r in scored[:5]:
            print(f"    [{score:+d}] {r['title'][:60]}")
            print(f"         {r['url'][:80]}")
    
    # Step 3: Try to fetch and extract from top results
    best_extraction = None
    best_source = None
    
    for score, result in scored[:3]:  # Try top 3
        url = result["url"]
        print(f"\n  📥 Fetching: {url[:80]}...")
        
        # Try Firecrawl first, then basic fetch
        content = firecrawl_fetch(url)
        fetch_method = "firecrawl"
        if not content:
            content = basic_fetch(url)
            fetch_method = "basic"
        
        if not content:
            print(f"    ⚠️  Could not fetch")
            continue
        
        print(f"    ✅ Got {len(content)} chars via {fetch_method}")
        
        extraction = extract_dates_with_claude(name, state, "2025-2026", content, url)
        if extraction:
            print(f"    🤖 Confidence: {extraction.get('confidence', '?')}")
            print(f"    📝 Notes: {extraction.get('notes', 'none')}")
            
            if extraction.get("confidence") != "none":
                if best_extraction is None or (
                    extraction.get("confidence") == "high" and 
                    best_extraction.get("confidence") != "high"
                ):
                    best_extraction = extraction
                    best_source = result
                    best_source["fetch_method"] = fetch_method
                
                if extraction.get("confidence") == "high":
                    break  # Stop if we got high confidence
        
        time.sleep(1)
    
    # Step 4: Compare with correct dates
    result_entry = {
        "nces_id": nces_id,
        "name": name,
        "state": state,
        "correct_dates": correct,
        "v2_extracted": best_extraction,
        "v2_source_url": best_source["url"] if best_source else None,
        "v2_source_title": best_source["title"] if best_source else None,
        "v2_fetch_method": best_source.get("fetch_method") if best_source else None,
        "search_results_count": len(results),
        "original_dates": district.get("original_dates", {}),
        "qa_sweep_dates": district.get("qa_sweep_dates", {}),
    }
    
    if best_extraction:
        matches = 0
        total = 0
        nulls = 0
        comparisons = {}
        for field in ["first_day", "last_day", "spring_break_start", "spring_break_end", "winter_break_start", "winter_break_end"]:
            correct_val = correct.get(field)
            extracted_val = best_extraction.get(field)
            if correct_val:
                total += 1
                if extracted_val is None:
                    nulls += 1
                    comparisons[field] = {"correct": correct_val, "extracted": None, "match": False, "null": True}
                else:
                    match = correct_val == extracted_val
                    if match:
                        matches += 1
                    comparisons[field] = {"correct": correct_val, "extracted": extracted_val, "match": match, "null": False}
        
        result_entry["comparisons"] = comparisons
        result_entry["accuracy"] = f"{matches}/{total}"
        result_entry["nulls"] = nulls
        
        print(f"\n  📊 V2 Results (confidence: {best_extraction.get('confidence', '?')}):")
        for field, comp in comparisons.items():
            if comp.get("null"):
                icon = "⬜"
                print(f"    {icon} {field}: correct={comp['correct']}, got=NULL (admitted unknown)")
            elif comp["match"]:
                icon = "✅"
                print(f"    {icon} {field}: {comp['correct']}")
            else:
                icon = "❌"
                print(f"    {icon} {field}: correct={comp['correct']}, got={comp['extracted']}")
        print(f"  Accuracy: {matches}/{total} ({nulls} nulls)")
    else:
        result_entry["accuracy"] = "0/0"
        result_entry["nulls"] = 0
        print(f"\n  ❌ No extraction possible")
    
    return result_entry

def main():
    print("=" * 60)
    print("🔬 IMPROVED SCRAPER TEST — v2 Methodology")
    print(f"Testing {len(districts)} manually-verified districts")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)
    
    results = []
    for district in districts:
        result = test_district(district)
        results.append(result)
        time.sleep(2)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    
    total_matches = 0
    total_fields = 0
    total_nulls = 0
    
    # Also compare v1 (original scraper) accuracy
    v1_matches = 0
    v1_total = 0
    
    for r in results:
        acc = r.get("accuracy", "0/0")
        nulls = r.get("nulls", 0)
        if "/" in str(acc):
            parts = str(acc).split("/")
            total_matches += int(parts[0])
            total_fields += int(parts[1])
            total_nulls += nulls
        
        # Count v1 accuracy
        correct = r.get("correct_dates", {})
        original = r.get("original_dates", {})
        for field in ["first_day", "last_day", "spring_break_start", "spring_break_end", "winter_break_start", "winter_break_end"]:
            if correct.get(field) and original.get(field):
                v1_total += 1
                if correct[field] == original[field]:
                    v1_matches += 1
        
        conf = r.get("v2_extracted", {}).get("confidence", "N/A") if r.get("v2_extracted") else "none"
        print(f"  {r['name']}, {r['state']}: {acc} (nulls: {nulls}) — confidence: {conf}")
    
    print(f"\n  🆕 V2 Overall: {total_matches}/{total_fields} ({100*total_matches/total_fields:.1f}% correct, {total_nulls} nulls)")
    if v1_total > 0:
        print(f"  📊 V1 Overall: {v1_matches}/{v1_total} ({100*v1_matches/v1_total:.1f}% correct)")
    print(f"\n  V2 nulls are GOOD — means it admitted uncertainty instead of hallucinating")
    
    # Save results
    output = {
        "metadata": {
            "test_date": datetime.now().isoformat(),
            "methodology": "v2 - targeted search + explicit extraction + confidence scoring",
            "districts_tested": len(districts),
            "v2_accuracy": f"{total_matches}/{total_fields}",
            "v1_accuracy": f"{v1_matches}/{v1_total}",
            "v2_nulls": total_nulls
        },
        "results": results
    }
    
    with open("improved_scraper_test_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults saved to improved_scraper_test_results.json")

if __name__ == "__main__":
    main()
