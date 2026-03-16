#!/usr/bin/env python3
"""Retry scraper for llm_no_dates and remaining medium districts.

Improvements over original:
1. Better search queries (tries multiple strategies)
2. Uses Sonnet for harder cases (still cheap)
3. More URL path patterns
4. Stores content for debugging
"""

from __future__ import annotations
import argparse, csv, json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
NCES_FILE = BASE_DIR / "nces_all_districts.csv"
RESULTS_FILE = BASE_DIR / "retry_scraper_results.json"
LLM_RESULTS_FILE = BASE_DIR / "llm_scraper_results.json"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")

SAVE_INTERVAL = 10
REQUEST_DELAY = 0.3
BRAVE_DELAY = 1.1

def load_nces_urls() -> dict:
    url_map = {}
    if NCES_FILE.exists():
        with open(NCES_FILE) as f:
            for r in csv.DictReader(f):
                if r.get('website'):
                    url_map[r['leaid']] = r['website']
    return url_map

NCES_URLS = load_nces_urls()

LLM_PROMPT = """You are extracting school calendar dates for the 2025-2026 school year.

District: {district_name} ({state})

Return ONLY a JSON object. Use YYYY-MM-DD format. Use null if truly not found.

IMPORTANT RULES:
- Spring break is typically 1-2 weeks in March/April 2026
- Winter break is Dec 2025 through early Jan 2026
- First day of school is typically Aug-Sep 2025
- Last day of school is typically May-Jun 2026
- If dates say "2024-2025", these are WRONG YEAR — return all nulls
- If you see "March 17-21, 2026" that means start=2026-03-17, end=2026-03-21
- Look for terms like: spring break, spring recess, spring vacation, Easter break, March break
- Also: winter break, Christmas break, holiday break, winter recess
- "Teacher workday" or "professional development" before students start — first day = first STUDENT day

{{
  "spring_break_start": "YYYY-MM-DD or null",
  "spring_break_end": "YYYY-MM-DD or null",
  "winter_break_start": "YYYY-MM-DD or null",
  "winter_break_end": "YYYY-MM-DD or null",
  "first_day": "YYYY-MM-DD or null",
  "last_day": "YYYY-MM-DD or null",
  "school_year": "2025-2026 or null"
}}

Web content (may be messy, look for calendar dates):
{content}"""


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def brave_search(query: str) -> list[dict]:
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


def web_fetch(url: str, max_chars: int = 10000) -> str:
    if url.lower().endswith('.pdf'):
        return ""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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
        text = re.sub(r'[ \t]+', ' ', text)
        # Remove empty lines
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        return '\n'.join(lines)[:max_chars]
    except Exception:
        return ""


