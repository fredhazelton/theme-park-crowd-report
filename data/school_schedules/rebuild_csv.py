#!/usr/bin/env python3
"""Rebuild the CSV from original district data + scraped results."""

import csv
import json
from datetime import datetime
from pathlib import Path

CSV_PATH = Path(__file__).parent / "districts_top100.csv"
RESULTS_PATH = Path(__file__).parent / "fetch_results.json"

# Original district data from the initial CSV
DISTRICTS = [
    (1, "New York City", "New York", 956634),
    (2, "Los Angeles Unified", "California", 483234),
    (3, "City of Chicago (SD 299)", "Illinois", 347484),
    (4, "Miami-Dade County", "Florida", 347307),
    (5, "Clark County", "Nevada", 328991),
    (6, "Broward County", "Florida", 269172),
    (7, "Hillsborough County", "Florida", 223305),
    (8, "Houston ISD", "Texas", 210061),
    (9, "Orange County", "Florida", 208875),
    (10, "Palm Beach", "Florida", 194675),
    (11, "Fairfax County", "Virginia", 188887),
    (12, "Hawaii Department of Education", "Hawaii", 181088),
    (13, "Gwinnett County", "Georgia", 180589),
    (14, "Montgomery County", "Maryland", 165267),
    (15, "Wake County", "North Carolina", 163404),
    (16, "Dallas ISD", "Texas", 153861),
    (17, "Charlotte-Mecklenburg", "North Carolina", 149845),
    (18, "Prince George's County", "Maryland", 135952),
    (19, "Philadelphia City", "Pennsylvania", 130617),
    (20, "Duval County", "Florida", 130279),
    (21, "Cypress-Fairbanks ISD", "Texas", 117446),
    (22, "Baltimore County", "Maryland", 115038),
    (23, "Shelby County", "Tennessee", 113198),
    (24, "Cobb County", "Georgia", 112097),
    (25, "Northside ISD", "Texas", 107817),
    (26, "Polk County", "Florida", 102952),
    (27, "San Diego Unified", "California", 102270),
    (28, "Jefferson County", "Kentucky", 100348),
    (29, "Pinellas County", "Florida", 99772),
    (30, "DeKalb County", "Georgia", 98800),
    (31, "Lee County", "Florida", 95613),
    (32, "Fulton County", "Georgia", 93897),
    (33, "Prince William County", "Virginia", 92237),
    (34, "Denver", "Colorado", 92143),
    (35, "Albuquerque", "New Mexico", 88312),
    (36, "Davidson County", "Tennessee", 85588),
    (37, "Anne Arundel County", "Maryland", 84984),
    (38, "Jefferson County No R1", "Colorado", 84078),
    (39, "Loudoun County", "Virginia", 83606),
    (40, "Alpine", "Utah", 83540),
    (41, "Katy ISD", "Texas", 83423),
    (42, "Fort Worth ISD", "Texas", 82891),
    (43, "Austin ISD", "Texas", 80911),
    (44, "Baltimore City", "Maryland", 79187),
    (45, "Fort Bend ISD", "Texas", 77756),
    (46, "Greenville County", "South Carolina", 77302),
    (47, "Pasco County", "Florida", 76661),
    (48, "Davis", "Utah", 74773),
    (49, "Milwaukee", "Wisconsin", 74683),
    (50, "Brevard County", "Florida", 73962),
    (51, "Guilford County", "North Carolina", 72682),
    (52, "Long Beach Unified", "California", 71712),
    (53, "Fresno Unified", "California", 71265),
    (54, "Osceola County", "Florida", 69925),
    (55, "Virginia Beach City", "Virginia", 68706),
    (56, "Seminole County", "Florida", 68096),
    (57, "Douglas County No RE1", "Colorado", 67305),
    (58, "Washoe County", "Nevada", 67301),
    (59, "Aldine ISD", "Texas", 67259),
    (60, "Granite", "Utah", 66276),
    (61, "Conroe ISD", "Texas", 64799),
    (62, "North East ISD", "Texas", 64539),
    (63, "Elk Grove Unified", "California", 63660),
    (64, "Volusia County", "Florida", 63009),
    (65, "Frisco ISD", "Texas", 62705),
    (66, "Mesa Unified", "Arizona", 62703),
    (67, "Chesterfield County", "Virginia", 62614),
    (68, "Knox County", "Tennessee", 61545),
    (69, "Arlington ISD", "Texas", 59532),
    (70, "Howard County", "Maryland", 58868),
    (71, "Jordan", "Utah", 57771),
    (72, "Cherry Creek No 5", "Colorado", 56228),
    (73, "Seattle", "Washington", 55986),
    (74, "Garland ISD", "Texas", 55701),
    (75, "El Paso ISD", "Texas", 55253),
    (76, "Winston-Salem/Forsyth County", "North Carolina", 54566),
    (77, "Clayton County", "Georgia", 54424),
    (78, "Klein ISD", "Texas", 54096),
    (79, "Mobile County", "Alabama", 53941),
    (80, "Omaha", "Nebraska", 53483),
    (81, "Pasadena ISD", "Texas", 52878),
    (82, "San Francisco Unified", "California", 52811),
    (83, "Plano ISD", "Texas", 52629),
    (84, "Corona-Norco Unified", "California", 52557),
    (85, "Atlanta", "Georgia", 52416),
    (86, "Lewisville ISD", "Texas", 52189),
    (87, "Henrico County", "Virginia", 51786),
    (88, "District of Columbia", "District of Columbia", 50971),
    (89, "Round Rock ISD", "Texas", 50953),
    (90, "Cumberland County", "North Carolina", 50750),
    (91, "Detroit", "Michigan", 50644),
    (92, "Forsyth County", "Georgia", 50544),
    (93, "Boston", "Massachusetts", 50480),
    (94, "Charleston 01", "South Carolina", 50299),
    (95, "Manatee County", "Florida", 50088),
    (96, "Jefferson Parish", "Louisiana", 49862),
    (97, "Wichita", "Kansas", 49323),
    (98, "Columbus City", "Ohio", 48759),
    (99, "San Bernardino City Unified", "California", 48755),
    (100, "Portland SD1J", "Oregon", 48601),
]

