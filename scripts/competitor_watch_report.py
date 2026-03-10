#!/usr/bin/env python3
"""
Competitor Watch Report — Daily Digest

Scrapes theme park industry sources for competitor activity and news
relevant to HazeyData's crowd prediction business, then posts a
formatted digest to the Discord #competitor-watch channel.

Sources monitored:
  1. TouringPlans — blog posts, announcements, data dumps
  2. Thrill Data — competing crowd prediction service
  3. Undercover Tourist — deals, crowd predictions, blog content
  4. Theme park news — WDWNT, BlogMickey, major industry moves
  5. Reddit mentions — crowd calendar, wait times, best time to visit
  6. HazeyData mentions — anyone talking about us

Usage:
    python scripts/competitor_watch_report.py              # Run + post to Discord
    python scripts/competitor_watch_report.py --dry-run    # Print only, don't post
    python scripts/competitor_watch_report.py --json-only  # Only update JSON, no Discord

Designed to be called by a Clawdbot cron job or subagent.
The web_fetch calls use requests + readability; for Cloudflare-protected
sites the script gracefully falls back to "unable to fetch".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ET = ZoneInfo("America/Toronto")
NOW = datetime.now(ET)
TODAY = NOW.strftime("%Y-%m-%d")
DISCORD_CHANNEL_ID = "1479351590052823164"  # #competitor-watch
GUILD_ID = "1479350342318690505"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JSON_OUTPUT = PROJECT_ROOT / "docs" / "analytics-data" / "competitor-watch.json"

# Brave Search API (optional — if key available, use it for deeper search)
BRAVE_API_KEY = None  # Set via env or config if available

# How many days back to consider "recent"
RECENT_DAYS = 7

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; HazeyData-CompWatch/1.0)"
})


def fetch_page(url: str, max_chars: int = 8000, timeout: int = 15) -> str | None:
    """Fetch a URL and return extracted text, or None on failure."""
    try:
        resp = SESSION.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return None
        html = resp.text

        # Try readability first
        if HAS_READABILITY:
            doc = ReadabilityDocument(html)
            text = doc.summary()
            if HAS_BS4:
                text = BeautifulSoup(text, "html.parser").get_text(separator="\n")
            return text[:max_chars] if text else None

        # Fallback: basic tag stripping
        if HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return text[:max_chars] if text else None

        # Last resort: regex strip
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else None
    except Exception:
        return None


def extract_links(html_text: str, base_url: str) -> list[dict]:
    """Extract links from HTML if BS4 available."""
    if not HAS_BS4:
        return []
    try:
        resp = SESSION.get(base_url, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            if href.startswith("/"):
                from urllib.parse import urljoin
                href = urljoin(base_url, href)
            if href.startswith("http"):
                links.append({"title": title, "url": href})
        return links
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Source scrapers
# ---------------------------------------------------------------------------

def _clean_url(url: str) -> str:
    """Remove tracking parameters from URLs."""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        # Remove common tracking params
        tracking_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_content",
                         "utm_term", "adt_ei", "fbclid", "gclid", "ref", "mc_eid",
                         "mc_cid", "mkt_tok"}
        cleaned = {k: v for k, v in params.items() if k.lower() not in tracking_keys}
        new_query = urlencode(cleaned, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url


def _parse_rss_feed(feed_url: str, source_name: str, max_items: int = 10,
                    max_age_days: int = 7) -> list[dict]:
    """Generic RSS feed parser. Returns list of items from a feed."""
    if not HAS_FEEDPARSER:
        return []
    items = []
    try:
        feed = feedparser.parse(feed_url, agent="HazeyData-CompWatch/1.0")
        cutoff = datetime.now() - timedelta(days=max_age_days)
        
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "").strip()
            link = _clean_url(entry.get("link", ""))
            if not title or not link:
                continue
            
            # Check publication date if available
            published = None
            for date_field in ("published_parsed", "updated_parsed"):
                parsed = entry.get(date_field)
                if parsed:
                    try:
                        from time import mktime
                        published = datetime.fromtimestamp(mktime(parsed))
                        break
                    except (ValueError, OverflowError):
                        pass
            
            # Skip old items
            if published and published < cutoff:
                continue
            
            # Get summary snippet
            summary = ""
            if entry.get("summary"):
                if HAS_BS4:
                    summary = BeautifulSoup(entry["summary"], "html.parser").get_text(strip=True)[:200]
                else:
                    summary = re.sub(r"<[^>]+>", " ", entry["summary"])[:200]
            
            items.append({
                "title": title[:120],
                "url": link,
                "source": source_name,
                "snippet": summary,
                "published": published.strftime("%Y-%m-%d") if published else None,
            })
    except Exception:
        pass
    return items


def check_touringplans() -> list[dict]:
    """Check TouringPlans blog for recent posts via RSS feed."""
    # RSS bypasses Cloudflare — much more reliable than HTML scraping
    items = _parse_rss_feed(
        "https://touringplans.com/blog/feed/",
        "TouringPlans",
        max_items=10,
        max_age_days=7,
    )
    
    # Fallback to HTML scraping if RSS fails
    if not items:
        blog_url = "https://touringplans.com/blog/"
        text = fetch_page(blog_url, max_chars=15000)
        if text and HAS_BS4:
            try:
                resp = SESSION.get(blog_url, timeout=15)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    seen_urls = set()
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        title = a.get_text(strip=True)
                        if "/blog/" in href and href != blog_url and title and len(title) > 15:
                            if href.startswith("/"):
                                href = f"https://touringplans.com{href}"
                            skip_patterns = ["category", "tag/", "page/", "#", "dashboard",
                                             "forum", "author/"]
                            if href not in seen_urls and not any(p in href for p in skip_patterns):
                                seen_urls.add(href)
                                items.append({"title": title[:120], "url": href, "source": "TouringPlans"})
                    items = items[:8]
            except Exception:
                pass

    # Filter for crowd/data relevant articles
    crowd_keywords = [
        "crowd", "wait time", "data dump", "attendance", "capacity",
        "lightning lane", "genie", "touring plan", "prediction",
        "spring break", "summer", "holiday", "busy", "slow",
        "epic universe", "new ride", "closure", "refurbishment",
        "price", "ticket", "annual pass", "free dining",
        "enjoyment index", "after hours", "hotel", "resort",
        "express pass", "forecast", "sell", "event",
        "flower", "garden", "festival", "food", "wine",
        "race", "marathon", "disney world", "universal",
        "disneyland", "magic kingdom", "epcot", "hollywood studios",
        "animal kingdom", "castle", "repaint", "hours",
    ]
    relevant = []
    for item in items:
        title_lower = item["title"].lower()
        snippet_lower = item.get("snippet", "").lower()
        combined = title_lower + " " + snippet_lower
        if any(kw in combined for kw in crowd_keywords):
            item["relevant"] = True
            relevant.append(item)
        else:
            item["relevant"] = False

    # Return relevant items first, then others (capped)
    others = [i for i in items if not i.get("relevant")]
    return relevant + others[:3]


def check_thrilldata() -> list[dict]:
    """Check Thrill Data for any updates."""
    items = []
    urls_to_try = [
        "https://thrilldata.com",
        "https://thrilldata.com/blog",
    ]
    for url in urls_to_try:
        text = fetch_page(url, max_chars=5000)
        if text:
            items.append({
                "title": f"Thrill Data site accessible",
                "url": url,
                "source": "Thrill Data",
                "snippet": text[:200]
            })
            break
    return items


def check_undercover_tourist() -> list[dict]:
    """Check Undercover Tourist blog."""
    items = []
    text = fetch_page("https://www.undercovertourist.com/blog/", max_chars=5000)
    if text and "just a moment" not in text.lower():
        items.append({
            "title": "Undercover Tourist Blog",
            "url": "https://www.undercovertourist.com/blog/",
            "source": "Undercover Tourist",
            "snippet": text[:200]
        })
    return items


def check_theme_park_news() -> list[dict]:
    """Check major theme park news sites via RSS feeds (bypasses Cloudflare)."""
    items = []
    
    # RSS feeds — much more reliable than HTML scraping
    rss_sources = [
        ("https://wdwnt.com/feed/", "WDWNT"),
        ("https://blogmickey.com/feed/", "BlogMickey"),
        ("https://www.laughingplace.com/w/feed/", "Laughing Place"),
    ]

    crowd_keywords = [
        "epic universe", "crowd", "price", "ticket", "close",
        "new ride", "open", "wait time", "annual pass",
        "lightning lane", "express pass", "refurb",
        "spring break", "capacity", "hour", "sell",
        "after hours", "event", "castle", "festival",
        "closure", "construction", "merchandise",
        "attendance", "delay", "soft open", "preview",
    ]

    for feed_url, name in rss_sources:
        feed_items = _parse_rss_feed(feed_url, name, max_items=15, max_age_days=3)
        for item in feed_items:
            title_lower = item["title"].lower()
            snippet_lower = item.get("snippet", "").lower()
            combined = title_lower + " " + snippet_lower
            if any(kw in combined for kw in crowd_keywords):
                item["relevant"] = True
                items.append(item)

    # Fallback to HTML scraping if RSS returned nothing
    if not items:
        html_sources = [
            ("https://wdwnt.com", "WDWNT"),
            ("https://blogmickey.com", "BlogMickey"),
            ("https://www.laughingplace.com/w/news/", "Laughing Place"),
        ]
        article_pattern = re.compile(r"/202[4-9]/\d{2}/")
        for url, name in html_sources:
            try:
                resp = SESSION.get(url, timeout=15)
                if resp.status_code == 200 and HAS_BS4:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    seen = set()
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        title = a.get_text(strip=True)
                        if not title or len(title) < 20 or not href.startswith("http"):
                            continue
                        if not article_pattern.search(href):
                            continue
                        if href in seen:
                            continue
                        title_lower = title.lower()
                        if any(kw in title_lower for kw in crowd_keywords):
                            seen.add(href)
                            items.append({"title": title[:120], "url": href, "source": name})
                        if len(items) >= 8:
                            break
            except Exception:
                pass

    return items[:12]


def check_reddit() -> list[dict]:
    """Check Reddit for crowd calendar / wait times discussions.
    
    Two-pronged approach:
    1. Browse hot/new posts from key theme park subreddits directly
    2. Search for specific terms (crowd calendar, wait times, hazeydata)
    
    Uses Reddit's JSON API (append .json to URLs) for structured data.
    """
    items = []
    seen_urls: set[str] = set()

    # --- Approach 1: Browse key subreddits for hot/new posts ---
    subreddits = [
        "WaltDisneyWorld", "UniversalOrlando", "DisneyPlanning",
        "disneyparks", "Disneyland", "UniversalStudios",
    ]
    
    crowd_keywords = [
        "crowd", "wait time", "busy", "spring break", "summer",
        "epic universe", "hazey", "touring plan", "prediction",
        "annual pass", "lightning lane", "genie", "express pass",
        "best time", "worst time", "how busy", "capacity",
        "ticket price", "sell out", "closure", "refurb",
        "crowd calendar", "wait", "line", "packed", "empty",
        "slow day", "dead", "mobbed", "insane",
    ]

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=10"
            resp = SESSION.get(url, timeout=15, headers={
                "User-Agent": "HazeyData-CompWatch/1.0 (competitive intelligence)"
            })
            if resp.status_code == 200:
                data = resp.json()
                posts = data.get("data", {}).get("children", [])
                for post in posts:
                    pd_ = post.get("data", {})
                    title = pd_.get("title", "")
                    permalink = pd_.get("permalink", "")
                    score = pd_.get("score", 0)
                    num_comments = pd_.get("num_comments", 0)
                    
                    if not title or not permalink:
                        continue
                    
                    full_url = f"https://www.reddit.com{permalink}"
                    if full_url in seen_urls:
                        continue
                    
                    # Filter for crowd/wait-time relevance OR high engagement
                    title_lower = title.lower()
                    selftext_lower = pd_.get("selftext", "")[:500].lower()
                    combined = title_lower + " " + selftext_lower
                    
                    is_relevant = any(kw in combined for kw in crowd_keywords)
                    is_popular = score >= 50 or num_comments >= 20
                    
                    if is_relevant or is_popular:
                        seen_urls.add(full_url)
                        items.append({
                            "title": title[:120],
                            "url": full_url,
                            "source": f"Reddit r/{sub}",
                            "query": "subreddit_browse",
                            "score": score,
                            "comments": num_comments,
                            "relevant": is_relevant,
                        })
        except Exception:
            pass

    # --- Approach 2: Search for specific terms ---
    queries = [
        ("crowd calendar", "crowd+calendar+disney+OR+universal"),
        ("wait times", "wait+times+disney+OR+universal"),
        ("hazeydata", "hazeydata+OR+%22hazey+data%22+OR+%22crowd+report%22"),
    ]

    for label, query in queries:
        try:
            url = f"https://www.reddit.com/search.json?q={query}&t=week&sort=relevance&limit=5"
            resp = SESSION.get(url, timeout=15, headers={
                "User-Agent": "HazeyData-CompWatch/1.0 (competitive intelligence)"
            })
            if resp.status_code == 200:
                data = resp.json()
                posts = data.get("data", {}).get("children", [])
                for post in posts[:3]:
                    pd_ = post.get("data", {})
                    title = pd_.get("title", "")
                    permalink = pd_.get("permalink", "")
                    subreddit = pd_.get("subreddit", "")
                    
                    if not title or not permalink:
                        continue
                    
                    full_url = f"https://www.reddit.com{permalink}"
                    if full_url in seen_urls:
                        continue
                    
                    # For search results, apply relevance filter
                    title_lower = title.lower()
                    park_terms = [
                        "disney", "universal", "epcot", "magic kingdom",
                        "crowd", "wait time", "busy", "spring break",
                        "epic universe", "theme park", "hazey", "touring",
                        "annual pass", "lightning lane", "genie",
                        "disneyland", "hollywood studios", "animal kingdom",
                    ]
                    if label == "hazeydata" or any(t in title_lower for t in park_terms):
                        seen_urls.add(full_url)
                        items.append({
                            "title": title[:120],
                            "url": full_url,
                            "source": f"Reddit r/{subreddit}",
                            "query": label,
                            "score": pd_.get("score", 0),
                            "comments": pd_.get("num_comments", 0),
                        })
        except (json.JSONDecodeError, KeyError, Exception):
            pass

    # Sort by relevance first, then score
    items.sort(key=lambda x: (not x.get("relevant", False), -x.get("score", 0)))
    return items[:15]


def check_hazeydata_mentions() -> list[dict]:
    """Search for HazeyData mentions across the web."""
    items = []

    # Check Reddit specifically
    for query in ["hazeydata", "hazey+data+theme+park"]:
        url = f"https://www.reddit.com/search/?q={query}&t=month&sort=new"
        text = fetch_page(url, max_chars=3000)
        if text and "hazey" in text.lower():
            items.append({
                "title": f"Reddit search: '{query}' — results found",
                "url": url,
                "source": "Reddit"
            })

    # Check Twitter/X (probably blocked but try)
    # Check Google (also probably blocked)
    return items


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(results: dict) -> str:
    """Build the Discord-formatted markdown report."""
    lines = []
    lines.append(f"# 🔭 Competitor Watch — {NOW.strftime('%A, %B %d, %Y')}")
    lines.append("")

    # 1. TouringPlans
    lines.append("## 📊 TouringPlans")
    tp_items = results.get("touringplans", [])
    if tp_items:
        relevant = [i for i in tp_items if i.get("relevant")]
        others = [i for i in tp_items if not i.get("relevant")]
        for item in relevant[:8]:
            lines.append(f"- **{item['title']}** — <{item['url']}>")
        if others:
            lines.append(f"- *+{len(others)} other post(s) (non-crowd-related)*")
    else:
        lines.append("- Nothing new")
    lines.append("")

    # 2. Thrill Data
    lines.append("## 🎯 Thrill Data")
    td_items = results.get("thrilldata", [])
    if td_items:
        for item in td_items[:3]:
            snippet = item.get("snippet", "")[:100]
            lines.append(f"- {item['title']}: {snippet}...")
    else:
        lines.append("- Unable to fetch (Cloudflare protected) — manual check recommended")
    lines.append("")

    # 3. Undercover Tourist
    lines.append("## 🎟️ Undercover Tourist")
    ut_items = results.get("undercover_tourist", [])
    if ut_items:
        for item in ut_items[:3]:
            snippet = item.get("snippet", "")[:100]
            lines.append(f"- {item['title']}: {snippet}...")
    else:
        lines.append("- Unable to fetch (Cloudflare protected) — manual check recommended")
    lines.append("")

    # 4. Theme Park News
    lines.append("## 📰 Theme Park News")
    news_items = results.get("theme_park_news", [])
    if news_items:
        for item in news_items[:5]:
            lines.append(f"- **{item['title']}** ({item['source']}) — <{item['url']}>")
    else:
        lines.append("- Nothing crowd-impacting found today")
    lines.append("")

    # 5. Reddit
    lines.append("## 💬 Reddit Mentions")
    reddit_items = results.get("reddit", [])
    if reddit_items:
        for item in reddit_items[:5]:
            lines.append(f"- **{item['title']}** ({item['source']}) — <{item['url']}>")
    else:
        lines.append("- Nothing new")
    lines.append("")

    # 6. HazeyData Mentions
    lines.append("## 🔍 HazeyData Mentions")
    hd_items = results.get("hazeydata_mentions", [])
    if hd_items:
        for item in hd_items[:5]:
            lines.append(f"- {item['title']} — <{item['url']}>")
    else:
        lines.append("- No mentions found this week")
    lines.append("")

    lines.append(f"*Report generated {NOW.strftime('%Y-%m-%d %H:%M ET')}*")
    return "\n".join(lines)


def build_json_data(results: dict) -> dict:
    """Build JSON data for Mission Control dashboard."""
    return {
        "generated_at": NOW.isoformat(),
        "date": TODAY,
        "categories": {
            category: {
                "count": len(items),
                "items": items
            }
            for category, items in results.items()
        },
        "total_items": sum(len(v) for v in results.values())
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Competitor Watch Report")
    parser.add_argument("--dry-run", action="store_true", help="Print report, don't post")
    parser.add_argument("--json-only", action="store_true", help="Only update JSON")
    args = parser.parse_args()

    print(f"🔭 Competitor Watch — {TODAY}")
    print("=" * 50)

    # Run all checkers
    results = {}

    print("Checking TouringPlans...", end=" ", flush=True)
    results["touringplans"] = check_touringplans()
    print(f"✓ ({len(results['touringplans'])} items)")

    print("Checking Thrill Data...", end=" ", flush=True)
    results["thrilldata"] = check_thrilldata()
    print(f"✓ ({len(results['thrilldata'])} items)")

    print("Checking Undercover Tourist...", end=" ", flush=True)
    results["undercover_tourist"] = check_undercover_tourist()
    print(f"✓ ({len(results['undercover_tourist'])} items)")

    print("Checking theme park news...", end=" ", flush=True)
    results["theme_park_news"] = check_theme_park_news()
    print(f"✓ ({len(results['theme_park_news'])} items)")

    print("Checking Reddit...", end=" ", flush=True)
    results["reddit"] = check_reddit()
    print(f"✓ ({len(results['reddit'])} items)")

    print("Checking HazeyData mentions...", end=" ", flush=True)
    results["hazeydata_mentions"] = check_hazeydata_mentions()
    print(f"✓ ({len(results['hazeydata_mentions'])} items)")

    # Build report
    report = build_report(results)
    total = sum(len(v) for v in results.values())
    print(f"\nTotal items found: {total}")

    # Save JSON
    json_data = build_json_data(results)
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(json_data, indent=2, default=str))
    print(f"JSON saved to {JSON_OUTPUT}")

    if args.json_only:
        print("\n--json-only mode, skipping Discord post")
        print("\n" + report)
        return

    if args.dry_run:
        print("\n--dry-run mode, report below:")
        print("\n" + report)
        return

    # Post to Discord via clawdbot message tool
    # Since this script can't call clawdbot tools directly,
    # it writes the report to a known file for the calling agent to post.
    report_file = PROJECT_ROOT / "docs" / "analytics-data" / "competitor-watch-latest.md"
    report_file.write_text(report)
    print(f"Report saved to {report_file}")
    print("\nReport ready for Discord posting.")
    print("\n" + report)


if __name__ == "__main__":
    main()