def llm_extract(content: str, district_name: str, state: str) -> dict | None:
    if not ANTHROPIC_API_KEY or not content or len(content) < 50:
        return None
    
    prompt = LLM_PROMPT.format(
        district_name=district_name,
        state=state,
        content=content[:8000]
    )
    
    payload = json.dumps({
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 400,
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
        
        # Try to find JSON block
        # First try code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
        if not json_match:
            # Try bare JSON
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.S)
        
        if json_match:
            raw = json_match.group(1) if json_match.lastindex else json_match.group()
            dates = json.loads(raw)
            return dates
    except Exception as e:
        log(f"    LLM error: {e}")
    
    return None


def validate_dates(dates: dict) -> dict | None:
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
    
    sb_start = parse_date(dates.get('spring_break_start'))
    sb_end = parse_date(dates.get('spring_break_end'))
    if sb_start and date(2026, 2, 1) <= sb_start <= date(2026, 5, 31):
        validated['spring_break_start'] = sb_start.isoformat()
        if sb_end and sb_start <= sb_end <= date(2026, 6, 15):
            validated['spring_break_end'] = sb_end.isoformat()
    
    wb_start = parse_date(dates.get('winter_break_start'))
    wb_end = parse_date(dates.get('winter_break_end'))
    if wb_start and date(2025, 11, 15) <= wb_start <= date(2026, 1, 15):
        validated['winter_break_start'] = wb_start.isoformat()
        if wb_end and wb_start <= wb_end <= date(2026, 1, 31):
            validated['winter_break_end'] = wb_end.isoformat()
    
    fd = parse_date(dates.get('first_day'))
    if fd and date(2025, 7, 15) <= fd <= date(2025, 9, 30):
        validated['first_day'] = fd.isoformat()
    
    ld = parse_date(dates.get('last_day'))
    if ld and date(2026, 5, 1) <= ld <= date(2026, 7, 15):
        validated['last_day'] = ld.isoformat()
    
    if 'spring_break_start' in validated or ('first_day' in validated and 'last_day' in validated):
        validated['school_year'] = '2025-2026'
        return validated
    
    return None


def find_calendar_content(nces_id: str, name: str, state: str) -> tuple[str, str]:
    """Multi-strategy content finding."""
    
    base_url = NCES_URLS.get(nces_id, "")
    if base_url:
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url
        base_url = base_url.rstrip('/')
    
    # Strategy 1: Direct URL patterns (fast, no API calls)
    if base_url:
        paths = ['/calendar', '/page/school-calendar', '/calendars', 
                 '/about/calendar', '/parents/calendar', '/page/calendar',
                 '/district-calendar', '/academic-calendar', '']
        for path in paths:
            try_url = base_url + path
            content = web_fetch(try_url)
            if content and len(content) > 200:
                if '2025' in content or '2026' in content:
                    return try_url, content
            time.sleep(REQUEST_DELAY)
    
    # Strategy 2: Brave search with specific queries
    if BRAVE_API_KEY:
        clean_name = re.sub(r'\s*\(.*?\)', '', name)
        clean_name = re.sub(r'\b(USD|ISD|SD|CSD|CUSD|HSD|UHSD|PSD|UFSD|CCD)\b', '', clean_name).strip()
        
        queries = [
            f'"{clean_name}" {state} school calendar 2025-2026 spring break',
            f'{clean_name} school district {state} 2025-2026 calendar',
        ]
        
        for query in queries:
            results = brave_search(query)
            time.sleep(BRAVE_DELAY)
            
            for r in results[:3]:
                url = r['url']
                if '.pdf' in url.lower():
                    continue
                content = web_fetch(url)
                if content and len(content) > 200:
                    if '2025' in content or '2026' in content:
                        return url, content
                time.sleep(REQUEST_DELAY)
    
    return "", ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['retry-fails', 'medium', 'both'], default='both')
    parser.add_argument('--min-enrollment', type=int, default=0)
    parser.add_argument('--max-districts', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    
    log("=" * 70)
    log("Retry/Medium School Calendar Scraper")
    log("=" * 70)
    
    if not ANTHROPIC_API_KEY:
        log("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)
    
    # Load districts to process
    to_process = []
    
    if args.mode in ('retry-fails', 'both'):
        # Load llm_no_dates from previous run
        with open(LLM_RESULTS_FILE) as f:
            llm_data = json.load(f)
        fails = {k: v for k, v in llm_data.items() if v.get('status') == 'llm_no_dates'}
        
        with open(COMPREHENSIVE_FILE) as f:
            all_districts = {r['nces_leaid']: r for r in csv.DictReader(f)}
        
        for nces_id, result in fails.items():
            padded = nces_id.zfill(7)
            if padded in all_districts and all_districts[padded]['confidence'] != 'confirmed':
                d = all_districts[padded]
                to_process.append(d)
        log(f"Retry-fails: {len(to_process)} districts")
    
    if args.mode in ('medium', 'both'):
        with open(COMPREHENSIVE_FILE) as f:
            all_districts_list = list(csv.DictReader(f))
        
        # Also load prior llm results to skip already-attempted districts
        prior_ids = set()
        if LLM_RESULTS_FILE.exists():
            with open(LLM_RESULTS_FILE) as f:
                prior = json.load(f)
                prior_ids = set(prior.keys())
        
        medium = [r for r in all_districts_list if r['confidence'] == 'medium']
        # Skip already attempted
        medium = [r for r in medium if r['nces_leaid'] not in prior_ids]
        medium.sort(key=lambda r: int(r.get('enrollment', 0) or 0), reverse=True)
        
        if args.min_enrollment:
            medium = [r for r in medium if int(r.get('enrollment', 0) or 0) >= args.min_enrollment]
        
        to_process.extend(medium)
        log(f"Medium (new): {len(medium)} districts")
    
    if args.max_districts:
        to_process = to_process[:args.max_districts]
    
    # Sort by enrollment descending (highest impact first)
    to_process.sort(key=lambda r: int(r.get('enrollment', 0) or 0), reverse=True)
    
    # Load existing results
    results = {}
    if args.resume and RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            results = json.load(f)
    
    done_ids = set(results.keys())
    to_process = [r for r in to_process if r['nces_leaid'] not in done_ids]
    
    log(f"Total to process: {len(to_process)}")
    
    found = sum(1 for r in results.values() if r.get('status') == 'found')
    failed = sum(1 for r in results.values() if r.get('status') != 'found')
    
    for i, district in enumerate(to_process):
        nces_id = district['nces_leaid']
        name = district['district_name']
        state = district['state']
        enrollment = int(district.get('enrollment', 0) or 0)
        
        log(f"[{i+1}/{len(to_process)}] {name} ({state}) — {enrollment:,}")
        
        url, content = find_calendar_content(nces_id, name, state)
        
        if not content:
            log(f"  ❌ no_content")
            results[nces_id] = {
                'name': name, 'state': state, 'enrollment': enrollment,
                'status': 'no_content',
                'timestamp': datetime.now().isoformat(),
            }
            failed += 1
        else:
            raw_dates = llm_extract(content, name, state)
            validated = validate_dates(raw_dates) if raw_dates else None
            
            if validated:
                log(f"  ✅ spring={validated.get('spring_break_start', 'N/A')}, first={validated.get('first_day', 'N/A')}")
                results[nces_id] = {
                    'name': name, 'state': state, 'enrollment': enrollment,
                    'status': 'found', 'method': 'llm_extract_v2',
                    'url': url, 'dates': validated,
                    'timestamp': datetime.now().isoformat(),
                }
                found += 1
            else:
                log(f"  ❌ no_dates (raw: {str(raw_dates)[:100]})")
                results[nces_id] = {
                    'name': name, 'state': state, 'enrollment': enrollment,
                    'status': 'llm_no_dates',
                    'url': url,
                    'raw_response': str(raw_dates)[:200] if raw_dates else None,
                    'timestamp': datetime.now().isoformat(),
                }
                failed += 1
        
        total = found + failed
        if total % SAVE_INTERVAL == 0:
            with open(RESULTS_FILE, 'w') as f:
                json.dump(results, f, indent=2)
            pct = found / total * 100 if total else 0
            log(f"  --- Save: {found}✅ {failed}❌ ({pct:.0f}%) ---")
    
    # Final save
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    total = found + failed
    pct = found / total * 100 if total else 0
    log("=" * 70)
    log(f"DONE: {found}✅ found, {failed}❌ failed ({pct:.1f}% success)")
    log("=" * 70)


if __name__ == '__main__':
    main()
