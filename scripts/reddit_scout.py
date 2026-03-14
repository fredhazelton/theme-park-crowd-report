#!/usr/bin/env python3
"""
Reddit Scout — Monitors theme park subreddits for relevant discussions.

Fetches recent posts from target subreddits, scores them by keyword relevance,
recency, and engagement, then posts qualifying threads to Discord #reddit channel
via clawdbot CLI.

Usage:
    .venv/bin/python3 scripts/reddit_scout.py [--dry-run] [--verbose] [--json]

State is persisted to data/reddit_scout_state.json to avoid duplicate postings.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SUBREDDITS = [
    "WaltDisneyWorld",
    "Disneyland",
    "DisneyPlanning",
    "DisneyWorld",
    "themeparks",
]

# Keywords with weights — higher weight = more relevant
HIGH_VALUE_KEYWORDS = {
    "crowd": 3,
    "crowds": 3,
    "busy": 3,
    "wait time": 4,
    "wait times": 4,
    "best time to visit": 5,
    "best day": 4,
    "worst day": 4,
    "when to go": 4,
    "planning": 2,
    "budget": 3,
    "how much": 3,
    "lightning lane": 3,
    "genie+": 3,
    "genie plus": 3,
    "dining plan": 3,
    "park hopper": 3,
    "touring plan": 4,
}

MEDIUM_VALUE_KEYWORDS = {
    "hotel": 1,
    "resort": 1,
    "ticket": 1,
    "pass": 1,
    "annual pass": 2,
    "crowd calendar": 5,
    "prediction": 3,
    "forecast": 3,
    "strategy": 2,
    "tip": 1,
    "advice": 2,
    "help planning": 3,
}

# Merge all keywords
KEYWORDS = {**MEDIUM_VALUE_KEYWORDS, **HIGH_VALUE_KEYWORDS}

# Scoring thresholds
MIN_SCORE = 5              # Minimum score to qualify for posting
MAX_AGE_HOURS = 48         # Don't scout threads older than this
MAX_POSTS_PER_RUN = 5      # Don't flood the channel

# State file
STATE_FILE = PROJECT_ROOT / "data" / "reddit_scout_state.json"
MAX_STATE_URLS = 500        # Trim posted_urls to prevent bloat

# Discord
DISCORD_CHANNEL_ID = "1481332266729734159"  # #reddit forum channel

# Reddit API
REDDIT_BASE_URL = "https://www.reddit.com"
USER_AGENT = "hazeydata-scout/1.0 (theme park crowd report)"
REQUEST_TIMEOUT = 15
POSTS_PER_SUBREDDIT = 25
RATE_LIMIT_DELAY = 2  # seconds between subreddit requests (be nice to Reddit)


# ── State Management ──────────────────────────────────────────────────

def load_state() -> dict:
    """Load the state file, returning a default if it doesn't exist."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            # Ensure required keys
            data.setdefault("posted_urls", [])
            data.setdefault("last_run", None)
            data.setdefault("total_posted", 0)
            return data
        except (json.JSONDecodeError, KeyError) as e:
            log(f"Warning: corrupt state file, starting fresh: {e}")
    return {"posted_urls": [], "last_run": None, "total_posted": 0}


def save_state(state: dict):
    """Save state to disk, trimming posted_urls to MAX_STATE_URLS."""
    state["posted_urls"] = state["posted_urls"][-MAX_STATE_URLS:]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Logging ───────────────────────────────────────────────────────────

VERBOSE = False

def log(msg: str):
    """Log to stderr."""
    print(f"[reddit_scout] {msg}", file=sys.stderr)

def log_verbose(msg: str):
    """Log only in verbose mode."""
    if VERBOSE:
        print(f"[reddit_scout] {msg}", file=sys.stderr)


# ── Reddit API ────────────────────────────────────────────────────────

