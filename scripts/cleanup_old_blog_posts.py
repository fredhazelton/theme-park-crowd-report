#!/usr/bin/env python3
"""
cleanup_old_blog_posts.py — Archive stale weekly blog posts.

Weekly "This Week" articles are only relevant for ~7 days after their date range.
This script moves superseded weekly articles to blog/archive/ to prevent accumulation.

Run after each new blog post generation, or on a weekly cron.

Usage:
  python cleanup_old_blog_posts.py              # Archive stale posts
  python cleanup_old_blog_posts.py --dry-run    # Preview what would be archived
  python cleanup_old_blog_posts.py --days 14    # Custom staleness threshold (default: 14)

Keeps:
  - All evergreen articles (what-is-wti, new-metric, etc.)
  - The most recent weekly article per region
  - Blog index, CSS, drafts
"""

import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

BLOG_DIR = Path.home() / "hazeydata.ai" / "blog"
ARCHIVE_DIR = BLOG_DIR / "archive"

# Patterns for weekly articles
WEEKLY_PATTERN = re.compile(r"^(orlando|disneyland|tokyo)-this-week-(\w+-\d+-\d+)\.html$")

# Month name → number
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_article_date(filename: str) -> date | None:
    """Extract date from weekly article filename like 'orlando-this-week-march-18-2026.html'."""
    m = WEEKLY_PATTERN.match(filename)
    if not m:
        return None
    date_part = m.group(2)  # e.g., "march-18-2026"
    parts = date_part.split("-")
    if len(parts) != 3:
        return None
    try:
        month = MONTHS.get(parts[0].lower())
        day = int(parts[1])
        year = int(parts[2])
        if month:
            return date(year, month, day)
    except (ValueError, KeyError):
        pass
    return None


def get_region(filename: str) -> str | None:
    """Extract region from weekly article filename."""
    m = WEEKLY_PATTERN.match(filename)
    return m.group(1) if m else None


def main():
    dry_run = "--dry-run" in sys.argv
    days_threshold = 14
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            days_threshold = int(sys.argv[idx + 1])

    today = date.today()
    cutoff = today - timedelta(days=days_threshold)

    # Discover all weekly articles
    weekly_articles = []
    for html_file in BLOG_DIR.glob("*.html"):
        if html_file.name == "index.html":
            continue
        article_date = parse_article_date(html_file.name)
        if article_date:
            region = get_region(html_file.name)
            weekly_articles.append({
                "path": html_file,
                "date": article_date,
                "region": region,
            })

    # Find the newest article per region (always keep)
    newest_per_region = {}
    for a in weekly_articles:
        region = a["region"]
        if region not in newest_per_region or a["date"] > newest_per_region[region]["date"]:
            newest_per_region[region] = a

    # Determine what to archive
    to_archive = []
    for a in weekly_articles:
        is_newest = a["path"] == newest_per_region.get(a["region"], {}).get("path")
        is_stale = a["date"] < cutoff

        if is_stale and not is_newest:
            to_archive.append(a)

    if not to_archive:
        print(f"✅ No stale weekly articles to archive (threshold: {days_threshold} days)")
        return

    print(f"📦 Found {len(to_archive)} stale weekly article(s) to archive:")
    for a in sorted(to_archive, key=lambda x: x["date"]):
        age = (today - a["date"]).days
        print(f"  - {a['path'].name} (age: {age} days)")

    if dry_run:
        print("\n🏃 DRY RUN — no files moved.")
        return

    # Create archive directory
    ARCHIVE_DIR.mkdir(exist_ok=True)

    for a in to_archive:
        dest = ARCHIVE_DIR / a["path"].name
        shutil.move(str(a["path"]), str(dest))
        print(f"  📁 Archived: {a['path'].name}")

    print(f"\n✅ Archived {len(to_archive)} article(s) to blog/archive/")
    print("💡 Remember to update blog/index.html if it lists these articles.")


if __name__ == "__main__":
    main()
