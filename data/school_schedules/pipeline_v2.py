#!/usr/bin/env python3
"""Production School Calendar Scraper Pipeline v2.

Three-tier evidence-based scraping strategy for ALL ~10,000 districts:
- Tier 1: PDF-first search (primary strategy)
- Tier 2: District website HTML (fallback)  
- Tier 3: Firecrawl for JS-rendered pages (final fallback)

Key improvements over v1:
- Evidence-based extraction (no hallucination)
- PDF-first priority per collection methodology
- Concurrency with rate limiting
- Resume support
- District profile intelligence updates
- Inline quality checks
- Cost tracking

Usage:
    python3 pipeline_v2.py                    # Process all districts
    python3 pipeline_v2.py --resume           # Resume from checkpoint
    python3 pipeline_v2.py --max-districts 100  # Test mode
"""

from __future__ import annotations
import argparse
import asyncio
import csv
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
import threading
import socket
import signal

# Global socket timeout — prevents any network call from hanging indefinitely
socket.setdefaulttimeout(30)

class DistrictTimeout(Exception):
    """Raised when a district takes too long to process."""
    pass

def _district_timeout_handler(signum, frame):
    raise DistrictTimeout("District processing timed out")

# Global rate limiter for Brave API — shared across all workers
_brave_lock = threading.Lock()
_brave_last_call = 0.0

# File paths
BASE_DIR = Path(__file__).parent
NCES_FILE = BASE_DIR / "nces_all_districts.csv"
PROFILES_FILE = BASE_DIR / "district_profiles.json"
RESULTS_FILE = BASE_DIR / "pipeline_v2_results.json"
LOG_FILE = BASE_DIR / "pipeline_v2.log"

# API keys
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")

# Config
MAX_WORKERS = 1  # Sequential processing — eliminates concurrency bugs, correct results first
BRAVE_RATE_LIMIT = 1.1  # seconds between Brave API calls
REQUEST_DELAY = 0.3     # seconds between general requests
SAVE_INTERVAL = 10      # Save results every N districts
MAX_PDF_SIZE = 5_000_000  # 5MB max PDF download
MAX_CONTENT_CHARS = 12000  # Max content to send to LLM

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Known JS platform domains for Tier 3 targeting
JS_PLATFORMS = {
    'finalsite.net', 'finalsite.com',
    'schoolwires.net', 'schoolwires.com', 
    'tandemapp.com',
    'edlio.com', 'edl.io',
    'thrillshare.com',
    'myconnectsuite.com'
}

