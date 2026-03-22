#!/usr/bin/env python3
"""
SSD Daily Progress Report

Generates daily progress reports for School Schedules Database collection.
Posts to Discord #school-schedules channel with current metrics.

Usage:
    python3 ssd_daily_report.py --post  # Post to Discord
    python3 ssd_daily_report.py         # Print to console only
"""

import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_FILE = BASE_DIR / "v3" / "school_schedules.db"
DISTRICTS_FILE = BASE_DIR / "districts_comprehensive.csv"
STATE_FILE = BASE_DIR / "memory" / "heartbeat-state.json"

# Discord channel for #school-schedules
DISCORD_CHANNEL_ID = "1482263793013756064"

def get_current_metrics():
    """Get current SSD collection metrics."""
    if not DB_FILE.exists():
        return None
    
    conn = sqlite3.connect(DB_FILE)
    
    # Get district and enrollment counts from v3 database
    v3_districts = conn.execute('SELECT COUNT(*) FROM dim_district').fetchone()[0]
    v3_enrollment = conn.execute('SELECT COALESCE(SUM(enrollment),0) FROM dim_district').fetchone()[0]
    
    # Get confidence breakdown
    high_conf = conn.execute("SELECT COUNT(*) FROM dim_calendar_source WHERE quality_confidence='high'").fetchone()[0]
    med_conf = conn.execute("SELECT COUNT(*) FROM dim_calendar_source WHERE quality_confidence='medium'").fetchone()[0]
    low_conf = conn.execute("SELECT COUNT(*) FROM dim_calendar_source WHERE quality_confidence='low'").fetchone()[0]
    
    # Get school day counts
    total_school_days = conn.execute('SELECT COUNT(*) FROM fact_school_day').fetchone()[0]
    instructional_days = conn.execute("SELECT COUNT(*) FROM fact_school_day WHERE day_type='school'").fetchone()[0]
    non_instructional_days = total_school_days - instructional_days
    
    conn.close()
    
    # Get universe totals from CSV
    total_districts = 0
    total_enrollment = 0
    
    if DISTRICTS_FILE.exists():
        with open(DISTRICTS_FILE) as f:
            for row in csv.DictReader(f):
                total_districts += 1
                enrollment = row.get('enrollment', '0') or '0'
                try:
                    total_enrollment += int(enrollment)
                except ValueError:
                    pass
    
    # Calculate percentages
    district_pct = (v3_districts / total_districts * 100) if total_districts > 0 else 0
    enrollment_pct = (v3_enrollment / total_enrollment * 100) if total_enrollment > 0 else 0
    
    # Calculate gaps to 95%
    districts_gap_95 = int(total_districts * 0.95) - v3_districts
    enrollment_gap_95 = int(total_enrollment * 0.95) - v3_enrollment
    
    return {
        'v3_districts': v3_districts,
        'v3_enrollment': v3_enrollment,
        'total_districts': total_districts,
        'total_enrollment': total_enrollment,
        'district_pct': district_pct,
        'enrollment_pct': enrollment_pct,
        'districts_gap_95': max(0, districts_gap_95),
        'enrollment_gap_95': max(0, enrollment_gap_95),
        'high_conf': high_conf,
        'med_conf': med_conf,
        'low_conf': low_conf,
        'total_school_days': total_school_days,
        'instructional_days': instructional_days,
        'non_instructional_days': non_instructional_days,
        'timestamp': datetime.now().isoformat()
    }

def format_progress_bar(percentage, width=20):
    """Create ASCII progress bar."""
    filled = int(percentage / 100 * width)
    bar = '█' * filled + '░' * (width - filled)
    return f"{bar} {percentage:.1f}%"

def check_if_changed(current_metrics):
    """Check if metrics have changed since last report."""
    if not Path(STATE_FILE).exists():
        return True, {}
    
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        
        last_metrics = state.get('ssd', {})
        last_districts = last_metrics.get('lastReportedDistricts', 0)
        last_enrollment = last_metrics.get('lastReportedEnrollment', 0)
        
        current_districts = current_metrics['v3_districts']
        current_enrollment = current_metrics['v3_enrollment']
        
        changed = (current_districts != last_districts or 
                  current_enrollment != last_enrollment)
        
        return changed, {
            'districts_change': current_districts - last_districts,
            'enrollment_change': current_enrollment - last_enrollment
        }
    except (json.JSONDecodeError, FileError):
        return True, {}

