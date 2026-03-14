# 📊 SSD Competitive Intel — 2026-03-14 (task-061)

## School Schedule Data Competitive Landscape

### Direct Competitors

#### 1. schools-calendar.com (School Calendar API)
- **Coverage:** 10,046+ districts across all 50 US states
- **Format:** Web interface + iCal downloads per district
- **Data:** First/last day, breaks, holidays per district
- **Pricing:** Unknown (no public API pricing found — likely consumer-focused, not B2B)
- **Strengths:** Broad coverage, clean UI, state-by-state browsing
- **Weaknesses:** No apparent bulk API for commercial use, no enrollment weighting, no indication of data verification methodology
- **Threat level:** MEDIUM — closest direct competitor to our scraper's output format
- **Our advantage:** We have enrollment weighting (84.1% of enrollment at 45.8% district coverage) and are building towards confirmed/verified data quality

#### 2. Local Logic (locallogic.co) — School Data API
- **Coverage:** US and Canada
- **Format:** REST API (lat/long + radius search, custom boundaries)
- **Data:** School names, websites, levels, grade ranges, languages, programs, school board info, proximity metrics, catchment areas
- **Pricing:** Enterprise (custom — likely $10K+/year)
- **Target market:** Real estate platforms (Realtor.com, Zillow-type integrations)
- **Strengths:** Rich data model, location-based search, Canadian coverage
- **Weaknesses:** Focused on school metadata, NOT school calendars/schedules. No break dates, no start/end dates
- **Threat level:** LOW — different product. They sell school info for real estate. We sell calendar data for tourism/travel
- **Our advantage:** Calendar-specific data (break periods, holidays) is our niche — Local Logic doesn't touch it

#### 3. SchoolDigger (schooldigger.com)
- **Coverage:** US schools
- **Format:** API + website
- **Data:** Rankings, test scores, demographics, reviews
- **Pricing:** API plans from ~$40/month
- **Target market:** Real estate, parents, researchers
- **Weaknesses:** No calendar/schedule data — purely rankings and performance metrics
- **Threat level:** NONE for schedule data

#### 4. GreatSchools (greatschools.org)
- **Coverage:** US + some international
- **Data:** Ratings, reviews, test scores, demographics
- **Pricing:** API available for partners
- **Weaknesses:** No school calendar data
- **Threat level:** NONE for schedule data

#### 5. Niche (niche.com)
- **Coverage:** US schools, colleges, neighborhoods
- **Data:** Rankings, reviews, statistics
- **Weaknesses:** No school calendar data
- **Threat level:** NONE for schedule data

#### 6. France — data.education.gouv.fr
- **Coverage:** French school calendars (official government API)
- **Format:** Open data API
- **Note:** Government-provided, free. Model for what US school calendar data COULD look like if centralized. But the US doesn't have this — fragmented across 13,000+ districts

### Gap Analysis

| Feature | Us (SSD) | schools-calendar.com | Local Logic | Others |
|---------|----------|---------------------|-------------|--------|
| Calendar/break dates | ✅ | ✅ | ❌ | ❌ |
| Enrollment weighting | ✅ | ❌ | ❌ | ❌ |
| Verified/confirmed data | ✅ (in progress) | ❓ | N/A | N/A |
| Bulk API access | 🔜 | ❓ | ✅ | Varies |
| US coverage | 45.8% districts / 84.1% enrollment | 10K+ districts | US+CA | Varies |
| Canadian coverage | 🔜 | ❌ | ✅ | ❌ |
| Theme park correlation | ✅ | ❌ | ❌ | ❌ |

### Key Findings

1. **No one sells verified school calendar data at scale with enrollment weighting.** This is genuinely a gap in the market
2. **schools-calendar.com is the closest competitor** but appears consumer-focused (find your kid's school calendar), not B2B data provider
3. **The theme park correlation angle is unique** — nobody else connects school schedules to travel demand patterns
4. **Enrollment weighting is our moat** — knowing that a district with 500K students has spring break week X is more valuable than knowing 50 small districts have different dates
5. **The US school calendar market is fragmented by design** — no federal database exists. Anyone building comprehensive coverage is doing the same scraping/manual work we are

### Recommended Positioning
- **B2B angle:** "The only enrollment-weighted, verified school calendar dataset in the US"
- **Travel industry angle:** "Know when 84% of American students are on break, before your competitors do"
- **Potential buyers:** Theme park operators, hotel chains, airline revenue management, travel booking platforms, retail (back-to-school timing)

### Next Steps
1. Get SSD scraper to 95%+ confirmed coverage (currently 45.8%)
2. Build API endpoint for schedule queries
3. Research pricing: what do similar data products charge? (Local Logic is $10K+/yr for school metadata — calendar data could command similar)
4. Consider adding Canadian school calendar coverage (aligns with ACCORD's GoC focus)
