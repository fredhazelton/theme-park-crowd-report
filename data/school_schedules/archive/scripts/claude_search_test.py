#!/usr/bin/env python3
"""
Test: Let Claude (Sonnet) find school calendar dates using web search + fetch tools.
Instead of Python heuristics for source selection, Claude reasons about which
results to check and extracts dates directly.
"""
import json
import os
import re
import subprocess
import urllib.request
import urllib.parse
import time
from datetime import datetime

BRAVE_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

GROUND_TRUTH = {
    "Satsuma City": {"state": "AL", "first_day": "2025-08-07", "last_day": "2026-05-22", "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02", "spring_break_start": "2026-04-13", "spring_break_end": "2026-04-17"},
    "Barbour County": {"state": "AL", "first_day": "2025-08-05", "last_day": "2026-05-21", "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02", "spring_break_start": "2026-03-30", "spring_break_end": "2026-04-03"},
    "Chilton County": {"state": "AL", "first_day": "2025-08-08", "last_day": "2026-05-21", "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02", "spring_break_start": "2026-03-23", "spring_break_end": "2026-03-27"},
    "Crenshaw County": {"state": "AL", "first_day": "2025-08-06", "last_day": "2026-05-21", "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02", "spring_break_start": "2026-03-30", "spring_break_end": "2026-04-03"},
    "Daleville City": {"state": "AL", "first_day": "2025-08-05", "last_day": "2026-05-21", "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-06", "spring_break_start": "2026-03-23", "spring_break_end": "2026-03-27"},
    "Elba City": {"state": "AL", "first_day": "2025-08-07", "last_day": "2026-05-21", "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-02", "spring_break_start": "2026-03-30", "spring_break_end": "2026-04-03"},
    "Midfield City": {"state": "AL", "first_day": "2025-08-07", "last_day": "2026-05-22", "winter_break_start": "2025-12-22", "winter_break_end": "2026-01-05", "spring_break_start": "2026-03-23", "spring_break_end": "2026-03-27"},
    "Thomasville City": {"state": "AL", "first_day": "2025-08-07", "last_day": "2026-05-22", "winter_break_start": "2025-12-19", "winter_break_end": "2026-01-02", "spring_break_start": "2026-03-30", "spring_break_end": "2026-04-03"},
}


def brave_search(query):
    """Search via Brave API"""
    params = urllib.parse.urlencode({"q": query, "count": 8})
    req = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_KEY}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
        results = data.get("web", {}).get("results", [])
        return [{"title": r["title"], "url": r["url"], "description": r.get("description", "")} for r in results]


def fetch_url(url, max_chars=6000):
    """Fetch text content from URL"""
    try:
        if url.endswith(".pdf") or any(h in url for h in ["finalsite", "core-docs", "thrillshare", "myconnectsuite"]):
            pdf_path = "/tmp/claude_fetch.pdf"
            subprocess.run(["wget", "-q", "--timeout=10", url, "-O", pdf_path],
                         check=True, timeout=15)
            result = subprocess.run(["pdftotext", pdf_path, "-"],
                                  capture_output=True, text=True, timeout=10)
            return result.stdout[:max_chars]
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_chars]
    except Exception as e:
        return f"ERROR: Could not fetch - {e}"


