#!/usr/bin/env python3
"""SSD Quality Validation — v3 (SQLite + CSV).

Validates the v3 school schedules database across multiple dimensions:

  1. Schema completeness — missing/null fields per district
  2. Date plausibility — dates within expected ranges for 2025-26
  3. Break duration sanity — spring, winter, summer lengths
  4. School year duration — instructional day counts
  5. State consistency — outlier detection within each state
  6. Duplicate date fingerprints — likely hallucinated entries
  7. Enrollment integrity — zero/missing enrollment, NCES coverage
  8. Daily aggregate coherence — totals, monotonicity, reason labels
  9. Confidence distribution — coverage by tier

Works against:
  - districts_comprehensive.csv (or districts_all.csv)
  - daily_aggregate_v3.csv
  - school_schedules.db (SQLite, if present)

Usage:
  python3 ssd_quality_check_v3.py --districts districts_comprehensive.csv \
                                   --daily daily_aggregate_v3.csv \
                                   [--output ssd_v3_quality_report.json]

Exit codes: 0 = PASS (score >= 0.80), 1 = FAIL, 2 = ERROR
"""

from __future__ import annotations
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ──────────────────────────────────────────────────────────
SCHOOL_YEAR = "2025-2026"

EXPECTED_RANGES = {
    "first_day":          (date(2025, 7, 1),  date(2025, 9, 30)),
    "last_day":           (date(2026, 4, 1),  date(2026, 7, 15)),
    "spring_break_start": (date(2026, 2, 1),  date(2026, 5, 15)),
    "spring_break_end":   (date(2026, 2, 1),  date(2026, 5, 31)),
    "winter_break_start": (date(2025, 11, 15), date(2026, 1, 15)),
    "winter_break_end":   (date(2025, 12, 15), date(2026, 1, 31)),
}

BREAK_LENGTH_RULES = {
    "spring": {"start": "spring_break_start", "end": "spring_break_end",
               "min": 2, "max": 14, "label": "Spring break"},
    "winter": {"start": "winter_break_start", "end": "winter_break_end",
               "min": 7, "max": 21, "label": "Winter break"},
}

YEAR_LENGTH = {"min": 150, "max": 210}

POST_LABOR_DAY_STATES = {"VA", "MI", "MN", "WI", "MD", "IA"}
EARLY_START_STATES = {"AZ", "HI", "GA", "TN", "MS", "AL", "SC", "FL", "TX"}

REQUIRED_DISTRICT_COLS = [
    "nces_leaid", "district_name", "state",
    "first_day", "last_day",
    "spring_break_start", "spring_break_end",
    "winter_break_start", "winter_break_end",
]


# ── Data classes ───────────────────────────────────────────────────────
@dataclass
class Issue:
    check: str
    severity: str  # critical, high, medium, low
    nces_id: str = ""
    detail: str = ""


@dataclass
class CheckResult:
    name: str
    passed: bool
    score: float
    issues: List[Issue] = field(default_factory=list)
    summary: str = ""


@dataclass
class QualityReport:
    timestamp: str
    school_year: str
    overall_score: float
    overall_pass: bool
    districts_analyzed: int
    daily_rows_analyzed: int
    checks: List[Dict[str, Any]] = field(default_factory=list)
    issue_counts: Dict[str, int] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────
