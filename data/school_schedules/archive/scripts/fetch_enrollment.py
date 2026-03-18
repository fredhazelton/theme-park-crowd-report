#!/usr/bin/env python3
"""Fetch district enrollment from NCES ArcGIS service, aggregating school-level data."""

import urllib.request, json, time, csv, sys

BASE_URL = ("https://nces.ed.gov/opengis/rest/services/K12_School_Locations/"
            "EDGE_ADMINDATA_PUBLICSCH_2223/MapServer/0/query")

STATES = ['AL','AK','AZ','AR','CA','CO','CT','DE','DC','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME',
          'MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI',
          'SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY']

def query_state(st, offset=0, limit=2000):
    params = (f"where=STABR%3D%27{st}%27&"
              f"outFields=LEAID,LEA_NAME,MEMBER,STABR&"
              f"returnGeometry=false&"
              f"resultRecordCount={limit}&"
              f"resultOffset={offset}&"
              f"f=json")
    url = f"{BASE_URL}?{params}"
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())

all_districts = {}
total_schools = 0

for st in STATES:
    offset = 0
    state_schools = 0
    while True:
        try:
            data = query_state(st, offset)
            features = data.get('features', [])
            if not features:
                break
            for f in features:
                a = f['attributes']
                lid = a['LEAID']
                member = a.get('MEMBER') or 0
                if member < 0: member = 0
                if lid not in all_districts:
                    all_districts[lid] = {'name': a['LEA_NAME'], 'state': st, 'enrollment': 0}
                all_districts[lid]['enrollment'] += member
            state_schools += len(features)
            exceeded = data.get('exceededTransferLimit', False)
            if exceeded:
                offset += len(features)
                time.sleep(0.5)
            else:
                break
        except Exception as e:
            print(f"ERROR {st} offset={offset}: {e}", file=sys.stderr)
            time.sleep(2)
            break
    
    total_schools += state_schools
    print(f"  {st}: {state_schools} schools, {sum(1 for d in all_districts.values() if d['state']==st)} districts")
    time.sleep(0.3)

print(f"\nTotal: {len(all_districts)} districts, {total_schools} schools")
total_enrollment = sum(d['enrollment'] for d in all_districts.values())
print(f"Total enrollment: {total_enrollment:,}")

# Save
with open('enrollment_by_district.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['leaid', 'district_name', 'state', 'enrollment_2223'])
    for lid, d in sorted(all_districts.items(), key=lambda x: -x[1]['enrollment']):
        writer.writerow([lid, d['name'], d['state'], d['enrollment']])

print("\nSaved to enrollment_by_district.csv")

# Top 20
print("\nTop 20:")
sorted_d = sorted(all_districts.items(), key=lambda x: -x[1]['enrollment'])
for lid, d in sorted_d[:20]:
    print(f"  {lid} {d['name']} ({d['state']}): {d['enrollment']:,}")
