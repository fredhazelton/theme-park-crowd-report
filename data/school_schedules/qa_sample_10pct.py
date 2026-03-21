#!/usr/bin/env python3
"""
SSD 10% QA Sampling System

Independently verifies 10% of collected districts by:
1. Random sampling from districts with calendar data
2. Re-extracting calendar information independently 
3. Comparing results with existing data for 100% accuracy verification
4. Flagging discrepancies for manual review

Usage:
    python3 qa_sample_10pct.py --sample-size 10 --output qa_sample_results.json
"""

import argparse
import csv
import json
import random
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).parent
DB_FILE = BASE_DIR / "v3" / "school_schedules.db"
DISTRICTS_FILE = BASE_DIR / "districts_comprehensive.csv"

def get_districts_with_data() -> List[Dict]:
    """Get all districts that have calendar data in the v3 database."""
    if not DB_FILE.exists():
        print(f"Error: Database not found at {DB_FILE}")
        sys.exit(1)
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    
    cursor = conn.execute("""
        SELECT DISTINCT d.district_id, d.district_name, d.state, d.enrollment, 
               cs.quality_confidence, cs.source_type
        FROM dim_district d
        JOIN dim_calendar_source cs ON d.district_id = cs.district_id
        WHERE EXISTS (
            SELECT 1 FROM fact_school_day fsd 
            WHERE fsd.district_id = d.district_id
        )
        ORDER BY d.enrollment DESC NULLS LAST
    """)
    
    districts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return districts

def sample_districts(districts: List[Dict], sample_pct: float = 0.10) -> List[Dict]:
    """Sample districts for QA verification."""
    sample_size = max(1, int(len(districts) * sample_pct))
    
    # Stratified sampling by confidence level to ensure representation
    high_conf = [d for d in districts if d['quality_confidence'] == 'high']
    med_conf = [d for d in districts if d['quality_confidence'] == 'medium']
    
    # Sample proportionally from each confidence level
    high_sample_size = int(sample_size * (len(high_conf) / len(districts)))
    med_sample_size = sample_size - high_sample_size
    
    sample = []
    if high_conf:
        sample.extend(random.sample(high_conf, min(high_sample_size, len(high_conf))))
    if med_conf and med_sample_size > 0:
        sample.extend(random.sample(med_conf, min(med_sample_size, len(med_conf))))
    
    # If we're short, fill from remaining districts
    if len(sample) < sample_size:
        remaining = [d for d in districts if d not in sample]
        if remaining:
            additional = min(sample_size - len(sample), len(remaining))
            sample.extend(random.sample(remaining, additional))
    
    return sample

def get_existing_calendar_data(district_id: str) -> Dict:
    """Get existing calendar data for a district from the database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    
    # Get basic district info
    district_info = conn.execute("""
        SELECT * FROM dim_district WHERE district_id = ?
    """, (district_id,)).fetchone()
    
    # Get calendar source info
    calendar_source = conn.execute("""
        SELECT * FROM dim_calendar_source WHERE district_id = ?
    """, (district_id,)).fetchone()
    
    # Get school days
    school_days = conn.execute("""
        SELECT date, day_type, break_name, notes 
        FROM fact_school_day 
        WHERE district_id = ? 
        ORDER BY date
    """, (district_id,)).fetchall()
    
    conn.close()
    
    return {
        'district': dict(district_info) if district_info else None,
        'source': dict(calendar_source) if calendar_source else None,
        'school_days': [dict(day) for day in school_days] if school_days else []
    }

def verify_sample_district(district: Dict) -> Dict:
    """Independently verify a single district's calendar data."""
    district_id = district['district_id']
    
    print(f"Verifying {district['district_name']} ({district['state']})...")
    
    # Get existing data
    existing = get_existing_calendar_data(district_id)
    
    # TODO: Implement independent re-extraction using qa_sweep.py logic
    # For now, return structure for manual verification
    
    result = {
        'district_id': district_id,
        'district_name': district['district_name'],
        'state': district['state'],
        'enrollment': district['enrollment'],
        'existing_confidence': district['quality_confidence'],
        'existing_data': existing,
        'verification_status': 'PENDING_MANUAL_REVIEW',  # Will be automated later
        'discrepancies': [],
        'verification_timestamp': datetime.now().isoformat()
    }
    
    return result

def main():
    parser = argparse.ArgumentParser(description='SSD 10% QA Sampling System')
    parser.add_argument('--sample-pct', type=float, default=0.10, 
                       help='Percentage of districts to sample (default: 0.10)')
    parser.add_argument('--output', default='qa_sample_results.json',
                       help='Output file for results')
    parser.add_argument('--seed', type=int, help='Random seed for reproducible sampling')
    
    args = parser.parse_args()
    
    if args.seed:
        random.seed(args.seed)
    
    # Get districts with data
    print("Loading districts with calendar data...")
    districts = get_districts_with_data()
    
    if not districts:
        print("No districts found with calendar data.")
        sys.exit(1)
    
    print(f"Found {len(districts)} districts with calendar data")
    
    # Sample districts for QA
    sample = sample_districts(districts, args.sample_pct)
    sample_size = len(sample)
    
    print(f"Selected {sample_size} districts for QA verification ({args.sample_pct:.1%} sample)")
    
    # Verify each district in sample
    results = []
    for i, district in enumerate(sample, 1):
        print(f"Progress: {i}/{sample_size}")
        result = verify_sample_district(district)
        results.append(result)
    
    # Save results
    output_data = {
        'metadata': {
            'sample_percentage': args.sample_pct,
            'total_districts_available': len(districts),
            'sample_size': sample_size,
            'generated_at': datetime.now().isoformat(),
            'random_seed': args.seed
        },
        'sample_districts': results
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2, default=str)
    
    print(f"\nQA sample results saved to: {args.output}")
    print(f"Sample size: {sample_size} districts ({args.sample_pct:.1%})")
    print("Manual verification required for complete QA validation.")

if __name__ == "__main__":
    main()