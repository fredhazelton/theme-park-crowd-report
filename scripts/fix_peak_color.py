#!/usr/bin/env python3
"""
Fix PEAK metric color from red to teal in stream-dashboard.html

This script finds and replaces red color styling for the PEAK metric
with teal to match the other metric cards.

Usage:
    python scripts/fix_peak_color.py [path-to-dashboard.html]
    
Default path: /home/wilma/clawd-anthropic/streaming/stream-dashboard.html
"""

import re
import sys
from pathlib import Path

# Default path on server
DEFAULT_PATH = Path("/home/wilma/clawd-anthropic/streaming/stream-dashboard.html")

# Red color codes to look for
RED_COLORS = [
    "#ff1a5c",  # red-light
    "#A60038",  # red
    "var(--red-light)",
    "var(--red)",
    "rgb(255, 26, 92)",
    "rgb(166, 0, 56)",
]

# Teal replacement
TEAL_COLOR = "#4a90a4"  # Main teal/cyan color


def fix_peak_color(file_path: Path) -> bool:
    """Fix PEAK metric color from red to teal."""
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        return False
    
    # Read file
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Pattern 1: Find PEAK in context with red colors
    # Look for patterns like: PEAK...color: #ff1a5c or similar
    for red in RED_COLORS:
        # Pattern: PEAK followed by red color (case insensitive)
        pattern = re.compile(
            r'(PEAK[^>]*?)(color\s*:\s*)' + re.escape(red),
            re.IGNORECASE
        )
        content = pattern.sub(r'\1\2' + TEAL_COLOR, content)
        
        # Pattern: nth-child(2) for second metric card with red
        pattern2 = re.compile(
            r'(nth-child\(2\)[^>]*?)(color\s*:\s*)' + re.escape(red),
            re.IGNORECASE
        )
        content = pattern2.sub(r'\1\2' + TEAL_COLOR, content)
    
    # Pattern 2: CSS class or ID containing "peak" with red color
    for red in RED_COLORS:
        # .peak-value { color: #ff1a5c; }
        pattern = re.compile(
            r'(\.peak[^}]*?color\s*:\s*)' + re.escape(red),
            re.IGNORECASE
        )
        content = pattern.sub(r'\1' + TEAL_COLOR, content)
        
        # #peak { color: #ff1a5c; }
        pattern = re.compile(
            r'(#peak[^}]*?color\s*:\s*)' + re.escape(red),
            re.IGNORECASE
        )
        content = pattern.sub(r'\1' + TEAL_COLOR, content)
    
    # Pattern 3: Inline style with PEAK and red
    for red in RED_COLORS:
        # <div class="metric" style="...">PEAK...color: #ff1a5c
        pattern = re.compile(
            r'(<[^>]*PEAK[^>]*style="[^"]*?)(color\s*:\s*)' + re.escape(red),
            re.IGNORECASE
        )
        content = pattern.sub(r'\1\2' + TEAL_COLOR, content)
    
    # Pattern 4: Second metric card (nth-child(2)) - common pattern
    # Look for second stat-box or metric-card with red
    for red in RED_COLORS:
        # .stat-box:nth-child(2) .value { color: #ff1a5c; }
        pattern = re.compile(
            r'(\.(?:stat-box|metric-card|metric):nth-child\(2\)[^}]*?color\s*:\s*)' + re.escape(red),
            re.IGNORECASE
        )
        content = pattern.sub(r'\1' + TEAL_COLOR, content)
    
    # Pattern 5: JavaScript that sets color for PEAK or second metric
    for red in RED_COLORS:
        # element.style.color = "#ff1a5c" in context of PEAK
        pattern = re.compile(
            r'(PEAK[^;]*?\.style\.color\s*=\s*["\'])(' + re.escape(red) + r')(["\'])',
            re.IGNORECASE
        )
        content = pattern.sub(r'\1' + TEAL_COLOR + r'\3', content)
        
        # querySelector for second metric setting red
        pattern = re.compile(
            r'(querySelector\([^)]*nth-child\(2\)[^)]*\)[^;]*?\.style\.color\s*=\s*["\'])(' + re.escape(red) + r')(["\'])',
            re.IGNORECASE
        )
        content = pattern.sub(r'\1' + TEAL_COLOR + r'\3', content)
    
    # Check if we made any changes
    if content == original_content:
        print("No changes made. PEAK metric might already be teal, or pattern not found.")
        print("Searching for PEAK occurrences...")
        peak_matches = re.findall(r'PEAK[^<]{0,100}', content, re.IGNORECASE)
        if peak_matches:
            print(f"Found {len(peak_matches)} PEAK references:")
            for match in peak_matches[:5]:  # Show first 5
                print(f"  ...{match[:80]}...")
        return False
    
    # Create backup
    backup_path = file_path.with_suffix(file_path.suffix + '.backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(original_content)
    print(f"Backup created: {backup_path}")
    
    # Write updated content
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Fixed PEAK metric color in: {file_path}")
    print(f"   Changed red colors to teal: {TEAL_COLOR}")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
    else:
        file_path = DEFAULT_PATH
    
    success = fix_peak_color(file_path)
    sys.exit(0 if success else 1)
