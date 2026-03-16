#!/usr/bin/env python3
"""Bulk scraper for *schools.us aggregator sites.

These sites have calendar pages for every district in every state:
  https://{state}schools.us/districts/{slug}/calendar/

They contain structured calendar data that's easy to parse with LLM.
This should be our fastest path to high coverage.
"""

from __future__ import annotations
import argparse, csv, json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
COMPREHENSIVE_FILE = BASE_DIR / "districts_comprehensive.csv"
RESULTS_FILE = BASE_DIR / "stateschools_results.json"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SAVE_INTERVAL = 25
REQUEST_DELAY = 0.5  # polite delay between requests

STATE_NAMES = {
    'AL': 'alabama', 'AK': 'alaska', 'AZ': 'arizona', 'AR': 'arkansas',
    'CA': 'california', 'CO': 'colorado', 'CT': 'connecticut', 'DE': 'delaware',
    'FL': 'florida', 'GA': 'georgia', 'HI': 'hawaii', 'ID': 'idaho',
    'IL': 'illinois', 'IN': 'indiana', 'IA': 'iowa', 'KS': 'kansas',
    'KY': 'kentucky', 'LA': 'louisiana', 'ME': 'maine', 'MD': 'maryland',
    'MA': 'massachusetts', 'MI': 'michigan', 'MN': 'minnesota', 'MS': 'mississippi',
    'MO': 'missouri', 'MT': 'montana', 'NE': 'nebraska', 'NV': 'nevada',
    'NH': 'newhampshire', 'NJ': 'newjersey', 'NM': 'newmexico', 'NY': 'newyork',
    'NC': 'northcarolina', 'ND': 'northdakota', 'OH': 'ohio', 'OK': 'oklahoma',
    'OR': 'oregon', 'PA': 'pennsylvania', 'RI': 'rhodeisland', 'SC': 'southcarolina',
    'SD': 'southdakota', 'TN': 'tennessee', 'TX': 'texas', 'UT': 'utah',
    'VT': 'vermont', 'VA': 'virginia', 'WA': 'washington', 'WV': 'westvirginia',
    'WI': 'wisconsin', 'WY': 'wyoming', 'DC': 'dc',
}

LLM_PROMPT = """Extract school calendar dates for {district_name} ({state}) from this content.

Return ONLY a JSON object with YYYY-MM-DD format dates. Use null if not found.

{{
  "spring_break_start": "YYYY-MM-DD or null",
  "spring_break_end": "YYYY-MM-DD or null",
  "winter_break_start": "YYYY-MM-DD or null",
  "winter_break_end": "YYYY-MM-DD or null",
  "first_day": "YYYY-MM-DD or null",
  "last_day": "YYYY-MM-DD or null",
  "school_year": "2025-2026 or null"
}}

Rules:
- Only extract 2025-2026 school year data
- Spring break: typically March-April 2026 (also called spring recess, spring vacation, Easter break)
- Winter break: typically Dec 2025 - Jan 2026 (also called Christmas break, holiday break)
- First day: typically Aug-Sep 2025 (first STUDENT day, not teacher workday)
- Last day: typically May-Jun 2026
- Look at the "Key Dates" section first if present
- If multiple dates for a break, start=first day off, end=last day off

Content:
{content}"""


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def district_to_slug(name: str) -> str:
    """Convert district name to URL slug."""
    # Common transformations
    slug = name.lower()
    # Remove common suffixes/prefixes
    slug = re.sub(r'\b(school district|sd|isd|usd|cusd|csd|ufsd|uhsd|hsd|psd|unified school district|city schools|county schools|public schools|school department|school division)\b', '', slug)
    slug = re.sub(r'\bcounty\b', 'county', slug)
    # Replace special chars
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


