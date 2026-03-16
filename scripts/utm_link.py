#!/usr/bin/env python3
"""
utm_link.py — Generate hazeydata.ai links with UTM tracking parameters.

Usage:
  python utm_link.py <page>                          # Default: reddit organic
  python utm_link.py <page> --source twitter         # Twitter
  python utm_link.py <page> --source reddit --content comment
  python utm_link.py blog/what-is-wti.html           # Blog article link
  python utm_link.py year-view.html                  # Year view
  python utm_link.py                                 # Homepage

Pre-built shortcuts:
  python utm_link.py --reddit                        # Reddit organic link to homepage
  python utm_link.py --twitter                       # Twitter link to homepage
  python utm_link.py --discord                       # Discord link to homepage

Examples for Fred's Reddit comments:
  python utm_link.py blog/what-is-wti.html --reddit
  → https://hazeydata.ai/blog/what-is-wti.html?utm_source=reddit&utm_medium=organic&utm_campaign=disneystatswhiz

  python utm_link.py year-view.html --reddit --content spring-break-tip
  → https://hazeydata.ai/year-view.html?utm_source=reddit&utm_medium=organic&utm_campaign=disneystatswhiz&utm_content=spring-break-tip
"""

import sys
from urllib.parse import urlencode

BASE = "https://hazeydata.ai/theme-park-crowd-report"

PRESETS = {
    "reddit": {"source": "reddit", "medium": "organic", "campaign": "disneystatswhiz"},
    "twitter": {"source": "twitter", "medium": "social", "campaign": "blog_promo"},
    "discord": {"source": "discord", "medium": "community", "campaign": "discord_server"},
}


def build_utm_url(page: str = "", source: str = "reddit", medium: str = "organic",
                   campaign: str = "disneystatswhiz", content: str = "") -> str:
    """Build a full URL with UTM parameters."""
    url = f"{BASE}/{page}" if page else BASE
    # Clean double slashes
    url = url.replace("//blog", "/blog").replace("//year", "/year")

    params = {
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": campaign,
    }
    if content:
        params["utm_content"] = content

    return f"{url}?{urlencode(params)}"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate UTM-tagged hazeydata.ai links")
    parser.add_argument("page", nargs="?", default="", help="Page path (e.g., blog/what-is-wti.html)")
    parser.add_argument("--source", default=None)
    parser.add_argument("--medium", default=None)
    parser.add_argument("--campaign", default=None)
    parser.add_argument("--content", default="")
    parser.add_argument("--reddit", action="store_true", help="Use Reddit preset")
    parser.add_argument("--twitter", action="store_true", help="Use Twitter preset")
    parser.add_argument("--discord", action="store_true", help="Use Discord preset")
    args = parser.parse_args()

    # Determine preset
    if args.reddit:
        preset = PRESETS["reddit"]
    elif args.twitter:
        preset = PRESETS["twitter"]
    elif args.discord:
        preset = PRESETS["discord"]
    else:
        preset = PRESETS["reddit"]  # Default to Reddit (most common manual use)

    # Override with explicit args
    source = args.source or preset["source"]
    medium = args.medium or preset["medium"]
    campaign = args.campaign or preset["campaign"]

    url = build_utm_url(args.page, source, medium, campaign, args.content)
    print(url)


if __name__ == "__main__":
    main()
