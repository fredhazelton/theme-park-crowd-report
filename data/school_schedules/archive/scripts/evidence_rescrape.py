#!/usr/bin/env python3
"""Evidence-Based Re-Scrape — Phase 1 Validation.

Re-scrapes a sample of flagged districts using a strict evidence-based prompt
that requires the LLM to quote actual text from the page. Compares results
against the original LLM scraper to measure hallucination rate.

This follows the PIPELINE_ARCHITECTURE.md Tier 1 (PDF-first) + Tier 2 (Claude smart search)
approach, with the district_profiles_schema.md intelligence capture built in.
"""

from __future__ import annotations
import argparse, csv, json, os, re, sys, time, random
import urllib.request, urllib.error, urllib.parse
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
RESULTS_FILE = BASE_DIR / "llm_scraper_results.json"
QUALITY_REPORT = BASE_DIR / "ssd_quality_report.json"
PROFILES_FILE = BASE_DIR / "district_profiles.json"
RESCRAPE_OUTPUT = BASE_DIR / "evidence_rescrape_results.json"
NCES_FILE = BASE_DIR / "nces_all_districts.csv"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")

BRAVE_DELAY = 1.1
REQUEST_DELAY = 0.3

# ── Evidence-Based Extraction Prompt ──────────────────────────────
# The key difference from the original: requires direct quotes from the page.
# If the LLM can't find the exact text, it MUST return not_found.

EVIDENCE_PROMPT = """You are extracting school calendar dates for {district_name} in {state} for the 2025-2026 school year.

You MUST follow these rules strictly:
1. ONLY extract dates that are EXPLICITLY stated in the content below.
2. For EACH date you extract, provide the EXACT QUOTE from the content that contains it.
3. If the content does not contain clear calendar dates for this specific district, return {{"status": "not_found", "reason": "explain why"}}.
4. Do NOT guess, infer, or use "typical" dates. If it's not written on the page, it's not found.
5. Check that the content is actually about {district_name} — not a different district.
6. Event feeds (sports, PTA meetings, concerts) are NOT school calendars. Ignore them.
7. If you see dates for a different school year (2024-2025, 2026-2027), ignore them.

Return ONLY valid JSON in this format:
{{
  "status": "found",
  "first_day": "YYYY-MM-DD or null",
  "last_day": "YYYY-MM-DD or null",
  "spring_break_start": "YYYY-MM-DD or null",
  "spring_break_end": "YYYY-MM-DD or null",
  "winter_break_start": "YYYY-MM-DD or null",
  "winter_break_end": "YYYY-MM-DD or null",
  "evidence": {{
    "first_day_quote": "exact text from page or null",
    "last_day_quote": "exact text from page or null",
    "spring_break_quote": "exact text from page or null",
    "winter_break_quote": "exact text from page or null"
  }},
  "source_type": "district_pdf | district_website | aggregator | other",
  "confidence": "high | medium | low",
  "notes": "any relevant context"
}}

OR if not found:
{{
  "status": "not_found",
  "reason": "brief explanation"
}}

Content from {url}:
{content}"""


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_nces_urls() -> dict:
    url_map = {}
    if NCES_FILE.exists():
        with open(NCES_FILE) as f:
            for r in csv.DictReader(f):
                if r.get('website'):
                    url_map[r['leaid']] = r['website']
    return url_map


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
        return [
            {'title': r.get('title', ''), 'url': r.get('url', ''), 'description': r.get('description', '')}
            for r in data.get('web', {}).get('results', [])
        ]
    except Exception as e:
        log(f"  Brave error: {e}")
        return []


def web_fetch(url: str, max_chars: int = 10000) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        content_type = resp.headers.get('Content-Type', '')
        if 'pdf' in content_type.lower():
            return "[PDF_DETECTED]"
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
        return text.strip()[:max_chars]
    except Exception:
        return ""


def fetch_pdf_text(url: str) -> str:
    """Download PDF and extract text via pdftotext (Tier 1 priority per methodology)."""
    import tempfile, subprocess
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp = urllib.request.urlopen(req, timeout=20)
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(resp.read(5_000_000))  # 5MB max
            tmp_path = f.name
        result = subprocess.run(
            ['pdftotext', '-layout', tmp_path, '-'],
            capture_output=True, text=True, timeout=30
        )
        os.unlink(tmp_path)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:12000]
    except Exception as e:
        log(f"  PDF fetch/extract error: {e}")
    return ""


