#!/usr/bin/env python3
"""
Fetch NCES district enrollment data.
Uses the NCES EDGE API / public data files.
"""

import csv
import json
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_CSV = BASE_DIR / 'NCES_districts.csv'

def fetch_nces_saipe():
    """
    Fetch district data from NCES using the public SAIPE/CCD API.
    The census.gov API has SAIPE school district data with enrollment.
    """
    # Use Census API to get school district estimates with child population
    # This is the School District Child Poverty Estimates which includes enrollment
    # https://www.census.gov/programs-surveys/saipe/data/api.html
    
    # Alternative: Use the NCES Public Data API
    # https://data.ed.gov/dataset/ccd-lea-directory  
    url = "https://educationdata.urban.org/api/v1/school-districts/ccd/directory/2022/?limit=100"
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
        return data
    except Exception as e:
        print(f"Error: {e}")
        return None


def fetch_from_census():
    """Use Census API for school district data."""
    # Census SAIPE School Districts - has enrollment and poverty data
    # API: https://api.census.gov/data/2022/acs/acs5
    # But we need a different approach for enrollment
    
    # Let's use the NCES CCD LEA directory data
    # Available as flat files, need to find the right URL
    pass


def build_nces_from_existing():
    """
    Build NCES data from what we already have + public enrollment data.
    Many large districts have well-known enrollment figures.
    We can supplement with NCES data later.
    """
    # For now, use the top 100 data we already have and extend with known figures
    # The top100 CSV has students_2019 which is from NCES
    districts = []
    
    top100_path = BASE_DIR / 'districts_top100.csv'
    if top100_path.exists():
        with open(top100_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                districts.append({
                    'district_name': row['district_name'],
                    'state': row['state'],
                    'enrollment': int(row['students_2019']) if row.get('students_2019') else 0,
                    'rank': int(row['rank']),
                    'source': 'top100_csv'
                })
    
    return districts


def main():
    print("Building NCES district reference data...")
    
    # Start with what we have
    districts = build_nces_from_existing()
    print(f"Loaded {len(districts)} districts from top100 CSV")
    
    total_enrollment = sum(d['enrollment'] for d in districts)
    print(f"Total enrollment (top 100): {total_enrollment:,}")
    
    # Total US public school enrollment is ~49.5 million
    US_TOTAL = 49_500_000
    pct = total_enrollment / US_TOTAL * 100
    print(f"Coverage: {pct:.1f}% of US students")
    
    # Save what we have
    fieldnames = ['rank', 'district_name', 'state', 'enrollment', 'source']
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(districts)
    
    print(f"Saved to: {OUTPUT_CSV}")
    print(f"\nNote: Full NCES data requires downloading from https://nces.ed.gov/ccd/elsi/")
    print("The Table Generator allows exporting all ~13,000 districts with enrollment.")
    print("This requires browser interaction (Angular app).")


if __name__ == "__main__":
    main()