def update_state(current_metrics):
    """Update state file with current metrics."""
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    
    state = {}
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except (json.JSONDecodeError, FileError):
            pass
    
    if 'ssd' not in state:
        state['ssd'] = {}
    
    state['ssd']['lastReportedDistricts'] = current_metrics['v3_districts']
    state['ssd']['lastReportedEnrollment'] = current_metrics['v3_enrollment']
    state['ssd']['lastReportTime'] = datetime.now().isoformat()
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def format_report(metrics, changes=None):
    """Format the progress report."""
    report_lines = [
        "🏫 **SSD Collection Progress Report**",
        "",
        f"📊 **District Coverage:** {metrics['v3_districts']:,}/{metrics['total_districts']:,} districts",
        f"{format_progress_bar(metrics['district_pct'])}",
        f"Gap to 95%: **{metrics['districts_gap_95']:,} districts**",
        "",
        f"👥 **Enrollment Coverage:** {metrics['v3_enrollment']:,}/{metrics['total_enrollment']:,} students",  
        f"{format_progress_bar(metrics['enrollment_pct'])}",
        f"Gap to 95%: **{metrics['enrollment_gap_95']:,} enrollment**",
        "",
        f"🔍 **Quality Breakdown:**",
        f"• High confidence: {metrics['high_conf']:,}",
        f"• Medium confidence: {metrics['med_conf']:,}",
        f"• Low confidence: {metrics['low_conf']:,}",
        "",
        f"📅 **Calendar Data:**",
        f"• Total school days collected: {metrics['total_school_days']:,}",
        f"• Instructional days: {metrics['instructional_days']:,}",
        f"• Non-instructional days: {metrics['non_instructional_days']:,}",
    ]
    
    if changes:
        if changes.get('districts_change', 0) > 0 or changes.get('enrollment_change', 0) > 0:
            report_lines.extend([
                "",
                f"📈 **Since last report:**",
                f"• +{changes['districts_change']:,} districts",
                f"• +{changes['enrollment_change']:,} enrollment",
            ])
    
    report_lines.extend([
        "",
        f"🎯 **Target:** 95% coverage = {int(metrics['total_districts']*0.95):,} districts, {int(metrics['total_enrollment']*0.95):,} enrollment",
        f"⏰ *Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} EDT*"
    ])
    
    return "\n".join(report_lines)

def post_to_discord(message):
    """Post message to Discord #school-schedules channel."""
    try:
        cmd = [
            "clawdbot", "message", "send",
            "--channel", "discord",
            "--target", DISCORD_CHANNEL_ID,
            "--message", message
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, "Posted successfully"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to post: {e.stderr}"
    except FileNotFoundError:
        return False, "clawdbot command not found"

def main():
    parser = argparse.ArgumentParser(description='SSD Daily Progress Report')
    parser.add_argument('--post', action='store_true',
                       help='Post to Discord #school-schedules channel')
    parser.add_argument('--force', action='store_true',
                       help='Post even if metrics unchanged')
    
    args = parser.parse_args()
    
    # Get current metrics
    metrics = get_current_metrics()
    if not metrics:
        print("Error: Could not load SSD metrics (database missing?)")
        sys.exit(1)
    
    # Check if changed
    changed, changes = check_if_changed(metrics)
    
    # Format report
    report = format_report(metrics, changes)
    
    if args.post:
        if changed or args.force:
            success, message = post_to_discord(report)
            if success:
                print("Posted to Discord successfully")
                update_state(metrics)
            else:
                print(f"Failed to post: {message}")
                sys.exit(1)
        else:
            print("Metrics unchanged since last report. Use --force to post anyway.")
    else:
        print(report)

if __name__ == "__main__":
    main()