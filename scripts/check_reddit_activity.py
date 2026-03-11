#!/usr/bin/env python3
"""
Check u/disneystatswhiz Reddit activity.
Returns recent comments and posts for tracking engagement.
"""
import json
import sys
import requests
from datetime import datetime, timezone

USERNAME = "disneystatswhiz"
USER_AGENT = "hazeydata-tracker/1.0"

def fetch_activity():
    url = f"https://www.reddit.com/user/{USERNAME}/overview.json"
    params = {"limit": 25, "raw_json": 1, "sort": "new"}
    headers = {"User-Agent": USER_AGENT}
    
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"Error: HTTP {resp.status_code}", file=sys.stderr)
        return []
    
    data = resp.json()
    children = data.get("data", {}).get("children", [])
    
    activity = []
    for child in children:
        item = child["data"]
        created = datetime.fromtimestamp(item["created_utc"], tz=timezone.utc)
        
        if child["kind"] == "t1":  # Comment
            activity.append({
                "type": "comment",
                "subreddit": item.get("subreddit", ""),
                "thread_title": item.get("link_title", ""),
                "body_preview": item.get("body", "")[:200],
                "score": item.get("score", 0),
                "permalink": f"https://reddit.com{item.get('permalink', '')}",
                "created": created.isoformat(),
                "age_hours": (datetime.now(timezone.utc) - created).total_seconds() / 3600,
            })
        elif child["kind"] == "t3":  # Post
            activity.append({
                "type": "post",
                "subreddit": item.get("subreddit", ""),
                "title": item.get("title", ""),
                "score": item.get("score", 0),
                "num_comments": item.get("num_comments", 0),
                "permalink": f"https://reddit.com{item.get('permalink', '')}",
                "created": created.isoformat(),
                "age_hours": (datetime.now(timezone.utc) - created).total_seconds() / 3600,
            })
    
    return activity

def main():
    activity = fetch_activity()
    
    # Filter to last 7 days
    recent = [a for a in activity if a["age_hours"] <= 168]
    
    summary = {
        "username": USERNAME,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "last_7_days": {
            "total": len(recent),
            "comments": len([a for a in recent if a["type"] == "comment"]),
            "posts": len([a for a in recent if a["type"] == "post"]),
        },
        "recent_activity": recent[:10],
    }
    
    if "--json" in sys.argv:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Reddit Activity — u/{USERNAME}")
        print(f"Last 7 days: {summary['last_7_days']['comments']} comments, {summary['last_7_days']['posts']} posts")
        for a in recent[:10]:
            kind = "💬" if a["type"] == "comment" else "📝"
            title = a.get("thread_title") or a.get("title", "")
            print(f"  {kind} r/{a['subreddit']} — {title[:60]} (⬆️{a['score']}, {a['age_hours']:.0f}h ago)")

if __name__ == "__main__":
    main()
