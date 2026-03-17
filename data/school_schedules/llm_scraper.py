#!/usr/bin/env python3
"""LLM-Enhanced School Calendar Scraper.

Instead of regex parsing, uses Claude Haiku to extract structured dates
from messy web content. This should dramatically improve the parse_failed rate.

Flow:
1. Firecrawl scrape the district website or a search result (markdown output)
2. Send the markdown to Claude Haiku with a structured extraction prompt
3. Validate dates and save

Cost estimate: Haiku ~$0.25/MTok input, $1.25/MTok output
  - ~2K tokens input per page, ~200 tokens output = ~$0.0008/district
  - 7,000 districts = ~$5.60 total
"""

from __future__ import annotations
import argparse, csv, json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
RESULTS_FILE = BASE_DIR / "llm_scraper_results.json"
LOG_FILE = BASE_DIR / "llm_scraper.log"

NCES_FILE = BASE_DIR / "nces_all_districts.csv"

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")

SAVE_INTERVAL = 5
REQUEST_DELAY = 0.3
BRAVE_DELAY = 1.1

# Global flag to skip Firecrawl when payment limit hit
FIRECRAWL_DISABLED = False

# Load NCES website URLs
def load_nces_urls() -> dict:
    url_map = {}
    if NCES_FILE.exists():
        with open(NCES_FILE) as f:
            for r in csv.DictReader(f):
                if r.get('website'):
                    url_map[r['leaid']] = r['website']
    return url_map

NCES_URLS = load_nces_urls()

LLM_EXTRACTION_PROMPT = """Extract the 2025-2026 school calendar dates from this content for {district_name} ({state}).

Return ONLY a JSON object with these fields (use YYYY-MM-DD format, null if not found):
{{
  "spring_break_start": "YYYY-MM-DD or null",
  "spring_break_end": "YYYY-MM-DD or null", 
  "winter_break_start": "YYYY-MM-DD or null",
  "winter_break_end": "YYYY-MM-DD or null",
  "first_day": "YYYY-MM-DD or null",
  "last_day": "YYYY-MM-DD or null",
  "school_year": "2025-2026 or null",
  "confidence": "high/medium/low"
}}

Rules:
- First day should be Aug-Sep 2025
- Last day should be May-Jun 2026
- Spring break should be Feb-May 2026
- Winter break should be Dec 2025 - Jan 2026
- Only extract 2025-2026 data, ignore other years
- "confidence" = "high" if dates are explicitly stated, "low" if inferred

Content:
{content}"""


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def brave_search(query: str) -> list[dict]:
    """Search Brave and return results."""
    if not BRAVE_API_KEY:
        return []
    params = urllib.parse.urlencode({'q': query, 'count': 5})
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'X-Subscription-Token': BRAVE_API_KEY,
    })
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        results = []
        for r in data.get('web', {}).get('results', []):
            results.append({
                'title': r.get('title', ''),
                'url': r.get('url', ''),
                'description': r.get('description', ''),
            })
        return results
    except Exception as e:
        log(f"    Brave error: {e}")
        return []