def fetch_subreddit_posts(subreddit: str) -> list[dict]:
    """Fetch recent posts from a subreddit using Reddit's public JSON API."""
    url = f"{REDDIT_BASE_URL}/r/{subreddit}/new.json"
    params = {"limit": POSTS_PER_SUBREDDIT, "raw_json": 1}
    headers = {"User-Agent": USER_AGENT}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            log(f"Rate limited on r/{subreddit}, waiting {retry_after}s")
            time.sleep(retry_after)
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

        if resp.status_code != 200:
            log(f"Error fetching r/{subreddit}: HTTP {resp.status_code}")
            return []

        data = resp.json()
        children = data.get("data", {}).get("children", [])
        return [child["data"] for child in children if child.get("kind") == "t3"]

    except requests.exceptions.Timeout:
        log(f"Timeout fetching r/{subreddit}")
        return []
    except requests.exceptions.ConnectionError:
        log(f"Connection error fetching r/{subreddit}")
        return []
    except Exception as e:
        log(f"Unexpected error fetching r/{subreddit}: {e}")
        return []


# ── Scoring ───────────────────────────────────────────────────────────

def score_post(post: dict) -> tuple[float, list[str]]:
    """
    Score a post based on keyword matches, recency, and engagement.
    Returns (score, list_of_matched_keywords).
    """
    title = (post.get("title") or "").lower()
    selftext = (post.get("selftext") or "").lower()
    combined = f"{title} {selftext}"

    # Keyword scoring
    matched_keywords = []
    keyword_score = 0.0
    for keyword, weight in KEYWORDS.items():
        if keyword.lower() in combined:
            matched_keywords.append(keyword)
            keyword_score += weight
            # Bonus if keyword appears in title (more targeted)
            if keyword.lower() in title:
                keyword_score += weight * 0.5

    if not matched_keywords:
        return 0.0, []

    # Recency scoring (prefer < 24h old, decay after that)
    created_utc = post.get("created_utc", 0)
    age_hours = (time.time() - created_utc) / 3600
    if age_hours <= 6:
        recency_bonus = 3.0
    elif age_hours <= 12:
        recency_bonus = 2.0
    elif age_hours <= 24:
        recency_bonus = 1.0
    elif age_hours <= 48:
        recency_bonus = 0.5
    else:
        recency_bonus = 0.0

    # Engagement scoring
    upvotes = post.get("score", 0)
    comments = post.get("num_comments", 0)

    engagement_score = 0.0
    if upvotes >= 50:
        engagement_score += 2.0
    elif upvotes >= 20:
        engagement_score += 1.5
    elif upvotes >= 10:
        engagement_score += 1.0
    elif upvotes >= 5:
        engagement_score += 0.5

    if comments >= 30:
        engagement_score += 2.0
    elif comments >= 15:
        engagement_score += 1.5
    elif comments >= 5:
        engagement_score += 1.0
    elif comments >= 2:
        engagement_score += 0.5

    total = keyword_score + recency_bonus + engagement_score
    return total, matched_keywords


def time_ago(created_utc: float) -> str:
    """Return a human-readable 'time ago' string."""
    seconds = time.time() - created_utc
    if seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins}m ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}h ago"
    else:
        days = int(seconds / 86400)
        return f"{days}d ago"


