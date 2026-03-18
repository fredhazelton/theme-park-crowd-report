#!/usr/bin/env python3
"""SSD (School Schedule Data) Quality Validation Script.

Validates quality of school calendar data by detecting:
1. Duplicate dates (likely hallucinated entries)
2. Implausible date ranges
3. Break length sanity checks  
4. State-level consistency outliers
5. Suspicious source URLs

Usage: python3 ssd_quality_check.py [--input llm_scraper_results.json]

Exit codes: 0 if quality_score > 0.8, 1 otherwise (for CI/QA)
"""

from __future__ import annotations
import argparse, json, os, sys, re, urllib.parse
from collections import defaultdict, Counter
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from statistics import median
from typing import Dict, List, Set, Optional, Tuple, Any

BASE_DIR = Path(__file__).parent
DEFAULT_INPUT = BASE_DIR / "llm_scraper_results.json"
DEFAULT_OUTPUT = BASE_DIR / "ssd_quality_report.json"

@dataclass
class QualityIssue:
    issue_type: str
    description: str
    severity: str = "medium"  # low, medium, high

@dataclass
class QualityReport:
    total_found: int
    flagged: int
    clean: int
    quality_score: float
    issues_by_type: Dict[str, int]
    flagged_entries: Dict[str, Dict[str, Any]]