def firecrawl_scrape(url: str, max_chars: int = 8000) -> str:
    """Firecrawl scrape — returns markdown."""
    global FIRECRAWL_DISABLED
    
    if not FIRECRAWL_API_KEY or FIRECRAWL_DISABLED:
        return ""
        
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "timeout": 20000,
    }).encode()
    req = urllib.request.Request(
        "https://api.firecrawl.dev/v1/scrape",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        if result.get("success"):
            md = result.get("data", {}).get("markdown", "")
            return md[:max_chars]
    except urllib.error.HTTPError as e:
        if e.code == 402:
            log(f"    Firecrawl payment limit reached (HTTP 402). Disabling Firecrawl for this session.")
            FIRECRAWL_DISABLED = True
        else:
            log(f"    Firecrawl HTTP error: {e}")
    except Exception as e:
        log(f"    Firecrawl error: {e}")
    return ""


def web_fetch(url: str, max_chars: int = 8000) -> str:
    """Simple web fetch — returns text."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; SchoolCalendarBot/1.0)',
        'Accept': 'text/html,application/xhtml+xml',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        content_type = resp.headers.get('Content-Type', '')
        if 'pdf' in content_type.lower():
            return ""
        raw = resp.read(max_chars * 2)
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S)
        text = re.sub(r'<[^>]+>', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&#\d+;', '', text)
        return text[:max_chars]
    except Exception:
        return ""


def llm_extract(content: str, district_name: str, state: str) -> dict | None:
    """Use Claude Haiku to extract dates from content."""
    if not ANTHROPIC_API_KEY or not content or len(content) < 50:
        return None
    
    prompt = LLM_EXTRACTION_PROMPT.format(
        district_name=district_name,
        state=state,
        content=content[:6000]  # Keep input manageable
    )
    
    payload = json.dumps({
        "model": "claude-3-haiku-20240307",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        text = result.get("content", [{}])[0].get("text", "")
        
        # Extract JSON from response
        json_match = re.search(r'\{[^}]+\}', text, re.S)
        if json_match:
            dates = json.loads(json_match.group())
            return dates
    except Exception as e:
        log(f"    LLM error: {e}")
    
    return None


def validate_dates(dates: dict) -> dict | None:
    """Validate extracted dates are reasonable for 2025-2026 school year."""
    if not dates:
        return None
    
    validated = {}
    
    def parse_date(s):
        if not s or s == 'null' or s == 'None':
            return None
        try:
            return date.fromisoformat(str(s))
        except (ValueError, TypeError):
            return None
    
    # Spring break
    sb_start = parse_date(dates.get('spring_break_start'))
    sb_end = parse_date(dates.get('spring_break_end'))
    if sb_start and date(2026, 2, 1) <= sb_start <= date(2026, 5, 31):
        validated['spring_break_start'] = sb_start.isoformat()
        if sb_end and sb_start <= sb_end <= date(2026, 6, 15):
            validated['spring_break_end'] = sb_end.isoformat()
    
    # Winter break
    wb_start = parse_date(dates.get('winter_break_start'))
    wb_end = parse_date(dates.get('winter_break_end'))
    if wb_start and date(2025, 11, 15) <= wb_start <= date(2026, 1, 15):
        validated['winter_break_start'] = wb_start.isoformat()
        if wb_end and wb_start <= wb_end <= date(2026, 1, 31):
            validated['winter_break_end'] = wb_end.isoformat()
    
    # First day
    fd = parse_date(dates.get('first_day'))
    if fd and date(2025, 7, 15) <= fd <= date(2025, 9, 30):
        validated['first_day'] = fd.isoformat()
    
    # Last day
    ld = parse_date(dates.get('last_day'))
    if ld and date(2026, 5, 1) <= ld <= date(2026, 7, 15):
        validated['last_day'] = ld.isoformat()
    
    # Need at least spring break to count as success
    if 'spring_break_start' in validated:
        validated['school_year'] = '2025-2026'
        return validated
    
    return None


def try_fetch_url(url: str) -> str:
    """Try to fetch content from a URL. web_fetch first (fast), Firecrawl as fallback."""
    if url.lower().endswith('.pdf'):
        return ""
    
    # Try simple web fetch first (fast, free)
    content = web_fetch(url)
    if content and len(content) > 200:
        return content
    
    # Firecrawl fallback — JS rendering for dynamic calendar pages
    if not FIRECRAWL_DISABLED:
        content = firecrawl_scrape(url)
        if content and len(content) > 100:
            time.sleep(1.0)  # throttle to avoid concurrency limits
            return content
        time.sleep(1.0)
    else:
        # Firecrawl disabled due to payment limits, rely only on web_fetch
        pass
    
    return ""


def find_calendar_content(district: dict) -> tuple[str, str]:
    """Find calendar content for a district.
    Strategy:
    1. Try NCES website URL + /calendar path guesses
    2. Fall back to Brave search
    Returns (url, content) tuple.
    """
    nces_id = district['nces_leaid']
    name = district['district_name']
    state = district['state']
    
    # Strategy 1: NCES website URL
    base_url = NCES_URLS.get(nces_id, "")
    if base_url:
        # Normalize
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url
        base_url = base_url.rstrip('/')
        
        # Try calendar page first, then homepage (just 2 attempts max)
        for path in ['/calendar', '']:
            try_url = base_url + path
            content = try_fetch_url(try_url)
            if content:
                if '2025' in content or '2026' in content or 'calendar' in content.lower():
                    return try_url, content
            time.sleep(REQUEST_DELAY)
    
    # Strategy 2: Brave search
    if BRAVE_API_KEY:
        clean_name = re.sub(r'\s*\(.*?\)', '', name)
        query = f'"{clean_name}" {state} school calendar 2025-2026'
        results = brave_search(query)
        time.sleep(BRAVE_DELAY)
        
        if not results:
            query = f'{clean_name} {state} school calendar 2025-2026'
            results = brave_search(query)
            time.sleep(BRAVE_DELAY)
        
        for r in results[:3]:
            url = r['url']
            content = try_fetch_url(url)
            if content and len(content) > 100:
                return url, content
            time.sleep(REQUEST_DELAY)
    
    # Strategy 3: Just try the base URL if we have it
    if base_url:
        content = try_fetch_url(base_url)
        if content:
            return base_url, content
    
    return "", ""


def load_results() -> dict:
    """Load existing results."""
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {}


def save_results(results: dict):
    """Save results to JSON."""
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='LLM-enhanced school calendar scraper')
    parser.add_argument('--resume', action='store_true', help='Resume from saved results')
    parser.add_argument('--min-enrollment', type=int, default=0, help='Minimum enrollment')
    parser.add_argument('--max-districts', type=int, default=0, help='Max districts to process (0=all)')
    parser.add_argument('--test', type=int, default=0, help='Test mode: process N districts then stop')
    parser.add_argument('--retry-failed', action='store_true', help='Only retry previously failed districts')
    args = parser.parse_args()
    
    log("=" * 70)
    log("LLM-Enhanced School Calendar Scraper")
    log("=" * 70)
    
    # Check API keys
    if not ANTHROPIC_API_KEY:
        log("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)
    if not FIRECRAWL_API_KEY:
        log("WARNING: FIRECRAWL_API_KEY not set — will use web_fetch only")
    
    # Load districts
    log("Loading districts...")
    with open(COMPREHENSIVE_FILE) as f:
        all_districts = list(csv.DictReader(f))
    
    # Filter to medium-confidence only
    medium = [r for r in all_districts if r.get('confidence') == 'medium']
    medium.sort(key=lambda r: int(r.get('enrollment', 0) or 0), reverse=True)
    
    if args.min_enrollment:
        medium = [r for r in medium if int(r.get('enrollment', 0) or 0) >= args.min_enrollment]
    
    if args.max_districts:
        medium = medium[:args.max_districts]
    
    # Load existing results
    results = load_results() if (args.resume or args.retry_failed) else {}
    done_ids = set(results.keys())
    
    if args.retry_failed:
        # Only retry districts that previously failed
        failed_ids = set(nid for nid, r in results.items() 
                        if isinstance(r, dict) and r.get('status') != 'found')
        to_process = [r for r in medium if r['nces_leaid'] in failed_ids]
        # Remove failed entries so they get re-processed
        for d in to_process:
            del results[d['nces_leaid']]
        log(f"Retry mode: {len(to_process)} previously failed districts")
    else:
        to_process = [r for r in medium if r['nces_leaid'] not in done_ids]
    
    log(f"Total medium-confidence: {len(medium)}")
    log(f"Already done: {len(done_ids)}")
    log(f"To process: {len(to_process)}")
    if args.min_enrollment:
        log(f"Min enrollment: {args.min_enrollment}")
    
    if not to_process:
        log("Nothing to process!")
        return
    
    # Stats
    found = sum(1 for r in results.values() if r.get('status') == 'found')
    failed = sum(1 for r in results.values() if r.get('status') != 'found')
    methods = {}
    
    test_count = 0
    
    for i, district in enumerate(to_process):
        nces_id = district['nces_leaid']
        name = district['district_name']
        state = district['state']
        enrollment = int(district.get('enrollment', 0) or 0)
        
        log(f"[{i+1}/{len(to_process)}] {name} ({state}) — {enrollment:,}")
        
        # Find calendar content
        url, content = find_calendar_content(district)
        
        if not content:
            log(f"  ❌ no_content")
            results[nces_id] = {
                'name': name, 'state': state, 'enrollment': enrollment,
                'status': 'no_content', 'method': 'no_content',
                'timestamp': datetime.now().isoformat(),
            }
            failed += 1
        else:
            # LLM extraction
            raw_dates = llm_extract(content, name, state)
            validated = validate_dates(raw_dates) if raw_dates else None
            
            if validated:
                log(f"  ✅ spring={validated.get('spring_break_start', 'N/A')}, first={validated.get('first_day', 'N/A')} [llm]")
                results[nces_id] = {
                    'name': name, 'state': state, 'enrollment': enrollment,
                    'status': 'found', 'method': 'llm_extract',
                    'url': url, 'dates': validated,
                    'timestamp': datetime.now().isoformat(),
                }
                found += 1
                method_key = 'llm_extract'
                methods[method_key] = methods.get(method_key, 0) + 1
            else:
                log(f"  ❌ llm_no_dates")
                results[nces_id] = {
                    'name': name, 'state': state, 'enrollment': enrollment,
                    'status': 'llm_no_dates', 'method': 'llm_no_dates',
                    'url': url,
                    'raw_response': str(raw_dates)[:200] if raw_dates else None,
                    'timestamp': datetime.now().isoformat(),
                }
                failed += 1
        
        # Save periodically
        total_processed = found + failed
        if total_processed % SAVE_INTERVAL == 0:
            save_results(results)
            pct = found / total_processed * 100 if total_processed else 0
            log(f"  --- Save: {found}✅ {failed}❌ ({pct:.0f}%) | Methods: {methods} ---")
        
        # Test mode
        if args.test:
            test_count += 1
            if test_count >= args.test:
                log(f"Test mode: stopping after {test_count} districts")
                break
    
    # Final save
    save_results(results)
    total = found + failed
    pct = found / total * 100 if total else 0
    log("=" * 70)
    log(f"DONE: {found}✅ found, {failed}❌ failed ({pct:.1f}% success)")
    log(f"Methods: {methods}")
    log("=" * 70)


if __name__ == '__main__':
    main()