def suggest_angle(matched_keywords: list[str]) -> str:
    """Generate a brief suggested content angle based on matched keywords."""
    kw_set = set(k.lower() for k in matched_keywords)

    if kw_set & {"crowd", "crowds", "busy", "crowd calendar"}:
        return "Crowd data validation — compare their experience against our predictions"
    if kw_set & {"wait time", "wait times"}:
        return "Wait time analysis — reference our entity-level WTI data"
    if kw_set & {"best time to visit", "best day", "worst day", "when to go"}:
        return "Trip planning advice — link to our forecast/calendar tools"
    if kw_set & {"budget", "how much"}:
        return "Budget planning content — could tie into our cost analysis features"
    if kw_set & {"lightning lane", "genie+", "genie plus"}:
        return "Lightning Lane strategy — our wait time predictions help optimize LL use"
    if kw_set & {"touring plan", "strategy", "planning"}:
        return "Touring strategy — our crowd predictions help build better touring plans"
    if kw_set & {"prediction", "forecast"}:
        return "Direct relevance — they're looking for exactly what we provide"
    if kw_set & {"crowd calendar"}:
        return "Crowd calendar comparison — perfect opportunity to showcase our data"
    if kw_set & {"annual pass", "pass", "ticket"}:
        return "Pass holder value — our tools help maximize pass usage"
    if kw_set & {"dining plan", "hotel", "resort"}:
        return "Trip planning — crowd data helps with dining/hotel timing decisions"
    if kw_set & {"advice", "help planning", "tip"}:
        return "General advice thread — helpful response with crowd prediction angle"

    return "Engage with relevant crowd/planning insights from our data"


# ── Discord Posting ───────────────────────────────────────────────────

def format_discord_message(post: dict, subreddit: str, score: float,
                           matched_keywords: list[str]) -> str:
    """Format a Reddit post as a Discord message."""
    title = post.get("title", "Untitled")
    permalink = post.get("permalink", "")
    url = f"https://www.reddit.com{permalink}" if permalink else post.get("url", "")
    selftext = post.get("selftext", "")
    upvotes = post.get("score", 0)
    comments = post.get("num_comments", 0)
    created_utc = post.get("created_utc", 0)

    # Summary: first ~200 chars of selftext
    if selftext and selftext.strip():
        summary = selftext.strip()[:200]
        if len(selftext.strip()) > 200:
            summary += "…"
    else:
        summary = "Link post — no selftext"

    # Clean up summary (remove markdown formatting that looks bad in Discord)
    summary = summary.replace("\n", " ").replace("  ", " ")

    keywords_str = ", ".join(matched_keywords[:8])
    age_str = time_ago(created_utc)
    angle = suggest_angle(matched_keywords)

    msg = (
        f'**🔴 Reddit Scout — r/{subreddit}**\n'
        f'\n'
        f'**"{title}"**\n'
        f'<{url}>\n'
        f'\n'
        f'**Summary:** {summary}\n'
        f'**Relevance:** {keywords_str}\n'
        f'**Engagement:** ⬆️ {upvotes} | 💬 {comments} | ⏰ {age_str}\n'
        f'**Suggested angle:** {angle}\n'
        f'\n'
        f'**Status:** Awaiting response draft'
    )
    return msg


