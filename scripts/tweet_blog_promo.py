#!/usr/bin/env python3
"""
Daily blog promotion tweet for @DisneyStatsWhiz.

Logic:
  1. Check if there's a blog post published today → tweet it as NEW
  2. Otherwise, pick an older post for ICYMI rotation
  3. Track what's been tweeted to avoid repeats

Usage:
  python tweet_blog_promo.py              # Post promo tweet
  python tweet_blog_promo.py --dry-run    # Preview without posting
  python tweet_blog_promo.py --list       # Show all known articles + promo history

Requires env vars: TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET,
                   TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import tweepy
from urllib.parse import urlencode

# ── Paths ────────────────────────────────────────────────────────
BLOG_DIR = Path.home() / "hazeydata.ai" / "blog"
STATE_FILE = Path.home() / "hazeydata" / "pipeline" / "state" / "blog_promo_state.json"
BASE_URL = "https://hazeydata.ai/blog"


# ── UTM Helpers ──────────────────────────────────────────────────

def add_utm(url: str, source: str = "twitter", medium: str = "social",
            campaign: str = "blog_promo", content: str = "") -> str:
    """Add UTM tracking parameters to a URL."""
    params = {
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": campaign,
    }
    if content:
        params["utm_content"] = content
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"

# Articles to never promote on @DisneyStatsWhiz (off-topic for theme parks)
EXCLUDE_SLUGS = {
    "why-canada-needs-a-digital-railway.html",
}

# Only promote articles that match theme park topics.
# If an article slug contains any of these keywords, it's eligible.
# Articles not matching are silently skipped.
TPCR_KEYWORDS = {
    "disney", "orlando", "epcot", "hollywood-studios", "animal-kingdom",
    "magic-kingdom", "disneyland", "tokyo", "universal", "epic-universe",
    "theme-park", "crowd", "wti", "wait-time", "spring-break", "memorial",
    "thanksgiving", "christmas", "new-metric", "best-time", "survival",
}

# ── State Management ─────────────────────────────────────────────

def load_state() -> dict:
    """Load promo tracking state."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"promoted": {}, "last_icymi": None, "last_new": None}