FIELDNAMES = [
    'rank', 'district_name', 'state', 'students_2019', 'calendar_url',
    'spring_break_start', 'spring_break_end', 'winter_break_start',
    'winter_break_end', 'summer_start', 'summer_end', 'last_updated'
]

def main():
    # Load scraped results
    with open(RESULTS_PATH) as f:
        results = json.load(f)
    
    rows = []
    for rank, name, state, students in DISTRICTS:
        row = {
            'rank': rank,
            'district_name': name,
            'state': state,
            'students_2019': students,
            'calendar_url': '',
            'spring_break_start': '',
            'spring_break_end': '',
            'winter_break_start': '',
            'winter_break_end': '',
            'summer_start': '',
            'summer_end': '',
            'last_updated': '',
        }
        
        if name in results and results[name]['status'] == 'success':
            data = results[name]['data']
            row['calendar_url'] = results[name].get('url', '')
            row['spring_break_start'] = data.get('spring_break_start', '')
            row['spring_break_end'] = data.get('spring_break_end', '')
            row['winter_break_start'] = data.get('winter_break_start', '')
            row['winter_break_end'] = data.get('winter_break_end', '')
            row['summer_start'] = data.get('summer_start', '')
            row['summer_end'] = data.get('summer_end', '')
            row['last_updated'] = datetime.now().strftime('%Y-%m-%d')
        
        rows.append(row)
    
    with open(CSV_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    
    # Count stats
    filled = sum(1 for r in rows if r['spring_break_start'])
    print(f"CSV rebuilt: {len(rows)} districts, {filled} with calendar data")
    print(f"Written to: {CSV_PATH}")

if __name__ == "__main__":
    main()