def post_to_discord(message: str, dry_run: bool = False) -> bool:
    """Post a message to Discord #reddit channel via clawdbot CLI."""
    if dry_run:
        print("--- DRY RUN ---")
        print(message)
        print("--- END ---\n")
        return True

    try:
        result = subprocess.run(
            [
                "clawdbot", "message", "send",
                "--channel", "discord",
                "--target", f"channel:{DISCORD_CHANNEL_ID}",
                "--message", message,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            log_verbose(f"Posted to Discord successfully")
            return True
        else:
            log(f"clawdbot send failed (exit {result.returncode}): {result.stderr[:200]}")
            return False

    except subprocess.TimeoutExpired:
        log("clawdbot send timed out")
        return False
    except FileNotFoundError:
        log("clawdbot not found in PATH")
        return False
    except Exception as e:
        log(f"Error posting to Discord: {e}")
        return False


# ── Main Logic ────────────────────────────────────────────────────────

def scout_subreddits(dry_run: bool = False, output_json: bool = False) -> dict:
    """
    Main scouting logic. Fetches posts, scores them, posts qualifying ones.
    Returns a summary dict.
    """
    state = load_state()
    posted_urls = set(state["posted_urls"])

    now = time.time()
    max_age_seconds = MAX_AGE_HOURS * 3600

    all_candidates = []
    subreddit_stats = {}

    for i, subreddit in enumerate(SUBREDDITS):
        if i > 0:
            time.sleep(RATE_LIMIT_DELAY)  # Be nice to Reddit

        log_verbose(f"Fetching r/{subreddit}...")
        posts = fetch_subreddit_posts(subreddit)
        log_verbose(f"  Got {len(posts)} posts from r/{subreddit}")

        sub_found = 0
        sub_skipped_old = 0
        sub_skipped_dup = 0
        sub_skipped_score = 0

        for post in posts:
            created_utc = post.get("created_utc", 0)
            age_seconds = now - created_utc
            permalink = post.get("permalink", "")
            url = f"https://www.reddit.com{permalink}" if permalink else post.get("url", "")

            # Skip old posts
            if age_seconds > max_age_seconds:
                sub_skipped_old += 1
                continue

            # Skip already-posted
            if url in posted_urls:
                sub_skipped_dup += 1
                continue

            # Score the post
            score, matched_keywords = score_post(post)
            if score < MIN_SCORE:
                sub_skipped_score += 1
                log_verbose(f"  Skip (score {score:.1f} < {MIN_SCORE}): {post.get('title', '')[:60]}")
                continue

            sub_found += 1
            all_candidates.append({
                "post": post,
                "subreddit": subreddit,
                "score": score,
                "matched_keywords": matched_keywords,
                "url": url,
            })

        subreddit_stats[subreddit] = {
            "fetched": len(posts),
            "qualifying": sub_found,
            "skipped_old": sub_skipped_old,
            "skipped_duplicate": sub_skipped_dup,
            "skipped_low_score": sub_skipped_score,
        }
        log_verbose(f"  r/{subreddit}: {sub_found} qualifying, {sub_skipped_dup} dupes, {sub_skipped_old} old, {sub_skipped_score} low-score")

    # Sort by score descending, take top N
    all_candidates.sort(key=lambda c: c["score"], reverse=True)
    to_post = all_candidates[:MAX_POSTS_PER_RUN]

    log(f"Found {len(all_candidates)} qualifying posts total, posting top {len(to_post)}")

    # Post to Discord
    posted_count = 0
    posted_details = []

    for candidate in to_post:
        msg = format_discord_message(
            candidate["post"],
            candidate["subreddit"],
            candidate["score"],
            candidate["matched_keywords"],
        )

        success = post_to_discord(msg, dry_run=dry_run)
        if success:
            posted_count += 1
            state["posted_urls"].append(candidate["url"])
            state["total_posted"] = state.get("total_posted", 0) + (0 if dry_run else 1)
            posted_details.append({
                "subreddit": candidate["subreddit"],
                "title": candidate["post"].get("title", ""),
                "url": candidate["url"],
                "score": candidate["score"],
                "keywords": candidate["matched_keywords"],
            })

            # Small delay between Discord posts to avoid rate limiting
            if not dry_run and posted_count < len(to_post):
                time.sleep(1)

    # Save state
    if not dry_run:
        save_state(state)
    else:
        log("Dry run — state not saved")

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "subreddit_stats": subreddit_stats,
        "total_candidates": len(all_candidates),
        "total_posted": posted_count,
        "total_lifetime_posted": state.get("total_posted", 0),
        "posted": posted_details,
    }

    return summary


def main():
    global VERBOSE

    dry_run = "--dry-run" in sys.argv
    output_json = "--json" in sys.argv
    VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv

    log(f"Starting Reddit scout run at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        summary = scout_subreddits(dry_run=dry_run, output_json=output_json)

        if output_json:
            print(json.dumps(summary, indent=2))
        else:
            # Human-readable summary to stderr
            log(f"Run complete: {summary['total_candidates']} candidates, {summary['total_posted']} posted")
            for entry in summary["posted"]:
                log(f"  ✅ r/{entry['subreddit']}: {entry['title'][:60]}... (score: {entry['score']:.1f})")

            if summary["total_posted"] == 0 and summary["total_candidates"] == 0:
                log("No qualifying posts found this run — that's normal!")

    except Exception as e:
        log(f"Fatal error: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