# Evidence-based extraction prompt (from evidence_rescrape.py)
EVIDENCE_PROMPT = """You are extracting school calendar dates for {district_name} in {state}.

PRIORITY: 2025-2026 school year is preferred, but ANY valid school year is acceptable (2024-2025, 2026-2027, etc).

You MUST follow these rules strictly:
1. ONLY extract dates that are EXPLICITLY stated in the content below.
2. For EACH date you extract, provide the EXACT QUOTE from the content that contains it.
3. If the content does not contain clear calendar dates for this specific district, return {{"status": "not_found", "reason": "explain why"}}.
4. Do NOT guess, infer, or use "typical" dates. If it's not written on the page, it's not found.
5. Check that the content is actually about {district_name} — not a different district.
6. Event feeds (sports, PTA meetings, concerts) are NOT school calendars. Ignore them.
7. If the page has MULTIPLE school years, extract 2025-2026 first. If 2025-2026 is not available, extract the most recent year available.
8. ALWAYS specify which school year the dates are from in the "school_year" field.

Return ONLY valid JSON in this format:
{{
  "status": "found",
  "school_year": "YYYY-YYYY (e.g. 2025-2026 or 2024-2025)",
  "first_day": "YYYY-MM-DD or null",
  "last_day": "YYYY-MM-DD or null", 
  "spring_break_start": "YYYY-MM-DD or null",
  "spring_break_end": "YYYY-MM-DD or null",
  "winter_break_start": "YYYY-MM-DD or null",
  "winter_break_end": "YYYY-MM-DD or null",
  "thanksgiving_break_start": "YYYY-MM-DD or null",
  "thanksgiving_break_end": "YYYY-MM-DD or null",
  "fall_break_start": "YYYY-MM-DD or null",
  "fall_break_end": "YYYY-MM-DD or null",
  "other_breaks": [
    {{"name": "break name (e.g. Mardi Gras, Mid-Winter, Presidents Day)", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}
  ],
  "evidence": {{
    "first_day_quote": "exact text from page or null",
    "last_day_quote": "exact text from page or null",
    "spring_break_quote": "exact text from page or null", 
    "winter_break_quote": "exact text from page or null",
    "other_breaks_quote": "exact text for any additional breaks or null"
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


class CostTracker:
    """Track API costs across all services."""
    
    def __init__(self):
        self.brave_calls = 0
        self.anthropic_calls = 0
        self.anthropic_input_tokens = 0
        self.anthropic_output_tokens = 0
        self.firecrawl_calls = 0
        
    def log_brave_call(self):
        self.brave_calls += 1
        
    def log_anthropic_call(self, input_tokens: int = 0, output_tokens: int = 0):
        self.anthropic_calls += 1
        self.anthropic_input_tokens += input_tokens
        self.anthropic_output_tokens += output_tokens
        
    def log_firecrawl_call(self):
        self.firecrawl_calls += 1
        
    def get_summary(self) -> Dict[str, Any]:
        # Rough cost estimates based on current pricing
        anthropic_cost = (self.anthropic_input_tokens / 1000 * 0.003 + 
                         self.anthropic_output_tokens / 1000 * 0.015)
        brave_cost = self.brave_calls * 0.005  # ~$5 per 1000 searches
        firecrawl_cost = self.firecrawl_calls * 0.01  # ~$1 per 100 scrapes
        
        return {
            "brave_calls": self.brave_calls,
            "brave_estimated_cost": round(brave_cost, 2),
            "anthropic_calls": self.anthropic_calls,
            "anthropic_input_tokens": self.anthropic_input_tokens,
            "anthropic_output_tokens": self.anthropic_output_tokens,
            "anthropic_estimated_cost": round(anthropic_cost, 2),
            "firecrawl_calls": self.firecrawl_calls,
            "firecrawl_estimated_cost": round(firecrawl_cost, 2),
            "total_estimated_cost": round(anthropic_cost + brave_cost + firecrawl_cost, 2)
        }


class DistrictProcessor:
    """Process a single district through the three-tier strategy."""
    
    def __init__(self, cost_tracker: CostTracker, profiles: Dict, nces_urls: Dict):
        self.cost_tracker = cost_tracker
        self.profiles = profiles
        self.nces_urls = nces_urls
        
    def score_search_result(self, result: Dict, district_name: str) -> int:
        """Score a search result per collection_methodology.md strategy.
        
        Score results: PDFs +4, "calendar" in title +3, "2025-2026" +3, .gov domains +2
        """
        score = 0
        url = result.get('url', '').lower()
        title = result.get('title', '').lower()
        desc = result.get('description', '').lower()
        combined = url + ' ' + title + ' ' + desc
        
        # PDF bonus (Tier 1 priority) — "PDFs are gold"
        if url.endswith('.pdf') or 'pdf' in title:
            score += 4
        # Calendar-specific terms in title (strong signal)
        if any(t in title for t in ['student calendar', 'school calendar', 'academic calendar', 'school year calendar']):
            score += 5  # Stronger than generic "calendar"
        elif 'calendar' in title:
            score += 3
        # Year reference
        if '2025-2026' in combined or ('2025' in combined and '2026' in combined):
            score += 3
        # Official domain — from district_profiles_schema.md hosting patterns
        if any(d in url for d in ['.k12.', '.edu']):
            score += 3  # District's own domain is best
        elif '.gov' in url:
            score += 2
        # Known hosting platforms — from district_profiles_schema.md
        if any(p in url for p in ['finalsite', 'thrillshare', 'core-docs', 'myconnectsuite',
                                   'campussuite', 'sharpschool', 'edl.io']):
            score += 2
        # District name in URL (confirms it's the right district)
        clean = re.sub(r'[^a-z]', '', district_name.lower().split()[0])
        if len(clean) > 3 and clean in url:
            score += 2
        # Penalty: aggregator sites (Tier 3 reliability per PIPELINE_ARCHITECTURE.md)
        if any(a in url for a in ['schools-calendar.com', 'educounty', 'schooldistrictcalendar',
                                   'niche.com', 'greatschools.org', 'usnews.com']):
            score -= 3
        # Penalty: definitely-not-calendar content
        if any(t in combined for t in ['salary', 'handbook', 'budget', 'employment',
                                        'nces.ed.gov', 'census.gov']):
            score -= 5
            
        return score
        
    def brave_search(self, query: str) -> List[Dict]:
        """Search Brave with global rate limiting across all workers."""
        global _brave_last_call
        if not BRAVE_API_KEY:
            return []
        
        # Global rate limit: wait until 1.1s since last Brave call across ALL workers
        with _brave_lock:
            now = time.time()
            elapsed = now - _brave_last_call
            if elapsed < BRAVE_RATE_LIMIT:
                time.sleep(BRAVE_RATE_LIMIT - elapsed)
            _brave_last_call = time.time()
            
        params = urllib.parse.urlencode({'q': query, 'count': 5})
        url = f"https://api.search.brave.com/res/v1/web/search?{params}"
        req = urllib.request.Request(url, headers={
            'Accept': 'application/json',
            'X-Subscription-Token': BRAVE_API_KEY,
        })
        
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            self.cost_tracker.log_brave_call()
            
            return [
                {
                    'title': r.get('title', ''),
                    'url': r.get('url', ''),
                    'description': r.get('description', '')
                }
                for r in data.get('web', {}).get('results', [])
            ]
        except Exception as e:
            logger.warning(f"Brave search error: {e}")
            return []
            
    def fetch_pdf_text(self, url: str) -> str:
        """Download PDF and extract text via pdftotext."""
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            resp = urllib.request.urlopen(req, timeout=20)
            
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
                f.write(resp.read(MAX_PDF_SIZE))
                tmp_path = f.name
                
            result = subprocess.run(
                ['pdftotext', '-layout', tmp_path, '-'],
                capture_output=True, text=True, timeout=30
            )
            os.unlink(tmp_path)
            
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout[:MAX_CONTENT_CHARS]
                
        except Exception as e:
            logger.debug(f"PDF fetch/extract error: {e}")
            
        return ""
        
    def web_fetch(self, url: str) -> str:
        """Simple web fetch for HTML content."""
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
                
            raw = resp.read(MAX_CONTENT_CHARS * 2)
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = raw.decode('latin-1')
                
            # Basic HTML cleaning
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S)
            text = re.sub(r'<[^>]+>', '\n', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = re.sub(r'&amp;', '&', text)
            text = re.sub(r'&nbsp;', ' ', text)
            text = re.sub(r'&#\d+;', '', text)
            
            return text.strip()[:MAX_CONTENT_CHARS]
            
        except Exception as e:
            logger.debug(f"Web fetch error: {e}")
            return ""
            
    def firecrawl_scrape(self, url: str) -> str:
        """Firecrawl scrape for JS-rendered pages."""
        if not FIRECRAWL_API_KEY:
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
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read())
            self.cost_tracker.log_firecrawl_call()
            
            if result.get("success"):
                md = result.get("data", {}).get("markdown", "")
                return md[:MAX_CONTENT_CHARS]
                
        except Exception as e:
            logger.debug(f"Firecrawl error: {e}")
            
        return ""
        
    def llm_extract_with_evidence(self, content: str, district_name: str, state: str, url: str) -> Optional[Dict]:
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
            self.cost_tracker.log_anthropic_call()
            
            text = result.get("content", [{}])[0].get("text", "")
            json_match = re.search(r'\{.*\}', text, re.S)
            
            if json_match:
                return json.loads(json_match.group())
                
        except Exception as e:
            logger.debug(f"LLM extraction error: {e}")
            
        return None
        
    def is_js_platform(self, url: str) -> bool:
        """Check if URL is from a known JS platform."""
        return any(platform in url.lower() for platform in JS_PLATFORMS)
        
    def _is_wrong_pdf(self, url: str, title: str) -> bool:
        """Filter out non-calendar PDFs per collection_methodology.md lessons."""
        lower_url = url.lower()
        lower_title = title.lower()
        combined = lower_url + ' ' + lower_title
        # Reject: salary schedules, handbooks, budgets, reports, applications
        reject_terms = ['salary', 'handbook', 'budget', 'financial', 'application',
                        'employment', 'job', 'bid', 'contract', 'audit', 'meal',
                        'nutrition', 'transportation', 'bus route', 'supply list',
                        'dress code', 'enrollment form', 'registration form']
        return any(term in combined for term in reject_terms)

    def tier1_pdf_search(self, district_name: str, state: str) -> List[Dict]:
        """Tier 1: PDF-first search strategy per collection_methodology.md.
        
        Search Strategy (from manual review lessons):
        1. Search Brave: "[District Name]" "2025-2026" school calendar
        2. Search Brave: "[District Name]" school district first day of school 2025
        3. Score results: PDFs +4, "calendar" in title +3, "2025-2026" +3, .gov +2
        4. Fetch top 3 results (PDF via pdftotext locally, HTML via basic fetch)
        """
        attempts = []
        clean_name = re.sub(r'\s*\(.*?\)', '', district_name)
        
        # Multiple search queries — per methodology doc + improvements
        # Primary: 2025-2026, but also accept other years
        queries = [
            f'"{clean_name}" "2025-2026" school calendar',
            f'"{clean_name}" {state} student calendar 2025-2026 PDF',
            f'"{clean_name}" school district calendar PDF',
        ]
        
        seen_urls = set()
        
        for query in queries:
            results = self.brave_search(query)
            
            # Score and sort results
            scored = [(self.score_search_result(r, district_name), r) for r in results]
            scored.sort(key=lambda x: -x[0])
            
            for score, result in scored[:3]:
                url = result['url']
                title = result.get('title', '')
                
                # Skip duplicates
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                
                # Skip obviously wrong PDFs
                if self._is_wrong_pdf(url, title):
                    logger.debug(f"    Skipping non-calendar PDF: {title[:60]}")
                    continue
                
                # Try PDFs
                if url.lower().endswith('.pdf') or 'pdf' in title.lower():
                    content = self.fetch_pdf_text(url)
                    if content and len(content) > 100:
                        attempts.append({
                            'url': url,
                            'content': content,
                            'source_type': 'district_pdf',
                            'method': 'tier1_pdf_search',
                            'search_query': query,
                            'score': score
                        })
                        # Try up to 3 PDFs total (don't stop at first hit)
                        if len(attempts) >= 3:
                            return attempts
                        
                time.sleep(REQUEST_DELAY)
                
            # If we already have good candidates, don't burn more searches
            if len(attempts) >= 2:
                break
                
        return attempts
        
    def tier2_district_website(self, nces_id: str, district_name: str) -> List[Dict]:
        """Tier 2: District website HTML search."""
        attempts = []
        base_url = self.nces_urls.get(nces_id, "")
        
        if not base_url:
            return attempts
            
        # Normalize URL
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url
        base_url = base_url.rstrip('/')
        
        # Try calendar page paths
        for path in ['/calendar', '/school-calendar', '/calendars', '']:
            try_url = base_url + path
            content = self.web_fetch(try_url)
            
            if content == "[PDF_DETECTED]":
                # Found a PDF at the calendar page
                content = self.fetch_pdf_text(try_url)
                if content:
                    attempts.append({
                        'url': try_url,
                        'content': content,
                        'source_type': 'district_pdf',
                        'method': 'tier2_website_pdf',
                        'score': 5
                    })
                    return attempts
                    
            elif content and len(content) > 200:
                # Check if content is relevant
                if ('2025' in content or '2026' in content or 
                    'calendar' in content.lower()):
                    attempts.append({
                        'url': try_url,
                        'content': content,
                        'source_type': 'district_website',
                        'method': 'tier2_website_html',
                        'score': 3
                    })
                    return attempts
                    
            time.sleep(REQUEST_DELAY)
            
        return attempts
        
    def tier3_firecrawl_js(self, nces_id: str, district_name: str, state: str) -> List[Dict]:
        """Tier 3: Firecrawl for known JS platforms."""
        attempts = []
        base_url = self.nces_urls.get(nces_id, "")
        
        # Only use Firecrawl if district is on known JS platform
        if not base_url or not self.is_js_platform(base_url):
            return attempts
            
        # Normalize URL
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url
        base_url = base_url.rstrip('/')
        
        # Try calendar page with Firecrawl
        try_url = base_url + '/calendar'
        content = self.firecrawl_scrape(try_url)
        
        if content and len(content) > 200:
            attempts.append({
                'url': try_url,
                'content': content,
                'source_type': 'district_website',
                'method': 'tier3_firecrawl',
                'score': 2
            })
            
        return attempts
        
    def update_district_profile(self, nces_id: str, district: Dict, attempts: List[Dict], 
                              result: Dict, tier_used: str):
        """Update district profile with collection intelligence."""
        profile = self.profiles.get(nces_id, {
            'nces_id': nces_id,
            'name': district['lea_name'],
            'state': district['st'],
            'sources': [],
            'failed_sources': [],
            'search_strategies': {'queries_tried': []},
            'collection_history': {}
        })
        
        # Update search queries tried
        for attempt in attempts:
            if 'search_query' in attempt:
                query = attempt['search_query']
                if query not in profile['search_strategies']['queries_tried']:
                    profile['search_strategies']['queries_tried'].append(query)
                    
        # Record successful source
        if result['status'] == 'found':
            source_record = {
                'url': result['source_url'],
                'type': 'pdf' if 'pdf' in result['source_type'] else 'html',
                'method': result.get('method', tier_used),
                'school_year': result.get('school_year', '2025-2026'),
                'quality': result.get('confidence', 'medium'),
                'last_checked': datetime.now().isoformat()
            }
            profile['sources'].append(source_record)
            
            # Update collection history
            detected_year = result.get('school_year', '2025-2026')
            profile['collection_history'][detected_year] = {
                'dates': result['dates'],
                'confidence': result.get('confidence', 'medium'),
                'tier_used': tier_used,
                'collected_date': datetime.now().isoformat()
            }
        else:
            # Record failed attempts
            for attempt in attempts:
                failed_record = {
                    'url': attempt['url'],
                    'reason': 'no_evidence_found',
                    'attempted': datetime.now().isoformat()
                }
                profile['failed_sources'].append(failed_record)
                
        # Detect hosting platform
        if result.get('source_url'):
            url = result['source_url'].lower()
            for platform in JS_PLATFORMS:
                if platform in url:
                    profile['website'] = profile.get('website', {})
                    profile['website']['platform'] = platform.split('.')[0]
                    break
                    
        self.profiles[nces_id] = profile
        
    def _has_minimum_data(self, extraction: Dict) -> bool:
        """Check if extraction has enough useful data to count as 'found'.
        
        Must have at least: spring_break dates OR (first_day + last_day).
        Winter break alone is not enough commercial value.
        """
        if not extraction or extraction.get('status') != 'found':
            return False
        has_spring = extraction.get('spring_break_start') and extraction.get('spring_break_end')
        has_year = extraction.get('first_day') and extraction.get('last_day')
        return has_spring or has_year

    def process_district(self, district: Dict) -> Dict:
        """Process a single district through all tiers."""
        nces_id = district['leaid']
        name = district['lea_name']
        state = district.get('st') or district.get('state', 'XX')
        
        if not state or len(state) > 2:
            logger.warning(f"  Skipping {name} — no valid state code")
            return {
                'status': 'error', 'name': name, 'state': state,
                'error': 'no_valid_state_code', 'timestamp': datetime.now().isoformat()
            }
        
        logger.info(f"Processing: {name} ({state})")
        
        # Hard 90-second timeout per district (signal-based, works even when urllib hangs)
        old_handler = signal.signal(signal.SIGALRM, _district_timeout_handler)
        signal.alarm(90)
        try:
            return self._process_district_inner(district)
        except DistrictTimeout:
            logger.warning(f"  ⏰ TIMEOUT: {name} ({state}) — skipping after 90s")
            return {
                'status': 'not_found', 'name': name, 'state': state,
                'error': 'timeout', 'search_queries_tried': [],
                'urls_tried': [], 'timestamp': datetime.now().isoformat()
            }
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    def _process_district_inner(self, district: Dict) -> Dict:
        """Inner processing logic (called with alarm set)."""
        nces_id = district['leaid']
        name = district['lea_name']
        state = district.get('st') or district.get('state', 'XX')
        
        all_attempts = []
        urls_tried = []
        queries_tried = []
        
        # Tier 1: PDF-first search
        tier1_attempts = self.tier1_pdf_search(name, state)
        all_attempts.extend(tier1_attempts)
        
        if tier1_attempts:
            for attempt in tier1_attempts:
                urls_tried.append(attempt['url'])
                if 'search_query' in attempt:
                    queries_tried.append(attempt['search_query'])
                    
            # Try extraction on Tier 1 results
            for attempt in tier1_attempts:
                extraction = self.llm_extract_with_evidence(
                    attempt['content'], name, state, attempt['url']
                )
                
                if extraction and self._has_minimum_data(extraction):
                    result = {
                        'status': 'found',
                        'name': name,
                        'state': state,
                        'enrollment': None,  # Add from NCES if available
                        'tier_used': 'tier1_pdf',
                        'dates': {
                            'first_day': extraction.get('first_day'),
                            'last_day': extraction.get('last_day'),
                            'spring_break_start': extraction.get('spring_break_start'),
                            'spring_break_end': extraction.get('spring_break_end'),
                            'winter_break_start': extraction.get('winter_break_start'),
                            'winter_break_end': extraction.get('winter_break_end'),
                            'thanksgiving_break_start': extraction.get('thanksgiving_break_start'),
                            'thanksgiving_break_end': extraction.get('thanksgiving_break_end'),
                            'fall_break_start': extraction.get('fall_break_start'),
                            'fall_break_end': extraction.get('fall_break_end'),
                            'other_breaks': extraction.get('other_breaks', []),
                        },
                        'evidence': extraction.get('evidence', {}),
                        'source_url': attempt['url'],
                        'source_type': attempt['source_type'],
                        'confidence': extraction.get('confidence', 'medium'),
                        'school_year': extraction.get('school_year', '2025-2026'),
                        'search_queries_tried': queries_tried,
                        'urls_tried': urls_tried,
                        'firecrawl_used': False,
                        'method': attempt['method'],
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    # Update district profile
                    self.update_district_profile(nces_id, district, all_attempts, result, 'tier1_pdf')
                    
                    return result
                    
        # Tier 2: District website HTML
        tier2_attempts = self.tier2_district_website(nces_id, name)
        all_attempts.extend(tier2_attempts)
        
        if tier2_attempts:
            for attempt in tier2_attempts:
                urls_tried.append(attempt['url'])
                
                extraction = self.llm_extract_with_evidence(
                    attempt['content'], name, state, attempt['url']
                )
                
                if extraction and self._has_minimum_data(extraction):
                    result = {
                        'status': 'found',
                        'name': name,
                        'state': state,
                        'enrollment': None,
                        'tier_used': 'tier2_html',
                        'dates': {
                            'first_day': extraction.get('first_day'),
                            'last_day': extraction.get('last_day'),
                            'spring_break_start': extraction.get('spring_break_start'),
                            'spring_break_end': extraction.get('spring_break_end'),
                            'winter_break_start': extraction.get('winter_break_start'),
                            'winter_break_end': extraction.get('winter_break_end'),
                            'thanksgiving_break_start': extraction.get('thanksgiving_break_start'),
                            'thanksgiving_break_end': extraction.get('thanksgiving_break_end'),
                            'fall_break_start': extraction.get('fall_break_start'),
                            'fall_break_end': extraction.get('fall_break_end'),
                            'other_breaks': extraction.get('other_breaks', []),
                        },
                        'evidence': extraction.get('evidence', {}),
                        'source_url': attempt['url'],
                        'source_type': attempt['source_type'],
                        'confidence': extraction.get('confidence', 'medium'),
                        'school_year': extraction.get('school_year', '2025-2026'),
                        'search_queries_tried': queries_tried,
                        'urls_tried': urls_tried,
                        'firecrawl_used': False,
                        'method': attempt['method'],
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    self.update_district_profile(nces_id, district, all_attempts, result, 'tier2_html')
                    
                    return result
                    
        # Tier 3: Firecrawl for JS platforms
        tier3_attempts = self.tier3_firecrawl_js(nces_id, name, state)
        all_attempts.extend(tier3_attempts)
        
        if tier3_attempts:
            for attempt in tier3_attempts:
                urls_tried.append(attempt['url'])
                
                extraction = self.llm_extract_with_evidence(
                    attempt['content'], name, state, attempt['url']
                )
                
                if extraction and self._has_minimum_data(extraction):
                    result = {
                        'status': 'found',
                        'name': name,
                        'state': state,
                        'enrollment': None,
                        'tier_used': 'tier3_firecrawl',
                        'dates': {
                            'first_day': extraction.get('first_day'),
                            'last_day': extraction.get('last_day'),
                            'spring_break_start': extraction.get('spring_break_start'),
                            'spring_break_end': extraction.get('spring_break_end'),
                            'winter_break_start': extraction.get('winter_break_start'),
                            'winter_break_end': extraction.get('winter_break_end'),
                            'thanksgiving_break_start': extraction.get('thanksgiving_break_start'),
                            'thanksgiving_break_end': extraction.get('thanksgiving_break_end'),
                            'fall_break_start': extraction.get('fall_break_start'),
                            'fall_break_end': extraction.get('fall_break_end'),
                            'other_breaks': extraction.get('other_breaks', []),
                        },
                        'evidence': extraction.get('evidence', {}),
                        'source_url': attempt['url'],
                        'source_type': attempt['source_type'],
                        'confidence': extraction.get('confidence', 'medium'),
                        'school_year': extraction.get('school_year', '2025-2026'),
                        'search_queries_tried': queries_tried,
                        'urls_tried': urls_tried,
                        'firecrawl_used': True,
                        'method': attempt['method'],
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    self.update_district_profile(nces_id, district, all_attempts, result, 'tier3_firecrawl')
                    
                    return result
                    
        # No extraction succeeded
        result = {
            'status': 'not_found',
            'name': name,
            'state': state,
            'enrollment': None,
            'tier_used': None,
            'dates': None,
            'evidence': None,
            'source_url': None,
            'source_type': None,
            'confidence': None,
            'search_queries_tried': queries_tried,
            'urls_tried': urls_tried,
            'firecrawl_used': len(tier3_attempts) > 0,
            'attempts': len(all_attempts),
            'timestamp': datetime.now().isoformat()
        }
        
        # Update district profile with failed attempt
        self.update_district_profile(nces_id, district, all_attempts, result, None)
        
        return result


def load_nces_districts() -> List[Dict]:
    """Load regular public school districts from NCES data."""
    districts = []
    with open(NCES_FILE) as f:
        for row in csv.DictReader(f):
            # Only include regular public school districts
            if 'Regular' not in row.get('lea_type', ''):
                continue
            # Fix state field — use 'state' if 'st' is empty
            if not row.get('st') and row.get('state'):
                # state might be full name or abbreviation
                state_val = row['state'].strip()
                if len(state_val) == 2:
                    row['st'] = state_val.upper()
                else:
                    # Map full names to abbreviations
                    STATE_ABBREVS = {
                        'ALABAMA':'AL','ALASKA':'AK','ARIZONA':'AZ','ARKANSAS':'AR','CALIFORNIA':'CA',
                        'COLORADO':'CO','CONNECTICUT':'CT','DELAWARE':'DE','FLORIDA':'FL','GEORGIA':'GA',
                        'HAWAII':'HI','IDAHO':'ID','ILLINOIS':'IL','INDIANA':'IN','IOWA':'IA',
                        'KANSAS':'KS','KENTUCKY':'KY','LOUISIANA':'LA','MAINE':'ME','MARYLAND':'MD',
                        'MASSACHUSETTS':'MA','MICHIGAN':'MI','MINNESOTA':'MN','MISSISSIPPI':'MS',
                        'MISSOURI':'MO','MONTANA':'MT','NEBRASKA':'NE','NEVADA':'NV',
                        'NEW HAMPSHIRE':'NH','NEW JERSEY':'NJ','NEW MEXICO':'NM','NEW YORK':'NY',
                        'NORTH CAROLINA':'NC','NORTH DAKOTA':'ND','OHIO':'OH','OKLAHOMA':'OK',
                        'OREGON':'OR','PENNSYLVANIA':'PA','RHODE ISLAND':'RI','SOUTH CAROLINA':'SC',
                        'SOUTH DAKOTA':'SD','TENNESSEE':'TN','TEXAS':'TX','UTAH':'UT','VERMONT':'VT',
                        'VIRGINIA':'VA','WASHINGTON':'WA','WEST VIRGINIA':'WV','WISCONSIN':'WI',
                        'WYOMING':'WY','DISTRICT OF COLUMBIA':'DC',
                    }
                    row['st'] = STATE_ABBREVS.get(state_val.upper(), state_val[:2].upper())
            districts.append(row)
    return districts


def load_nces_urls() -> Dict[str, str]:
    """Load NCES website URLs."""
    url_map = {}
    if NCES_FILE.exists():
        with open(NCES_FILE) as f:
            for r in csv.DictReader(f):
                if r.get('website'):
                    url_map[r['leaid']] = r['website']
    return url_map


def load_profiles() -> Dict[str, Any]:
    """Load district profiles."""
    if PROFILES_FILE.exists():
        with open(PROFILES_FILE) as f:
            return json.load(f)
    return {}


def save_profiles(profiles: Dict[str, Any]):
    """Save district profiles."""
    with open(PROFILES_FILE, 'w') as f:
        json.dump(profiles, f, indent=2)


def load_results() -> Dict[str, Any]:
    """Load existing results."""
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return {}


def save_results(results: Dict[str, Any]):
    """Save results to JSON."""
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)


def run_quality_check(district_result: Dict) -> List[str]:
    """Run inline quality checks on a district result.
    
    Accepts ANY valid school year (2024-2025, 2025-2026, 2026-2027).
    Only flags truly implausible dates or hallucination signals.
    """
    flags = []
    
    if district_result['status'] != 'found':
        return flags
        
    dates = district_result.get('dates', {})
    school_year = district_result.get('school_year', '2025-2026')
    
    # Determine expected year ranges based on school_year
    try:
        start_year = int(school_year.split('-')[0])
        end_year = int(school_year.split('-')[1])
    except (ValueError, IndexError, AttributeError):
        start_year, end_year = 2025, 2026
    
    # Check date plausibility for the detected school year
    try:
        if dates.get('first_day'):
            first_day = date.fromisoformat(dates['first_day'])
            # First day should be Jul-Oct of start year
            if not (date(start_year, 7, 1) <= first_day <= date(start_year, 10, 15)):
                flags.append(f'implausible_first_day_for_{school_year}')
                
        if dates.get('last_day'):
            last_day = date.fromisoformat(dates['last_day'])
            # Last day should be Apr-Jul of end year
            if not (date(end_year, 4, 15) <= last_day <= date(end_year, 7, 15)):
                flags.append(f'implausible_last_day_for_{school_year}')
                
        if dates.get('spring_break_start'):
            sb = date.fromisoformat(dates['spring_break_start'])
            # Spring break should be Feb-May of end year
            if not (date(end_year, 2, 1) <= sb <= date(end_year, 5, 31)):
                flags.append(f'implausible_spring_break_for_{school_year}')
                
    except (ValueError, TypeError):
        flags.append('invalid_date_format')
    
    # Flag duplicate "hallucination" patterns — same spring break for 5+ districts
    # (This is checked at batch level, not here)
        
    return flags


# Unused functions removed - batch QA logic is integrated directly in main()


# Functions removed - batch processing integrated directly in main() for simplicity


def main():
    parser = argparse.ArgumentParser(description='Production School Calendar Pipeline v2')
    parser.add_argument('--resume', action='store_true', help='Resume from checkpoint')
    parser.add_argument('--max-districts', type=int, default=0, help='Max districts to process (0=all)')
    parser.add_argument('--min-enrollment', type=int, default=0, help='Minimum enrollment threshold')
    parser.add_argument('--test-mode', action='store_true', help='Test mode with limited districts')
    parser.add_argument('--batch-size', type=int, default=100, help='Process districts in batches of N')
    parser.add_argument('--no-auto-qa', action='store_true', help='Disable automatic quality checks after each batch')
    parser.add_argument('--no-halt-on-fail', action='store_true', help='Continue pipeline even if quality issues detected')
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("Production School Calendar Scraper Pipeline v2")
    logger.info("=" * 70)
    
    # Check API keys
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set")
        return 1
    if not BRAVE_API_KEY:
        logger.warning("BRAVE_SEARCH_API_KEY not set - search will be limited")
    if not FIRECRAWL_API_KEY:
        logger.warning("FIRECRAWL_API_KEY not set - Tier 3 disabled")
        
    # Load data
    logger.info("Loading districts and existing data...")
    all_districts = load_nces_districts()
    nces_urls = load_nces_urls()
    profiles = load_profiles()
    
    # Enrich districts with enrollment from profiles/LLM scraper results
    llm_results = {}
    llm_results_path = BASE_DIR / "llm_scraper_results.json"
    if llm_results_path.exists():
        with open(llm_results_path) as f:
            llm_results = json.load(f)
    
    for d in all_districts:
        nid = d['leaid']
        enrollment = 0
        if nid in profiles and profiles[nid].get('enrollment'):
            enrollment = profiles[nid]['enrollment']
        elif nid in llm_results and llm_results[nid].get('enrollment'):
            enrollment = llm_results[nid]['enrollment']
        d['enrollment'] = enrollment or 0
    
    # Filter and prioritize districts
    districts = all_districts
    if args.min_enrollment:
        districts = [d for d in districts if d.get('enrollment', 0) >= args.min_enrollment]
        
    # Sort by enrollment descending (biggest = most commercial value first)
    districts.sort(key=lambda d: d.get('enrollment', 0), reverse=True)
    
    if args.max_districts:
        districts = districts[:args.max_districts]
        
    if args.test_mode:
        districts = districts[:50]
        
    logger.info(f"Total districts to process: {len(districts)}")
    
    # Load existing results for resume
    if args.resume:
        results = load_results()
        done_ids = set(results.keys())
        districts = [d for d in districts if d['leaid'] not in done_ids]
        logger.info(f"Resume mode: {len(done_ids)} already done, {len(districts)} remaining")
    else:
        results = {}
        
    if not districts:
        logger.info("No districts to process!")
        return 0
        
    # Initialize tracking
    cost_tracker = CostTracker()
    stats = defaultdict(int)
    batch_size = args.batch_size
    
    # Split districts into batches
    batches = [districts[i:i + batch_size] for i in range(0, len(districts), batch_size)]
    logger.info(f"Processing {len(districts)} districts in {len(batches)} batches of {batch_size}")
    auto_qa = not args.no_auto_qa
    halt_on_fail = not args.no_halt_on_fail
    logger.info(f"Workers: {MAX_WORKERS} | Auto-QA: {auto_qa} | Halt-on-fail: {halt_on_fail}")
    
    total_processed = 0
    pipeline_halted = False
    
    for batch_num, batch in enumerate(batches, 1):
        logger.info("")
        logger.info(f"{'='*60}")
        logger.info(f"BATCH {batch_num}/{len(batches)} — {len(batch)} districts")
        logger.info(f"{'='*60}")
        
        batch_results = {}
        batch_stats = defaultdict(int)
        
        processor = DistrictProcessor(cost_tracker, profiles, nces_urls)
        for district in batch:
                nces_id = district['leaid']
                
                try:
                    result = processor.process_district(district)
                    results[nces_id] = result
                    batch_results[nces_id] = result
                    
                    # Update stats
                    stats[result['status']] += 1
                    batch_stats[result['status']] += 1
                    if result['status'] == 'found':
                        stats[f"tier_{result['tier_used']}"] += 1
                        batch_stats[f"tier_{result['tier_used']}"] += 1
                        
                    # Run inline quality checks
                    quality_flags = run_quality_check(result)
                    if quality_flags:
                        result['quality_flags'] = quality_flags
                        stats['quality_flagged'] += 1
                        batch_stats['quality_flagged'] += 1
                        
                    total_processed += 1
                    
                    # Logging
                    if result['status'] == 'found':
                        logger.info(f"  ✅ {district['lea_name']} ({district['st']}) — {result['tier_used']}")
                    else:
                        logger.info(f"  ❌ {district['lea_name']} ({district['st']}) — {result['status']}")
                        
                    # Periodic saves within batch
                    if total_processed % SAVE_INTERVAL == 0:
                        save_results(results)
                        save_profiles(profiles)
                        
                except Exception as e:
                    logger.error(f"  Error processing {district['lea_name']}: {e}")
                    results[nces_id] = {
                        'status': 'error',
                        'name': district['lea_name'],
                        'state': district['st'],
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    }
                    stats['error'] += 1
                    batch_stats['error'] += 1
                    total_processed += 1
        
        # ── BATCH QA GATE ──────────────────────────────────────────────
        save_results(results)
        save_profiles(profiles)
        
        batch_total = len(batch_results)
        batch_found = batch_stats.get('found', 0)
        batch_not_found = batch_stats.get('not_found', 0)
        batch_flagged = batch_stats.get('quality_flagged', 0)
        
        # Skip QA analysis if disabled
        if not auto_qa:
            logger.info(f"Batch {batch_num} complete: {batch_found} found, {batch_not_found} not found (QA disabled)")
            continue
        
        # Duplicate detection within this batch
        from collections import Counter as _Counter
        date_patterns = _Counter()
        for r in batch_results.values():
            if r.get('status') == 'found' and r.get('dates'):
                d = r['dates']
                pattern = (d.get('first_day'), d.get('spring_break_start'), d.get('last_day'))
                date_patterns[pattern] += 1
        
        # Exclude null patterns — (None, None, None) is just missing data, not hallucination
        duplicate_patterns = {p: c for p, c in date_patterns.items() 
                             if c >= 5 and any(v is not None for v in p)}
        # Quality score measures data ACCURACY (of found entries), not find rate
        # Quality = (clean found entries) / (total found entries)
        # Find rate is reported separately
        if batch_found > 0:
            bad_found = len(duplicate_patterns) * 5 + batch_flagged
            batch_quality_score = max(0, (batch_found - bad_found) / batch_found)
        else:
            batch_quality_score = 1.0  # No data = no bad data
        batch_find_rate = batch_found / batch_total if batch_total > 0 else 0
        
        # Generate spot-check samples (10 random found results)
        import random as _random
        found_entries = [(k, v) for k, v in batch_results.items() if v.get('status') == 'found']
        spot_check_sample = _random.sample(found_entries, min(10, len(found_entries)))
        
        # Write QA batch report
        qa_report = {
            'batch_number': batch_num,
            'batch_size': batch_total,
            'found': batch_found,
            'not_found': batch_not_found,
            'errors': batch_stats.get('error', 0),
            'quality_flagged': batch_flagged,
            'duplicate_patterns_detected': len(duplicate_patterns),
            'duplicate_details': {str(k): v for k, v in duplicate_patterns.items()},
            'batch_quality_score': round(batch_quality_score, 3),
            'tier_breakdown': {
                'tier1_pdf': batch_stats.get('tier_tier1_pdf', 0),
                'tier2_html': batch_stats.get('tier_tier2_html', 0),
                'tier3_firecrawl': batch_stats.get('tier_tier3_firecrawl', 0),
            },
            'cost_so_far': cost_tracker.get_summary(),
            'spot_check_samples': [
                {
                    'nces_id': nid,
                    'name': r.get('name'),
                    'state': r.get('state'),
                    'dates': r.get('dates'),
                    'source_url': r.get('source_url'),
                    'evidence': r.get('evidence'),
                    'confidence': r.get('confidence'),
                    'tier_used': r.get('tier_used'),
                }
                for nid, r in spot_check_sample
            ],
            'running_totals': {
                'total_processed': total_processed,
                'total_found': stats.get('found', 0),
                'total_not_found': stats.get('not_found', 0),
                'total_errors': stats.get('error', 0),
                'total_flagged': stats.get('quality_flagged', 0),
            },
            'timestamp': datetime.now().isoformat()
        }
        
        qa_report_path = BASE_DIR / f"qa_batch_{batch_num}_report.json"
        with open(qa_report_path, 'w') as f:
            json.dump(qa_report, f, indent=2)
        
        # Print batch summary
        logger.info("")
        logger.info(f"── BATCH {batch_num} QA REPORT ──")
        logger.info(f"  Processed: {batch_total}")
        logger.info(f"  Found: {batch_found} ({batch_found/batch_total*100:.1f}%)" if batch_total else "  Found: 0")
        logger.info(f"  Not found: {batch_not_found}")
        logger.info(f"  Quality flagged: {batch_flagged}")
        logger.info(f"  Duplicate patterns (5+ districts): {len(duplicate_patterns)}")
        logger.info(f"  Find rate: {batch_find_rate:.1%}")
        logger.info(f"  Data quality score: {batch_quality_score:.3f} (of found entries)")
        logger.info(f"  Spot-check report: {qa_report_path}")
        logger.info(f"  Cost so far: ${cost_tracker.get_summary()['total_estimated_cost']:.2f}")
        logger.info(f"  Running total: {total_processed}/{len(districts)} districts")
        
        # ── KILL SWITCHES ──────────────────────────────────────────────
        halt_reasons = []
        
        if duplicate_patterns and halt_on_fail:
            halt_reasons.append(f"DUPLICATE PATTERNS: {len(duplicate_patterns)} patterns with 5+ districts sharing identical dates")
            for pattern, count in duplicate_patterns.items():
                logger.warning(f"    ⚠️  {count} districts share dates: {pattern}")
        
        if batch_quality_score < 0.80 and batch_found > 5 and halt_on_fail:
            halt_reasons.append(f"LOW QUALITY SCORE: {batch_quality_score:.3f} < 0.80 threshold")
        
        firecrawl_in_batch = sum(1 for r in batch_results.values() if r.get('firecrawl_used'))
        if firecrawl_in_batch > 500 and halt_on_fail:
            halt_reasons.append(f"FIRECRAWL BUDGET: {firecrawl_in_batch} calls in single batch exceeds 500 limit")
        
        if halt_reasons:
            logger.warning("")
            logger.warning("🛑 PIPELINE HALTED — Quality gate failed!")
            for reason in halt_reasons:
                logger.warning(f"   → {reason}")
            logger.warning(f"   Review: {qa_report_path}")
            logger.warning(f"   Resume with: python3 pipeline_v2.py --resume --batch-size {batch_size}")
            logger.warning("")
            pipeline_halted = True
            break
        else:
            logger.info(f"  ✅ Batch {batch_num} PASSED quality gate")
    
    # Final save
    save_results(results)
    save_profiles(profiles)
    
    # Final report
    total = len(results)
    cost_summary = cost_tracker.get_summary()
    
    if pipeline_halted:
        logger.info("")
        logger.info("⚠️  Pipeline stopped early due to quality gate failure.")
        logger.info("Fix the issue, then resume with --resume")
    
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"Total processed: {total}")
    logger.info(f"Found: {stats['found']} ({stats['found']/total*100:.1f}%)")
    logger.info(f"Not found: {stats['not_found']} ({stats['not_found']/total*100:.1f}%)")
    logger.info(f"Errors: {stats['error']} ({stats['error']/total*100:.1f}%)")
    logger.info("")
    logger.info("Tier breakdown:")
    for tier in ['tier1_pdf', 'tier2_html', 'tier3_firecrawl']:
        count = stats[f"tier_{tier}"]
        if count > 0:
            logger.info(f"  {tier}: {count}")
    logger.info("")
    logger.info("Cost summary:")
    logger.info(f"  Brave calls: {cost_summary['brave_calls']} (${cost_summary['brave_estimated_cost']})")
    logger.info(f"  Anthropic calls: {cost_summary['anthropic_calls']} (${cost_summary['anthropic_estimated_cost']})")
    logger.info(f"  Firecrawl calls: {cost_summary['firecrawl_calls']} (${cost_summary['firecrawl_estimated_cost']})")
    logger.info(f"  Total estimated cost: ${cost_summary['total_estimated_cost']}")
    logger.info("")
    logger.info(f"Results saved to: {RESULTS_FILE}")
    logger.info(f"District profiles updated: {PROFILES_FILE}")
    logger.info("=" * 70)
    
    return 0


if __name__ == '__main__':
    exit(main())