def web_fetch(url: str, max_chars: int = 12000) -> str:
    """Fetch a URL and return cleaned text."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
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
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        return '\n'.join(lines)[:max_chars]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "404"
        return ""
    except Exception:
        return ""


def llm_extract(content: str, district_name: str, state: str) -> dict | None:
    """Use Claude Haiku to extract dates."""
    if not ANTHROPIC_API_KEY or not content or len(content) < 100:
        return None
    
    prompt = LLM_PROMPT.format(
        district_name=district_name,
        state=state,
        content=content[:8000]
    )
    
    payload = json.dumps({
        "model": "claude-3-5-haiku-20241022",
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
        
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
        if not json_match:
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.S)
        
        if json_match:
            raw = json_match.group(1) if json_match.lastindex else json_match.group()
            return json.loads(raw)
    except Exception as e:
        log(f"    LLM error: {e}")
    
    return None


def validate_dates(dates: dict) -> dict | None:
    """Validate extracted dates."""
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
    
    # Accept if we got spring break OR first+last day
    if 'spring_break_start' in validated or ('first_day' in validated and 'last_day' in validated):
        validated['school_year'] = '2025-2026'
        return validated
    
    return None


def generate_slug_variants(name: str, state: str) -> list[str]:
    """Generate possible URL slug variants for a district name."""
    slugs = []
    
    # Raw district name to slug
    raw_slug = district_to_slug(name)
    if raw_slug:
        slugs.append(raw_slug)
    
    # Try with common suffixes
    name_lower = name.lower().strip()
    
    # Strip trailing numbers like "District #1" -> just the name
    cleaned = re.sub(r'\s*#?\d+\s*$', '', name_lower)
    cleaned = re.sub(r'\s*(school|schools)?\s*(district|sd|isd|usd|cusd|csd)\s*#?\d*\s*$', '', cleaned, flags=re.I)
    
    # Add "-district" suffix variant
    base_slug = re.sub(r'[^a-z0-9\s-]', '', cleaned)
    base_slug = re.sub(r'\s+', '-', base_slug.strip())
    base_slug = re.sub(r'-+', '-', base_slug).strip('-')
    
    if base_slug and base_slug not in slugs:
        slugs.append(base_slug)
    if base_slug:
        variants = [
            f"{base_slug}-district",
            f"{base_slug}-school-district",
            f"{base_slug}-public-schools",
            f"{base_slug}-schools",
        ]
        for v in variants:
            if v not in slugs:
                slugs.append(v)
    
    return slugs[:5]  # Max 5 variants


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-districts', type=int, default=0)
    parser.add_argument('--state', type=str, default='', help='Process only this state')
    parser.add_argument('--min-enrollment', type=int, default=0)
    args = parser.parse_args()
    
    log("=" * 70)
    log("StateSchools.us Bulk Scraper")
    log("=" * 70)
    
    if not ANTHROPIC_API_KEY:
        log("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)
    
    # Load districts
    with open(COMPREHENSIVE_FILE) as f:
        all_districts = list(csv.DictReader(f))
    
    medium = [r for r in all_districts if r['confidence'] == 'medium']
    medium.sort(key=lambda r: int(r.get('enrollment', 0) or 0), reverse=True)
    
    if args.state:
        medium = [r for r in medium if r['state'] == args.state.upper()]
    
    if args.min_enrollment:
        medium = [r for r in medium if int(r.get('enrollment', 0) or 0) >= args.min_enrollment]
    
    # Load existing results
    results = {}
    if args.resume and RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            results = json.load(f)
    
    done_ids = set(results.keys())
    to_process = [r for r in medium if r['nces_leaid'] not in done_ids]
    
    if args.max_districts:
        to_process = to_process[:args.max_districts]
    
    log(f"Medium districts: {len(medium)}")
    log(f"Already done: {len(done_ids)}")
    log(f"To process: {len(to_process)}")
    
    found = sum(1 for r in results.values() if r.get('status') == 'found')
    failed = sum(1 for r in results.values() if r.get('status') != 'found')
    url_cache = {}  # Cache 404s to avoid hitting them again
    
    for i, district in enumerate(to_process):
        nces_id = district['nces_leaid']
        name = district['district_name']
        state = district['state']
        enrollment = int(district.get('enrollment', 0) or 0)
        
        state_name = STATE_NAMES.get(state, '')
        if not state_name:
            log(f"[{i+1}/{len(to_process)}] {name} ({state}) — skipping, no state URL")
            results[nces_id] = {
                'name': name, 'state': state, 'enrollment': enrollment,
                'status': 'no_state_url',
                'timestamp': datetime.now().isoformat(),
            }
            failed += 1
            continue
        
        log(f"[{i+1}/{len(to_process)}] {name} ({state}) — {enrollment:,}")
        
        # Try slug variants
        slugs = generate_slug_variants(name, state)
        content = ""
        used_url = ""
        
        for slug in slugs:
            url = f"https://{state_name}schools.us/districts/{slug}/calendar/"
            if url in url_cache:
                continue
            
            fetched = web_fetch(url)
            time.sleep(REQUEST_DELAY)
            
            if fetched == "404":
                url_cache[url] = "404"
                continue
            
            if fetched and len(fetched) > 200 and ('2025' in fetched or '2026' in fetched or 'calendar' in fetched.lower()):
                content = fetched
                used_url = url
                break
        
        if not content:
            log(f"  ❌ no_content (tried: {slugs[:3]})")
            results[nces_id] = {
                'name': name, 'state': state, 'enrollment': enrollment,
                'status': 'no_content', 'slugs_tried': slugs[:3],
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
                    'status': 'found', 'method': 'stateschools_llm',
                    'url': used_url, 'dates': validated,
                    'timestamp': datetime.now().isoformat(),
                }
                found += 1
            else:
                log(f"  ❌ no_dates")
                results[nces_id] = {
                    'name': name, 'state': state, 'enrollment': enrollment,
                    'status': 'llm_no_dates', 'url': used_url,
                    'raw': str(raw_dates)[:200] if raw_dates else None,
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