class SSDQualityChecker:
    """Base class for SSD quality validation - designed for reuse across data products."""
    
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.issues_by_entry: Dict[str, List[QualityIssue]] = defaultdict(list)
        self.duplicate_threshold = 20  # Flag date combos shared by 20+ districts
        
    def run_checks(self) -> QualityReport:
        """Main entry point - run all validation checks and return report."""
        print("🔍 Running SSD Quality Validation...")
        
        found_entries = {k: v for k, v in self.data.items() 
                        if v.get('status') == 'found'}
        
        print(f"   Found entries to validate: {len(found_entries)}")
        
        # Run all validation checks
        self._check_duplicate_dates(found_entries)
        self._check_date_plausibility(found_entries) 
        self._check_break_length_sanity(found_entries)
        self._check_state_consistency(found_entries)
        self._check_suspicious_urls(found_entries)
        
        return self._generate_report(found_entries)
        
    def _check_duplicate_dates(self, entries: Dict[str, Any]) -> None:
        """Check #1: Flag entries sharing identical date combos (likely hallucinated)."""
        print("   Checking for duplicate date patterns...")
        
        date_combos = defaultdict(list)
        
        for nces_id, entry in entries.items():
            dates = entry.get('dates', {})
            
            # Create signature from all available dates
            date_sig = tuple(sorted([
                (k, v) for k, v in dates.items() 
                if k != 'school_year' and v and v != 'null'
            ]))
            
            if date_sig:  # Only track if we have actual dates
                date_combos[date_sig].append(nces_id)
        
        # Flag combos shared by threshold+ districts
        for date_sig, district_list in date_combos.items():
            if len(district_list) >= self.duplicate_threshold:
                for nces_id in district_list:
                    self.issues_by_entry[nces_id].append(QualityIssue(
                        issue_type="duplicate_dates",
                        description=f"Shares identical dates with {len(district_list)} other districts",
                        severity="high"
                    ))
        
        duplicates_found = sum(1 for districts in date_combos.values() 
                             if len(districts) >= self.duplicate_threshold)
        print(f"      → Found {duplicates_found} duplicate date patterns")
    
    def _check_date_plausibility(self, entries: Dict[str, Any]) -> None:
        """Check #2: Validate dates fall within expected ranges for 2025-26."""
        print("   Checking date plausibility...")
        
        expected_ranges = {
            'first_day': (date(2025, 7, 1), date(2025, 9, 30)),
            'last_day': (date(2026, 4, 1), date(2026, 7, 31)), 
            'spring_break_start': (date(2026, 2, 1), date(2026, 5, 31)),
            'spring_break_end': (date(2026, 2, 1), date(2026, 5, 31)),
            'winter_break_start': (date(2025, 11, 1), date(2026, 1, 31)),
            'winter_break_end': (date(2025, 11, 1), date(2026, 1, 31))
        }
        
        implausible_count = 0
        
        for nces_id, entry in entries.items():
            dates = entry.get('dates', {})
            
            for date_field, date_str in dates.items():
                if date_field in expected_ranges and date_str:
                    try:
                        actual_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        min_date, max_date = expected_ranges[date_field]
                        
                        if not (min_date <= actual_date <= max_date):
                            self.issues_by_entry[nces_id].append(QualityIssue(
                                issue_type="implausible_dates",
                                description=f"{date_field} ({date_str}) outside expected range {min_date} to {max_date}",
                                severity="high"
                            ))
                            implausible_count += 1
                            
                    except ValueError:
                        self.issues_by_entry[nces_id].append(QualityIssue(
                            issue_type="invalid_date_format",
                            description=f"Invalid date format: {date_field} = {date_str}",
                            severity="medium"
                        ))
                        
        print(f"      → Found {implausible_count} implausible dates")
    
    def _check_break_length_sanity(self, entries: Dict[str, Any]) -> None:
        """Check #3: Validate break lengths and school year duration."""
        print("   Checking break length sanity...")
        
        invalid_lengths = 0
        
        for nces_id, entry in entries.items():
            dates = entry.get('dates', {})
            
            try:
                # Spring break length check
                if dates.get('spring_break_start') and dates.get('spring_break_end'):
                    start = datetime.strptime(dates['spring_break_start'], '%Y-%m-%d').date()
                    end = datetime.strptime(dates['spring_break_end'], '%Y-%m-%d').date()
                    length = (end - start).days + 1
                    
                    if not (2 <= length <= 14):
                        self.issues_by_entry[nces_id].append(QualityIssue(
                            issue_type="invalid_break_length",
                            description=f"Spring break length {length} days (expected 2-14)",
                            severity="medium"
                        ))
                        invalid_lengths += 1
                
                # Winter break length check  
                if dates.get('winter_break_start') and dates.get('winter_break_end'):
                    start = datetime.strptime(dates['winter_break_start'], '%Y-%m-%d').date()
                    end = datetime.strptime(dates['winter_break_end'], '%Y-%m-%d').date()
                    length = (end - start).days + 1
                    
                    if not (7 <= length <= 21):
                        self.issues_by_entry[nces_id].append(QualityIssue(
                            issue_type="invalid_break_length", 
                            description=f"Winter break length {length} days (expected 7-21)",
                            severity="medium"
                        ))
                        invalid_lengths += 1
                
                # School year length check
                if dates.get('first_day') and dates.get('last_day'):
                    start = datetime.strptime(dates['first_day'], '%Y-%m-%d').date()
                    end = datetime.strptime(dates['last_day'], '%Y-%m-%d').date()
                    length = (end - start).days + 1
                    
                    if not (150 <= length <= 300):
                        self.issues_by_entry[nces_id].append(QualityIssue(
                            issue_type="invalid_year_length",
                            description=f"School year length {length} days (expected 150-300)",
                            severity="medium"
                        ))
                        invalid_lengths += 1
                        
            except ValueError:
                # Skip entries with malformed dates (already flagged above)
                pass
                
        print(f"      → Found {invalid_lengths} invalid break/year lengths")
    
    def _check_state_consistency(self, entries: Dict[str, Any]) -> None:
        """Check #4: Flag outliers within each state (spring break >30 days from median)."""
        print("   Checking state-level consistency...")
        
        # Group by state and collect spring break dates
        by_state = defaultdict(list)
        
        for nces_id, entry in entries.items():
            state = entry.get('state')
            dates = entry.get('dates', {})
            
            if state and dates.get('spring_break_start'):
                try:
                    sb_date = datetime.strptime(dates['spring_break_start'], '%Y-%m-%d').date()
                    by_state[state].append((nces_id, sb_date))
                except ValueError:
                    pass
        
        outliers_found = 0
        
        # Check each state for outliers
        for state, date_list in by_state.items():
            if len(date_list) < 3:  # Need at least 3 to identify outliers
                continue
                
            dates_only = [d[1] for d in date_list]
            # Convert to ordinals for median calculation, then back to date
            ordinals = [d.toordinal() for d in dates_only]
            median_ordinal = median(ordinals)
            median_date = date.fromordinal(int(median_ordinal))
            
            for nces_id, sb_date in date_list:
                days_diff = abs((sb_date - median_date).days)
                
                if days_diff > 30:
                    self.issues_by_entry[nces_id].append(QualityIssue(
                        issue_type="state_outlier",
                        description=f"Spring break {days_diff} days from {state} median ({median_date})",
                        severity="medium"
                    ))
                    outliers_found += 1
        
        print(f"      → Found {outliers_found} state consistency outliers")
    
    def _check_suspicious_urls(self, entries: Dict[str, Any]) -> None:
        """Check #5: Flag generic/suspicious source URLs."""
        print("   Checking for suspicious URLs...")
        
        suspicious_patterns = [
            r'.*\.state\.[a-z]+\.us.*',  # State dept of education sites
            r'.*education\.state\..*',
            r'.*doe\.state\..*',
            r'.*\.gov/.*/districts$',    # Generic district listing pages
            r'.*\.gov/.*/schools$',
            r'.*/.*/about/?$',           # Generic about pages
            r'.*/.*/contact/?$'          # Contact pages
        ]
        
        suspicious_count = 0
        
        for nces_id, entry in entries.items():
            url = entry.get('url', '')
            
            if url:
                for pattern in suspicious_patterns:
                    if re.match(pattern, url, re.IGNORECASE):
                        self.issues_by_entry[nces_id].append(QualityIssue(
                            issue_type="suspicious_url",
                            description=f"URL looks generic/non-district-specific: {url}",
                            severity="low"
                        ))
                        suspicious_count += 1
                        break
                        
        print(f"      → Found {suspicious_count} suspicious URLs")
    
    def _generate_report(self, found_entries: Dict[str, Any]) -> QualityReport:
        """Generate final quality report."""
        
        flagged_entries = {}
        issues_by_type = Counter()
        
        # Build flagged entries and count issues
        for nces_id, issues in self.issues_by_entry.items():
            if issues:
                flagged_entries[nces_id] = {
                    'issues': [
                        {
                            'type': issue.issue_type,
                            'description': issue.description, 
                            'severity': issue.severity
                        } for issue in issues
                    ],
                    'entry': found_entries.get(nces_id, {})
                }
                
                for issue in issues:
                    issues_by_type[issue.issue_type] += 1
        
        total_found = len(found_entries)
        flagged = len(flagged_entries)
        clean = total_found - flagged
        quality_score = clean / total_found if total_found > 0 else 0.0
        
        return QualityReport(
            total_found=total_found,
            flagged=flagged,
            clean=clean,
            quality_score=quality_score,
            issues_by_type=dict(issues_by_type),
            flagged_entries=flagged_entries
        )