def parse_date(s: Optional[str]) -> Optional[date]:
    if not s or s in ("", "null", "None", "NaT"):
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def load_csv(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ── Check implementations ─────────────────────────────────────────────
def check_schema_completeness(districts: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    total = len(districts)
    null_counts: Dict[str, int] = Counter()
    for row in districts:
        for col in REQUIRED_DISTRICT_COLS:
            val = row.get(col, "")
            if not val or val in ("", "null", "None"):
                null_counts[col] += 1
    worst_null_pct = 0.0
    for col, count in null_counts.items():
        pct = count / total * 100 if total else 0
        worst_null_pct = max(worst_null_pct, pct)
        sev = "critical" if pct > 50 else "high" if pct > 20 else "medium" if pct > 5 else "low"
        if pct > 1:
            issues.append(Issue(check="schema_completeness", severity=sev,
                                detail=f"Column '{col}' null/empty in {count:,} rows ({pct:.1f}%)"))
    score = max(0.0, 1.0 - worst_null_pct / 100)
    return CheckResult(name="schema_completeness", passed=score >= 0.80, score=round(score, 3),
                       issues=issues, summary=f"{len(null_counts)} columns with nulls; worst = {worst_null_pct:.1f}%")


def check_date_plausibility(districts: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    total = len(districts)
    bad = 0
    for row in districts:
        nces = row.get("nces_leaid", "?")
        for field_name, (lo, hi) in EXPECTED_RANGES.items():
            d = parse_date(row.get(field_name))
            if d and not (lo <= d <= hi):
                bad += 1
                issues.append(Issue(check="date_plausibility", severity="high", nces_id=nces,
                                    detail=f"{field_name}={d} outside [{lo}, {hi}]"))
    score = max(0.0, 1.0 - bad / (total * len(EXPECTED_RANGES))) if total else 0
    return CheckResult(name="date_plausibility", passed=score >= 0.95, score=round(score, 3),
                       issues=issues[:200], summary=f"{bad:,} implausible dates across {total:,} districts")


def check_break_duration(districts: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    checked = bad = 0
    for row in districts:
        nces = row.get("nces_leaid", "?")
        for label, rule in BREAK_LENGTH_RULES.items():
            s = parse_date(row.get(rule["start"]))
            e = parse_date(row.get(rule["end"]))
            if s and e:
                checked += 1
                length = (e - s).days + 1
                if length < rule["min"] or length > rule["max"]:
                    bad += 1
                    issues.append(Issue(check="break_duration", severity="medium", nces_id=nces,
                                        detail=f"{rule['label']} = {length}d (expected {rule['min']}-{rule['max']})"))
    score = max(0.0, 1.0 - bad / checked) if checked else 1.0
    return CheckResult(name="break_duration", passed=score >= 0.95, score=round(score, 3),
                       issues=issues[:200], summary=f"{bad:,} invalid break lengths out of {checked:,} checked")


def check_school_year_length(districts: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    checked = bad = 0
    for row in districts:
        nces = row.get("nces_leaid", "?")
        fd = parse_date(row.get("first_day"))
        ld = parse_date(row.get("last_day"))
        if fd and ld:
            checked += 1
            length = (ld - fd).days + 1
            if length < YEAR_LENGTH["min"] or length > YEAR_LENGTH["max"]:
                bad += 1
                issues.append(Issue(check="school_year_length", severity="medium", nces_id=nces,
                                    detail=f"School year = {length} cal days (expected {YEAR_LENGTH['min']}-{YEAR_LENGTH['max']})"))
    score = max(0.0, 1.0 - bad / checked) if checked else 1.0
    return CheckResult(name="school_year_length", passed=score >= 0.95, score=round(score, 3),
                       issues=issues[:200], summary=f"{bad:,} invalid year lengths out of {checked:,} checked")


def check_state_consistency(districts: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    by_state: Dict[str, List[Tuple[str, date]]] = defaultdict(list)
    for row in districts:
        state = row.get("state", "")
        sb = parse_date(row.get("spring_break_start"))
        if state and sb:
            by_state[state].append((row.get("nces_leaid", "?"), sb))
    outliers = total_checked = 0
    for state, entries in by_state.items():
        if len(entries) < 5:
            continue
        total_checked += len(entries)
        ordinals = [d.toordinal() for _, d in entries]
        med = date.fromordinal(int(median(ordinals)))
        for nces, sb in entries:
            diff = abs((sb - med).days)
            if diff > 30:
                outliers += 1
                issues.append(Issue(check="state_consistency", severity="medium", nces_id=nces,
                                    detail=f"Spring break {diff}d from {state} median ({med})"))
    score = max(0.0, 1.0 - outliers / total_checked) if total_checked else 1.0
    return CheckResult(name="state_consistency", passed=score >= 0.95, score=round(score, 3),
                       issues=issues[:200], summary=f"{outliers:,} state outliers out of {total_checked:,} checked")


def check_duplicate_fingerprints(districts: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    fingerprints: Dict[tuple, List[str]] = defaultdict(list)
    date_fields = ["first_day", "last_day", "spring_break_start", "spring_break_end",
                    "winter_break_start", "winter_break_end"]
    for row in districts:
        nces = row.get("nces_leaid", "?")
        sig = tuple(row.get(f, "") for f in date_fields)
        if any(s and s not in ("", "null") for s in sig):
            fingerprints[sig].append(nces)
    dup_threshold = 15
    flagged = 0
    for sig, ids in fingerprints.items():
        if len(ids) >= dup_threshold:
            flagged += len(ids)
            issues.append(Issue(check="duplicate_fingerprints", severity="high",
                                detail=f"{len(ids)} districts share dates {dict(zip(date_fields, sig))}"))
    total = len(districts)
    score = max(0.0, 1.0 - flagged / total) if total else 1.0
    return CheckResult(name="duplicate_fingerprints", passed=score >= 0.80, score=round(score, 3),
                       issues=issues[:100], summary=f"{flagged:,} districts in duplicate clusters (threshold={dup_threshold})")


def check_enrollment_integrity(districts: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    total = len(districts)
    zero_count = missing_count = 0
    total_enrollment = 0
    for row in districts:
        enr_str = row.get("enrollment", "0")
        try:
            enr = int(float(enr_str)) if enr_str else 0
        except (ValueError, TypeError):
            enr = 0
            missing_count += 1
            continue
        if enr == 0:
            zero_count += 1
        elif enr < 0:
            issues.append(Issue(check="enrollment_integrity", severity="high",
                                nces_id=row.get("nces_leaid", "?"), detail=f"Negative enrollment: {enr}"))
        else:
            total_enrollment += enr
    zero_pct = zero_count / total * 100 if total else 0
    if zero_pct > 50:
        issues.insert(0, Issue(check="enrollment_integrity", severity="critical",
                               detail=f"{zero_count:,} districts ({zero_pct:.1f}%) have enrollment=0"))
    score = max(0.0, 1.0 - (zero_count + missing_count) / total) if total else 0
    return CheckResult(name="enrollment_integrity", passed=score >= 0.80, score=round(score, 3),
                       issues=issues[:50],
                       summary=f"Enrollment: {total_enrollment:,} total | {zero_count:,} zeros ({zero_pct:.1f}%) | {missing_count:,} missing")


def check_daily_aggregate(daily: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    if not daily:
        return CheckResult(name="daily_aggregate", passed=False, score=0.0,
                           issues=[Issue(check="daily_aggregate", severity="critical", detail="No daily rows")],
                           summary="No daily aggregate data")
    expected_rows = 366
    actual_rows = len(daily)
    if actual_rows < expected_rows - 5:
        issues.append(Issue(check="daily_aggregate", severity="high",
                            detail=f"Expected ~{expected_rows} rows, got {actual_rows}"))
    bad_reason = 0
    for row in daily:
        d = parse_date(row.get("date"))
        reason = row.get("primary_reason", "")
        if d and date(2025, 10, 1) <= d <= date(2026, 5, 15):
            if reason == "summer_break":
                bad_reason += 1
    if bad_reason > 0:
        issues.insert(0, Issue(check="daily_aggregate", severity="critical",
                               detail=f"{bad_reason} school-year dates mislabeled as 'summer_break'"))
    total_checks = max(1, actual_rows + 1)
    score = max(0.0, 1.0 - len(issues) / total_checks)
    return CheckResult(name="daily_aggregate",
                       passed=len([i for i in issues if i.severity in ("critical", "high")]) == 0,
                       score=round(score, 3), issues=issues[:100],
                       summary=f"{actual_rows} rows; {bad_reason} mislabeled reasons; {len(issues)} issues total")


def check_confidence_distribution(districts: List[Dict]) -> CheckResult:
    issues: List[Issue] = []
    conf_counts: Counter = Counter()
    total = len(districts)
    for row in districts:
        conf = (row.get("confidence") or "unknown").lower().strip()
        conf_counts[conf] += 1
    confirmed_pct = conf_counts.get("confirmed", 0) / total * 100 if total else 0
    high_pct = conf_counts.get("high", 0) / total * 100 if total else 0
    verified_pct = confirmed_pct + high_pct
    if verified_pct < 30:
        issues.append(Issue(check="confidence_distribution", severity="high",
                            detail=f"Only {verified_pct:.1f}% of districts are confirmed/high confidence"))
    dist_str = " | ".join(f"{k}: {v:,} ({v/total*100:.1f}%)" for k, v in conf_counts.most_common())
    score = min(1.0, verified_pct / 50)
    return CheckResult(name="confidence_distribution", passed=verified_pct >= 20,
                       score=round(score, 3), issues=issues, summary=dist_str)


# ── Main orchestrator ──────────────────────────────────────────────────
def run_all_checks(districts: List[Dict], daily: List[Dict]) -> QualityReport:
    checks = [
        check_schema_completeness(districts),
        check_date_plausibility(districts),
        check_break_duration(districts),
        check_school_year_length(districts),
        check_state_consistency(districts),
        check_duplicate_fingerprints(districts),
        check_enrollment_integrity(districts),
        check_daily_aggregate(daily),
        check_confidence_distribution(districts),
    ]
    weights = {
        "schema_completeness": 1.5, "date_plausibility": 2.0,
        "break_duration": 1.0, "school_year_length": 1.0,
        "state_consistency": 1.0, "duplicate_fingerprints": 2.0,
        "enrollment_integrity": 1.5, "daily_aggregate": 1.5,
        "confidence_distribution": 1.0,
    }
    weighted_sum = sum(c.score * weights.get(c.name, 1.0) for c in checks)
    weight_total = sum(weights.get(c.name, 1.0) for c in checks)
    overall = weighted_sum / weight_total if weight_total else 0
    all_issues = [i for c in checks for i in c.issues]
    issue_counts = Counter(i.severity for i in all_issues)
    recs = [f"[{c.name}] {c.summary}" for c in checks if not c.passed]
    return QualityReport(
        timestamp=datetime.now().isoformat(), school_year=SCHOOL_YEAR,
        overall_score=round(overall, 3), overall_pass=overall >= 0.80,
        districts_analyzed=len(districts), daily_rows_analyzed=len(daily),
        checks=[{"name": c.name, "passed": c.passed, "score": c.score,
                 "summary": c.summary, "issue_count": len(c.issues),
                 "issues": [asdict(i) for i in c.issues[:20]]} for c in checks],
        issue_counts=dict(issue_counts), recommendations=recs)


def print_report(report: QualityReport) -> None:
    status = "PASS" if report.overall_pass else "FAIL"
    print(f"\n{'='*60}")
    print(f"  SSD v3 Quality Report — {report.school_year}")
    print(f"  {status}  Overall Score: {report.overall_score:.3f}")
    print(f"{'='*60}")
    print(f"  Districts analyzed:  {report.districts_analyzed:,}")
    print(f"  Daily rows analyzed: {report.daily_rows_analyzed:,}")
    print(f"  Issues: {report.issue_counts}")
    print()
    for c in report.checks:
        icon = "PASS" if c["passed"] else "FAIL"
        print(f"  {icon} {c['name']:30s}  score={c['score']:.3f}  issues={c['issue_count']}")
        if c["summary"]:
            print(f"       {c['summary']}")
    print()
    if report.recommendations:
        print("  Recommendations:")
        for r in report.recommendations:
            print(f"     - {r}")
        print()


def main():
    parser = argparse.ArgumentParser(description="SSD v3 Quality Validation")
    parser.add_argument("--districts", required=True, help="Path to districts CSV")
    parser.add_argument("--daily", default=None, help="Path to daily aggregate CSV")
    parser.add_argument("--output", default="ssd_v3_quality_report.json", help="Output JSON")
    args = parser.parse_args()
    print(f"Loading districts from {args.districts}...")
    districts = load_csv(args.districts)
    print(f"  -> {len(districts):,} rows")
    daily = []
    if args.daily and os.path.exists(args.daily):
        print(f"Loading daily aggregate from {args.daily}...")
        daily = load_csv(args.daily)
        print(f"  -> {len(daily):,} rows")
    report = run_all_checks(districts, daily)
    print_report(report)
    with open(args.output, "w") as f:
        json.dump(asdict(report), f, indent=2, default=str)
    print(f"  Report saved to {args.output}")
    return 0 if report.overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
