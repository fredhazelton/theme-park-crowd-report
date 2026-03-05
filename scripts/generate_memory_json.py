#!/usr/bin/env python3
"""Generate memory.json for Mission Control v3 Memory tab.

Reads:
  ~/clawd-anthropic/MEMORY.md          — long-term memory
  ~/clawd-anthropic/memory/YYYY-MM-DD.md — daily journal files

Outputs:
  docs/analytics-data/memory.json

SECURITY: Redacts emails, phone numbers, API keys, and addresses
before writing to the public repo.
"""

import json
import os
import re
from datetime import datetime
from glob import glob
from pathlib import Path

MEMORY_MD = Path.home() / "clawd-anthropic" / "MEMORY.md"
DAILY_DIR = Path.home() / "clawd-anthropic" / "memory"
OUTPUT = Path.home() / "theme-park-crowd-report" / "docs" / "analytics-data" / "memory.json"

# ── Redaction patterns ──────────────────────────────────────────
REDACT_PATTERNS = [
    # Email addresses
    (re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'), '[redacted-email]'),
    # Phone numbers (various formats)
    (re.compile(r'(?<!\d)(\+?1?[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})(?!\d)'), '[redacted-phone]'),
    # API keys / tokens (long hex or alphanumeric strings that look like keys)
    (re.compile(r'(?:api[_-]?key|token|secret|password|bearer)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE), '[redacted-key]'),
    # sk-... style API keys
    (re.compile(r'\bsk-[a-zA-Z0-9]{20,}\b'), '[redacted-key]'),
    # Street addresses (number + street name pattern)
    (re.compile(r'\d{1,5}\s+[A-Z][a-zA-Z]+\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Ct|Court|Way|Pl|Place|Cir|Circle)\.?(?:\s*(?:#|Apt|Suite|Unit)\s*\w+)?', re.IGNORECASE), '[redacted-address]'),
]


def redact(text: str) -> str:
    """Remove sensitive info from text."""
    for pattern, replacement in REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def file_stats(path: Path) -> dict:
    """Get word count, line count, size for a file."""
    content = path.read_text(encoding="utf-8", errors="replace")
    words = len(content.split())
    lines = content.count("\n") + 1
    size_kb = round(path.stat().st_size / 1024, 1)
    mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    return {
        "words": words,
        "lines": lines,
        "size_kb": size_kb,
        "updated": mtime,
        "content": content,
    }


def parse_date_from_filename(filename: str):
    """Extract date from YYYY-MM-DD.md filename."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})\.md$", filename)
    if m:
        return m.group(1)
    return None


def main():
    result = {
        "generated_at": datetime.now().isoformat(),
        "long_term": None,
        "daily": [],
        "total_entries": 0,
    }

    # ── Long-term memory ────────────────────────────────────
    if MEMORY_MD.exists():
        stats = file_stats(MEMORY_MD)
        stats["content"] = redact(stats["content"])
        result["long_term"] = stats

    # ── Daily journal files ─────────────────────────────────
    daily_files = sorted(glob(str(DAILY_DIR / "????-??-??.md")), reverse=True)

    for fpath in daily_files:
        p = Path(fpath)
        date_str = parse_date_from_filename(p.name)
        if not date_str:
            continue

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        stats = file_stats(p)
        stats["content"] = redact(stats["content"])

        result["daily"].append({
            "date": date_str,
            "day_name": dt.strftime("%A"),
            "size_kb": stats["size_kb"],
            "words": stats["words"],
            "updated": stats["updated"],
            "content": stats["content"],
        })

    result["total_entries"] = len(result["daily"])

    # ── Write output ────────────────────────────────────────
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ memory.json written: {OUTPUT}")
    print(f"   Long-term: {result['long_term']['words']} words" if result["long_term"] else "   Long-term: not found")
    print(f"   Daily entries: {result['total_entries']}")


if __name__ == "__main__":
    main()