def llm_extract_with_evidence(content: str, district_name: str, state: str, url: str) -> dict | None:
    """Use Claude Sonnet for evidence-based extraction."""
    if not ANTHROPIC_API_KEY or not content or len(content) < 50:
        return None

    prompt = EVIDENCE_PROMPT.format(
        district_name=district_name,
        state=state,
        url=url,
        content=content[:8000]
    )

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 600,
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
        json_match = re.search(r'\{.*\}', text, re.S)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        log(f"  LLM error: {e}")
    return None


def score_search_result(result: dict, district_name: str) -> int:
    """Score a search result per collection_methodology.md strategy."""
    score = 0
    url = result.get('url', '').lower()
    title = result.get('title', '').lower()
    desc = result.get('description', '').lower()

    # PDF bonus (Tier 1 priority)
    if url.endswith('.pdf') or 'pdf' in title:
        score += 4
    # Calendar in title
    if 'calendar' in title:
        score += 3
    # Year reference
    if '2025-2026' in title or '2025-2026' in desc:
        score += 3
    # Official domain
    if any(d in url for d in ['.gov', '.k12.', '.edu', 'schools.org']):
        score += 2
    # Known hosting platforms (district_profiles_schema.md)
    if any(p in url for p in ['finalsite', 'thrillshare', 'core-docs', 'myconnectsuite']):
        score += 2
    # District name in URL
    clean = district_name.lower().split()[0]
    if clean in url:
        score += 1
    # Penalty: aggregator sites (lower reliability per PIPELINE_ARCHITECTURE.md)
    if any(a in url for a in ['schools-calendar.com', 'educounty', 'schooldistrictcalendar']):
        score -= 2

    return score


def find_calendar_content(nces_id: str, name: str, state: str, nces_urls: dict) -> list[dict]:
    """Multi-strategy content fetch following collection_methodology.md.

    Returns list of {url, content, source_type, method} sorted by quality.
    """
    attempts = []

    # ── Strategy 1: PDF-first targeted search (Tier 1) ──
    clean_name = re.sub(r'\s*\(.*?\)', '', name)
    pdf_queries = [
        f'"{clean_name}" {state} 2025-2026 school calendar PDF',
        f'"{clean_name}" schools calendar 2025 2026 filetype:pdf',
    ]
    for query in pdf_queries:
        results = brave_search(query)
        time.sleep(BRAVE_DELAY)
        # Score and sort results per methodology
        scored = [(score_search_result(r, name), r) for r in results]
        scored.sort(key=lambda x: -x[0])

        for score, r in scored[:3]:
            url = r['url']
            if url.lower().endswith('.pdf') or 'pdf' in r.get('title', '').lower():
                content = fetch_pdf_text(url)
                if content and len(content) > 100:
                    attempts.append({
                        'url': url, 'content': content,
                        'source_type': 'district_pdf', 'method': 'brave_pdf_search',
                        'search_query': query, 'score': score
                    })
                    break  # Found a PDF, try extracting from it first
            time.sleep(REQUEST_DELAY)
        if attempts:
            break

    # ── Strategy 2: District website calendar page ──
    base_url = nces_urls.get(nces_id, "")
    if base_url:
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url
        base_url = base_url.rstrip('/')
        for path in ['/calendar', '/school-calendar', '/calendars', '']:
            try_url = base_url + path
            content = web_fetch(try_url)
            if content == "[PDF_DETECTED]":
                content = fetch_pdf_text(try_url)
                if content:
                    attempts.append({
                        'url': try_url, 'content': content,
                        'source_type': 'district_pdf', 'method': 'nces_url_pdf',
                        'score': 5
                    })
                    break
            elif content and len(content) > 200:
                if '2025' in content or '2026' in content or 'calendar' in content.lower():
                    attempts.append({
                        'url': try_url, 'content': content,
                        'source_type': 'district_website', 'method': 'nces_url_html',
                        'score': 3
                    })
                    break
            time.sleep(REQUEST_DELAY)

    # ── Strategy 3: General Brave search (Tier 2) ──
    if len(attempts) < 2:
        query = f'"{clean_name}" {state} school calendar 2025-2026'
        results = brave_search(query)
        time.sleep(BRAVE_DELAY)
        scored = [(score_search_result(r, name), r) for r in results]
        scored.sort(key=lambda x: -x[0])
        for score, r in scored[:2]:
            url = r['url']
            # Skip URLs we already fetched
            if any(a['url'] == url for a in attempts):
                continue
            content = web_fetch(url)
            if content and len(content) > 200:
                attempts.append({
                    'url': url, 'content': content,
                    'source_type': 'other', 'method': 'brave_general_search',
                    'search_query': query, 'score': score
                })
            time.sleep(REQUEST_DELAY)

    # Sort by score descending — try best sources first
    attempts.sort(key=lambda x: -x.get('score', 0))
    return attempts