def save_state(state: dict):
    """Save promo tracking state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ── Blog Discovery ───────────────────────────────────────────────

def discover_articles() -> list[dict]:
    """
    Scan blog directory for articles. Returns list of dicts with:
    {filename, title, date_str, date, region, url, is_weekly}
    """
    articles = []
    for html_file in sorted(BLOG_DIR.glob("*.html")):
        if html_file.name == "index.html":
            continue

        content = html_file.read_text()

        # Extract title
        title_match = re.search(r"<title>(.*?)\s*\|", content)
        title = title_match.group(1).strip() if title_match else html_file.stem

        # Extract date from meta or filename
        date_match = re.search(r'<span>(\w+ \d+, \d{4})</span>', content)
        if date_match:
            try:
                article_date = datetime.strptime(date_match.group(1), "%B %d, %Y").date()
            except ValueError:
                article_date = None
        else:
            article_date = None

        # Determine region from filename
        if "orlando" in html_file.name:
            region = "orlando"
        elif "disneyland" in html_file.name:
            region = "disneyland"
        elif "tokyo" in html_file.name:
            region = "tokyo"
        else:
            region = "general"

        is_weekly = "this-week" in html_file.name

        # Skip non-TPCR articles (government, personal, etc.)
        slug_lower = html_file.name.lower()
        if slug_lower in EXCLUDE_SLUGS:
            continue
        if not any(kw in slug_lower for kw in TPCR_KEYWORDS):
            continue

        articles.append({
            "filename": html_file.name,
            "title": title,
            "date": article_date,
            "region": region,
            "url": f"{BASE_URL}/{html_file.name}",
            "is_weekly": is_weekly,
        })

    # Sort by date, newest first
    articles.sort(key=lambda a: a["date"] or date.min, reverse=True)
    return articles


def find_todays_articles(articles: list[dict]) -> list[dict]:
    """Find articles published today."""
    today = date.today()
    return [a for a in articles if a["date"] == today]


def pick_icymi(articles: list[dict], state: dict) -> dict | None:
    """
    Pick the best ICYMI candidate:
    - Not promoted in last 7 days
    - Prefer least-recently promoted
    - Prefer evergreen content over dated weekly reports
    - Skip very old weekly reports (>30 days)
    """
    now = datetime.now()
    promoted = state.get("promoted", {})
    candidates = []

    for article in articles:
        slug = article["filename"]

        if slug in EXCLUDE_SLUGS:
            continue

        # Skip very old weekly reports
        if article["is_weekly"] and article["date"]:
            age_days = (date.today() - article["date"]).days
            if age_days > 21:  # Weekly reports stale after 3 weeks
                continue

        # Check promo cooldown (7 days)
        last_promo = promoted.get(slug)
        if last_promo:
            try:
                last_dt = datetime.fromisoformat(last_promo)
                if (now - last_dt).days < 7:
                    continue
            except (ValueError, TypeError):
                pass

        # Score: prefer less-promoted, non-weekly (evergreen) content
        promo_count = len([v for k, v in promoted.items() if k == slug])
        is_evergreen = not article["is_weekly"]
        score = (1 if is_evergreen else 0, -(promo_count or 0))

        candidates.append((score, article))

    if not candidates:
        return None

    # Sort by score (highest first), then pick top
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# ── Tweet Composition ────────────────────────────────────────────

def compose_new_tweet(article: dict) -> str:
    """Compose tweet for a freshly published article."""
    title = article["title"]
    url = add_utm(article["url"], source="twitter", medium="social",
                  campaign="blog_promo", content="new")

    if article["region"] == "orlando":
        hooks = [
            f"📊 New: {title}\n\nWhich parks are busiest? Which are ghost towns? The WTI data tells all.\n\n{url}",
            f"🏰 Fresh crowd outlook: {title}\n\nPark-by-park WTI breakdown — know before you go.\n\n{url}",
            f"📈 This week's Orlando crowd forecast is live.\n\n{title}\n\n{url}",
        ]
    elif article["region"] == "disneyland":
        hooks = [
            f"📊 New: {title}\n\nDisneyland or California Adventure? Here's what the data says this week.\n\n{url}",
            f"🏔️ Fresh SoCal crowd outlook: {title}\n\nPark-by-park WTI breakdown for Disneyland Resort.\n\n{url}",
            f"📈 This week's Disneyland crowd forecast is live.\n\n{title}\n\n{url}",
        ]
    elif article["region"] == "tokyo":
        hooks = [
            f"📊 New: {title}\n\nTokyo Disneyland or DisneySea? Here's what the crowd data says this week.\n\n{url}",
            f"🗼 Fresh Tokyo Disney crowd outlook: {title}\n\nPark-by-park WTI breakdown — plan smarter.\n\n{url}",
            f"📈 This week's Tokyo Disney Resort crowd forecast is live.\n\n{title}\n\n{url}",
        ]
    else:
        hooks = [
            f"📊 New on the blog: {title}\n\n{url}",
        ]

    # Rotate through hooks based on day of year
    idx = date.today().timetuple().tm_yday % len(hooks)
    return hooks[idx]


def compose_icymi_tweet(article: dict) -> str:
    """Compose ICYMI tweet for an older article."""
    title = article["title"]
    url = add_utm(article["url"], source="twitter", medium="social",
                  campaign="blog_promo", content="icymi")

    if article["is_weekly"]:
        return f"📌 ICYMI: {title}\n\nStill relevant if you're planning a trip this week. Park-by-park crowd data inside.\n\n{url}"
    elif "wti" in article["filename"].lower() or "metric" in article["filename"].lower():
        return f"📌 ICYMI: {title}\n\nHow we track theme park crowds with a single number — and why it works.\n\n{url}"
    elif "spring-break" in article["filename"]:
        return f"📌 ICYMI: {title}\n\nPlanning a spring break trip? The data can help you pick the right week.\n\n{url}"
    elif "memorial" in article["filename"]:
        return f"📌 ICYMI: {title}\n\nHoliday weekends at the parks — here's what the numbers say.\n\n{url}"
    else:
        return f"📌 ICYMI: {title}\n\nWorth a read if you're planning a theme park trip.\n\n{url}"


# ── Twitter Posting ──────────────────────────────────────────────

def post_tweet(text: str) -> str:
    """Post tweet and return tweet URL."""
    ck = os.environ["TWITTER_CONSUMER_KEY"]
    cs = os.environ["TWITTER_CONSUMER_SECRET"]
    at = os.environ["TWITTER_ACCESS_TOKEN"]
    ats = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

    client = tweepy.Client(
        consumer_key=ck, consumer_secret=cs,
        access_token=at, access_token_secret=ats,
    )

    response = client.create_tweet(text=text)
    tweet_id = response.data["id"]
    return f"https://x.com/DisneyStatsWhiz/status/{tweet_id}"


# ── Main ─────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    list_mode = "--list" in sys.argv

    articles = discover_articles()

    if not articles:
        print("No blog articles found.")
        sys.exit(0)

    state = load_state()

    if list_mode:
        promoted = state.get("promoted", {})
        print(f"{'Filename':<55} {'Date':<12} {'Region':<12} {'Last Promo':<12}")
        print("-" * 91)
        for a in articles:
            date_str = str(a["date"]) if a["date"] else "unknown"
            last = promoted.get(a["filename"], "never")
            if last != "never":
                last = last[:10]
            print(f"{a['filename']:<55} {date_str:<12} {a['region']:<12} {last:<12}")
        return

    # Check for today's articles first
    todays = find_todays_articles(articles)

    if todays:
        # Promote the newest fresh article
        article = todays[0]
        tweet_text = compose_new_tweet(article)
        promo_type = "NEW"
        print(f"🆕 Fresh article found: {article['title']}")
    else:
        # ICYMI rotation
        article = pick_icymi(articles, state)
        if not article:
            print("No ICYMI candidates available (all recently promoted or excluded).")
            sys.exit(0)
        tweet_text = compose_icymi_tweet(article)
        promo_type = "ICYMI"
        print(f"📌 ICYMI pick: {article['title']}")

    print(f"\n📝 Tweet ({promo_type}):\n{tweet_text}\n")

    if dry_run:
        print("🏃 DRY RUN — not posting.")
        return

    # Post
    tweet_url = post_tweet(tweet_text)
    print(f"✅ Posted: {tweet_url}")

    # Update state
    state["promoted"][article["filename"]] = datetime.now().isoformat()
    if promo_type == "NEW":
        state["last_new"] = article["filename"]
    else:
        state["last_icymi"] = article["filename"]
    save_state(state)

    # Output for cron pickup
    print(f"\nTWEET_URL={tweet_url}")
    print(f"ARTICLE_URL={article['url']}")
    print(f"PROMO_TYPE={promo_type}")


if __name__ == "__main__":
    main()