def main():
    parser = argparse.ArgumentParser(description="SSD Quality Validation")
    parser.add_argument('--input', default=DEFAULT_INPUT, 
                       help=f"Input JSON file (default: {DEFAULT_INPUT})")
    parser.add_argument('--output', default=DEFAULT_OUTPUT,
                       help=f"Output report file (default: {DEFAULT_OUTPUT})")
    
    args = parser.parse_args()
    
    # Load data
    try:
        with open(args.input) as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error loading {args.input}: {e}")
        return 1
    
    # Run quality checks
    checker = SSDQualityChecker(data)
    report = checker.run_checks()
    
    # Print summary to stdout
    print("\n📊 SSD Quality Report Summary")
    print("=" * 40)
    print(f"Total 'found' entries:     {report.total_found:,}")
    print(f"Clean entries:             {report.clean:,}")  
    print(f"Flagged entries:           {report.flagged:,}")
    print(f"Overall quality score:     {report.quality_score:.3f}")
    print()
    
    print("Issues by type:")
    for issue_type, count in sorted(report.issues_by_type.items()):
        print(f"  • {issue_type:20} {count:,}")
    
    # Quality assessment
    if report.quality_score >= 0.8:
        print(f"\n✅ PASS: Quality score {report.quality_score:.3f} meets threshold (≥0.8)")
        exit_code = 0
    else:
        print(f"\n❌ FAIL: Quality score {report.quality_score:.3f} below threshold (≥0.8)")
        exit_code = 1
    
    # Write detailed report
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "input_file": str(args.input),
        "summary": {
            "total_found": report.total_found,
            "flagged": report.flagged,
            "clean": report.clean,
            "quality_score": report.quality_score
        },
        "issues_by_type": report.issues_by_type,
        "flagged_entries": report.flagged_entries
    }
    
    with open(args.output, 'w') as f:
        json.dump(report_data, f, indent=2)
    
    print(f"\n📄 Detailed report written to: {args.output}")
    
    return exit_code

if __name__ == "__main__":
    sys.exit(main())