def rescrape_district(nces_id: str, original: dict, nces_urls: dict) -> dict:
    """Re-scrape a single district with evidence-based extraction."""
    name = original.get('name', '')
    state = original.get('state', '')
    log(f"  Processing: {name} ({state}) [enrollment: {original.get('enrollment', '?')}]")

    # Find content from multiple sources
    sources = find_calendar_content(nces_id, name, state, nces_urls)

    if not sources:
        return {
            'status': 'not_found',
            'reason': 'no_content_fetched',
            'original_dates': original.get('dates', {}),
            'original_url': original.get('url', ''),
            'attempts': 0
        }

    # Try extraction on each source, best first
    for source in sources:
        extraction = llm_extract_with_evidence(
            source['content'], name, state, source['url']
        )
        if extraction and extraction.get('status') == 'found':
            return {
                'status': 'found',
                'dates': {
                    'first_day': extraction.get('first_day'),
                    'last_day': extraction.get('last_day'),
                    'spring_break_start': extraction.get('spring_break_start'),
                    'spring_break_end': extraction.get('spring_break_end'),
                    'winter_break_start': extraction.get('winter_break_start'),
                    'winter_break_end': extraction.get('winter_break_end'),
                },
                'evidence': extraction.get('evidence', {}),
                'confidence': extraction.get('confidence', 'medium'),
                'source_type': source['source_type'],
                'source_url': source['url'],
                'method': source['method'],
                'search_query': source.get('search_query'),
                'original_dates': original.get('dates', {}),
                'original_url': original.get('url', ''),
                'notes': extraction.get('notes', ''),
                'attempts': len(sources)
            }
        elif extraction and extraction.get('status') == 'not_found':
            log(f"    Source {source['url'][:60]}... → not_found: {extraction.get('reason', '')[:60]}")

    return {
        'status': 'not_found',
        'reason': 'no_evidence_found_in_any_source',
        'original_dates': original.get('dates', {}),
        'original_url': original.get('url', ''),
        'sources_tried': [s['url'] for s in sources],
        'attempts': len(sources)
    }


def select_sample(flagged: dict, results: dict, n: int = 50) -> list[tuple[str, dict]]:
    """Select a stratified sample of flagged districts.

    Strategy: pick from different duplicate patterns and different states
    to get a representative view of the hallucination problem.
    """
    # Group flagged by their date pattern
    from collections import defaultdict
    pattern_groups = defaultdict(list)
    for nces_id, info in flagged.items():
        entry = info.get('entry', results.get(nces_id, {}))
        dates = entry.get('dates', {})
        pattern = (dates.get('first_day'), dates.get('spring_break_start'))
        pattern_groups[pattern].append((nces_id, entry))

    # Sample from each pattern group, prioritizing larger enrollment
    sample = []
    patterns = list(pattern_groups.values())
    random.shuffle(patterns)

    idx = 0
    while len(sample) < n and idx < len(patterns) * 3:
        group = patterns[idx % len(patterns)]
        # Sort by enrollment descending within group
        group.sort(key=lambda x: x[1].get('enrollment', 0), reverse=True)
        pick_idx = idx // len(patterns)
        if pick_idx < len(group):
            sample.append(group[pick_idx])
        idx += 1

    return sample[:n]


def compare_results(original_dates: dict, new_dates: dict) -> dict:
    """Compare original vs re-scraped dates."""
    comparison = {}
    fields = ['first_day', 'last_day', 'spring_break_start', 'spring_break_end',
              'winter_break_start', 'winter_break_end']
    matches = 0
    total = 0
    for field in fields:
        orig = original_dates.get(field)
        new = new_dates.get(field)
        if orig or new:
            total += 1
            if orig == new:
                matches += 1
                comparison[field] = 'match'
            elif new is None:
                comparison[field] = 'new_is_null'
            elif orig is None:
                comparison[field] = 'orig_was_null'
            else:
                comparison[field] = f'mismatch: {orig} vs {new}'
    comparison['match_rate'] = matches / total if total > 0 else 0
    return comparison