def claude_find_dates(district_name, state):
    """
    Give Claude search+fetch tools and let it find school calendar dates.
    Claude drives the search strategy, picks sources, and extracts.
    """
    tools = [
        {
            "name": "web_search",
            "description": "Search the web for information. Returns a list of results with title, URL, and description.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "fetch_page",
            "description": "Fetch and extract text content from a URL. Works with PDFs and HTML pages. PDFs are converted to text automatically.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"}
                },
                "required": ["url"]
            }
        }
    ]

    system = """You are a research assistant finding school calendar dates. Your job is to find ACCURATE dates for a specific school district.

IMPORTANT RULES:
- Find the OFFICIAL 2025-2026 school calendar for the specific district
- Prefer PDF calendars from the district's own website
- Look for "nine weeks" or "grading period" tables — they reliably show first/last day
- Alabama schools typically start in early August (Aug 4-11), NOT mid-August
- If you see Aug 18/19 as first day for a small Alabama district, that's likely wrong — dig deeper
- DO NOT use data from schools-calendar.com or similar aggregators — they are often wrong
- If you cannot find reliable dates, return null — never guess
- Cross-reference multiple sources when possible

When done, return your final answer as a JSON object with these fields:
first_day, last_day, winter_break_start, winter_break_end, spring_break_start, spring_break_end
All dates in YYYY-MM-DD format. Use null for any field you cannot verify."""

    messages = [
        {"role": "user", "content": f"Find the 2025-2026 school calendar dates for {district_name} School District in {state}. Search for their official calendar, find the PDF if possible, and extract the key dates."}
    ]

    # Run tool-use loop
    max_turns = 6
    for turn in range(max_turns):
        body = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1500,
            "system": system,
            "tools": tools,
            "messages": messages
        })

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body.encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01"
            }
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            response = json.loads(resp.read())

        # Check for tool calls
        tool_calls = [b for b in response.get("content", []) if b.get("type") == "tool_use"]
        text_blocks = [b for b in response.get("content", []) if b.get("type") == "text"]

        if not tool_calls:
            # No more tool calls — extract final answer from text
            final_text = " ".join(b["text"] for b in text_blocks)
            json_match = re.search(r'\{[^{}]*\}', final_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            return None

        # Process tool calls
        messages.append({"role": "assistant", "content": response["content"]})
        
        tool_results = []
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_input = tc["input"]
            
            if tool_name == "web_search":
                print(f"    🔍 Search: {tool_input['query']}")
                try:
                    results = brave_search(tool_input["query"])
                    result_text = json.dumps(results, indent=2)
                except Exception as e:
                    result_text = f"Search error: {e}"
                time.sleep(0.5)
            elif tool_name == "fetch_page":
                url = tool_input["url"]
                print(f"    📄 Fetch: {url[:80]}...")
                try:
                    result_text = fetch_url(url)
                except Exception as e:
                    result_text = f"Fetch error: {e}"
                time.sleep(0.3)
            else:
                result_text = "Unknown tool"
            
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": result_text[:8000]
            })
        
        messages.append({"role": "user", "content": tool_results})

        # Check stop reason
        if response.get("stop_reason") == "end_turn":
            final_text = " ".join(b.get("text", "") for b in text_blocks)
            json_match = re.search(r'\{[^{}]*\}', final_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass

    return None


def main():
    print("=" * 70)
    print("CLAUDE-DRIVEN SEARCH TEST")
    print(f"Letting Sonnet find dates for 8 Alabama districts")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    results = {}
    fields = ['first_day', 'last_day', 'winter_break_start', 'winter_break_end', 'spring_break_start', 'spring_break_end']
    total = 0
    correct = 0
    wrong = 0
    null = 0

    for name, truth in GROUND_TRUTH.items():
        print(f"\n{'='*60}")
        print(f"  {name}, {truth['state']}")
        print(f"{'='*60}")

        try:
            dates = claude_find_dates(name, truth['state'])
        except Exception as e:
            print(f"  ERROR: {e}")
            dates = None

        results[name] = dates
        
        if dates:
            print(f"\n  Results:")
            for f in fields:
                t = truth.get(f)
                g = dates.get(f)
                total += 1
                if t == g:
                    correct += 1
                    mark = "✅"
                elif not g or g == "null" or g is None:
                    null += 1
                    mark = "⬜"
                else:
                    wrong += 1
                    mark = "❌"
                print(f"    {mark} {f:<22} truth={t}  got={g}")
        else:
            print("  No dates returned")
            for f in fields:
                total += 1
                null += 1
        
        time.sleep(2)  # Rate limit

    print(f"\n{'='*70}")
    print(f"FINAL SCORE: {correct}/{total} correct ({correct/total*100:.0f}%), {wrong} wrong, {null} null")
    print(f"Compare to V1 scraper: 13/48 = 27% (35 wrong)")
    print(f"Compare to V2 scraper: 13/48 = 27% (5 wrong, 30 null)")
    print(f"Claude search: {correct}/48 = {correct/48*100:.0f}% ({wrong} wrong, {null} null)")

    with open("claude_search_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "methodology": "claude_sonnet_with_search_tools",
            "results": results,
            "ground_truth": {k: {f: v[f] for f in fields} for k, v in GROUND_TRUTH.items()},
            "score": {"correct": correct, "wrong": wrong, "null": null, "total": total}
        }, f, indent=2)

    print(f"\nSaved to claude_search_results.json")


if __name__ == "__main__":
    main()