def main():
    parser = argparse.ArgumentParser(description='Evidence-based re-scrape of flagged districts')
    parser.add_argument('--sample-size', '-n', type=int, default=50,
                        help='Number of flagged districts to re-scrape')
    parser.add_argument('--resume', action='store_true',
                        help='Resume from existing output file')
    args = parser.parse_args()

    log(f"=== Evidence-Based Re-Scrape — Phase 1 Validation ===")
    log(f"Sample size: {args.sample_size}")

    # Load data
    results = json.load(open(RESULTS_FILE))
    report = json.load(open(QUALITY_REPORT))
    flagged = report['flagged_entries']
    nces_urls = load_nces_urls()

    log(f"Loaded {len(results)} LLM results, {len(flagged)} flagged entries")

    # Resume support
    if args.resume and RESCRAPE_OUTPUT.exists():
        output = json.load(open(RESCRAPE_OUTPUT))
        done_ids = set(output.get('results', {}).keys())
        log(f"Resuming: {len(done_ids)} already done")
    else:
        output = {'results': {}, 'summary': {}, 'started': datetime.now().isoformat()}
        done_ids = set()

    # Select sample
    sample = select_sample(flagged, results, args.sample_size)
    sample = [(nid, entry) for nid, entry in sample if nid not in done_ids]
    log(f"Selected {len(sample)} districts to re-scrape (after excluding done)")

    # Process
    found = 0
    not_found = 0
    for i, (nces_id, original) in enumerate(sample):
        log(f"[{i+1}/{len(sample)}] {original.get('name', '?')} ({original.get('state', '?')})")

        result = rescrape_district(nces_id, original, nces_urls)
        output['results'][nces_id] = result

        if result['status'] == 'found':
            found += 1
            comp = compare_results(original.get('dates', {}), result.get('dates', {}))
            result['comparison'] = comp
            log(f"  ✅ FOUND — match_rate: {comp['match_rate']:.0%} | source: {result.get('method', '?')}")
        else:
            not_found += 1
            log(f"  ❌ NOT FOUND — {result.get('reason', '?')[:60]}")

        # Save periodically
        if (i + 1) % 5 == 0:
            output['summary'] = {
                'total': i + 1,
                'found': found,
                'not_found': not_found,
                'hallucination_rate': not_found / (i + 1),
                'updated': datetime.now().isoformat()
            }
            with open(RESCRAPE_OUTPUT, 'w') as f:
                json.dump(output, f, indent=2)
            log(f"  --- Progress: {found} found / {not_found} not_found / {i+1} total ({not_found/(i+1)*100:.0f}% hallucination rate) ---")

    # Final summary
    total = len(output['results'])
    found_total = sum(1 for r in output['results'].values() if r['status'] == 'found')
    not_found_total = total - found_total
    hallucination_rate = not_found_total / total if total > 0 else 0

    # Analyze match rates for found entries
    match_rates = [r['comparison']['match_rate'] for r in output['results'].values()
                   if r.get('comparison')]
    avg_match = sum(match_rates) / len(match_rates) if match_rates else 0

    output['summary'] = {
        'total': total,
        'found': found_total,
        'not_found': not_found_total,
        'hallucination_rate': hallucination_rate,
        'avg_date_match_rate': avg_match,
        'completed': datetime.now().isoformat()
    }

    with open(RESCRAPE_OUTPUT, 'w') as f:
        json.dump(output, f, indent=2)

    log(f"\n{'='*60}")
    log(f"PHASE 1 RESULTS:")
    log(f"  Total re-scraped:     {total}")
    log(f"  Found with evidence:  {found_total} ({found_total/total*100:.1f}%)")
    log(f"  NOT found (likely hallucinated): {not_found_total} ({hallucination_rate*100:.1f}%)")
    log(f"  Avg date match rate (when found): {avg_match*100:.1f}%")
    log(f"{'='*60}")
    log(f"Results saved to: {RESCRAPE_OUTPUT}")


if __name__ == '__main__':
    main()
