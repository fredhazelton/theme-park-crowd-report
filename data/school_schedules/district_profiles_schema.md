# District Intelligence Profiles — Schema Design

## Philosophy
Every district in the country gets a persistent record. When we research a district,
we record EVERYTHING — what worked, what didn't, what the website looks like, where
the calendar lives. This memory compounds over time. By the 3rd collection cycle,
we should know exactly where to look for 90%+ of districts.

## Profile Schema (per district)

```json
{
  "nces_id": "0100189",
  "name": "Satsuma City",
  "state": "AL",
  "enrollment": 1502,
  "county": "Mobile",
  
  "website": {
    "primary_url": "https://www.satsumaschools.com",
    "platform": "finalsite",
    "calendar_page": "https://www.satsumaschools.com/gatorlife/student-calendar",
    "calendar_page_type": "static_html | js_rendered | iframe | redirect",
    "has_pdf_calendar": true,
    "pdf_url_pattern": "resources.finalsite.net/images/v{version}/satsumaschoolscom/{hash}/{filename}.pdf",
    "notes": "Calendar page links to PDF hosted on Finalsite CDN"
  },
  
  "sources": [
    {
      "url": "https://resources.finalsite.net/images/v1741986663/satsumaschoolscom/qhaiq8ubf94...",
      "type": "pdf",
      "hosting": "finalsite_cdn",
      "discovered_via": "brave_search",
      "search_query": "\"Satsuma City\" Alabama 2025-2026 school calendar pdf",
      "school_year": "2025-2026",
      "quality": "high",
      "fields_extracted": ["first_day", "last_day", "winter_break_start", "winter_break_end", "spring_break_start", "spring_break_end"],
      "extraction_method": "pdftotext + claude",
      "verified": true,
      "first_seen": "2026-03-15",
      "last_checked": "2026-03-15"
    }
  ],
  
  "failed_sources": [
    {
      "url": "https://www.satsumaschools.com/gatorlife/student-calendar",
      "reason": "js_rendered_no_calendar_text",
      "attempted": "2026-03-15"
    }
  ],
  
  "search_strategies": {
    "best_query": "\"Satsuma City\" Alabama 2025-2026 school calendar pdf",
    "alternative_queries_tried": [
      "Satsuma City schools Alabama first day of school 2025"
    ],
    "forum_search_tried": false,
    "reddit_search_tried": false,
    "notes": "PDF found via Brave search, result #1. Finalsite CDN hosting."
  },
  
  "collection_history": {
    "2025-2026": {
      "dates": {
        "first_day": "2025-08-07",
        "last_day": "2026-05-22",
        "winter_break_start": "2025-12-22",
        "winter_break_end": "2026-01-02",
        "spring_break_start": "2026-04-13",
        "spring_break_end": "2026-04-17"
      },
      "primary_source": "finalsite_pdf",
      "secondary_source": null,
      "confidence": "high",
      "verified_by": "manual_review",
      "collected_date": "2026-03-15"
    }
  },
  
  "state_doe_source": {
    "available": false,
    "tier": "silver",
    "portal": "alabamaachieves.org",
    "notes": "Alabama has portal but per-district, not bulk download"
  },
  
  "district_characteristics": {
    "calendar_style": "traditional | year_round | modified",
    "typical_first_day_month": "august",
    "typical_first_day_week": "first_full_week",
    "publishes_pdf": true,
    "pdf_naming_pattern": "descriptive",
    "updates_calendar_online": true,
    "board_approves_calendar": true,
    "notes": "Small district, early August start typical for AL"
  }
}
```

## Collection Process (per district, per cycle)

### Step 1: Check Known Sources
If we've collected before, check the same sources first:
- Hit the known PDF URL pattern (version may change)
- Check the known calendar page
- Check state DOE if available

### Step 2: Search for New/Updated Sources  
- Brave: "{District Name}" "{State}" "2025-2026" school calendar pdf
- Brave: "{District Name}" schools first day spring break 2025
- Reddit/Forums: "{District Name}" spring break 2025 OR 2026

### Step 3: Extract & Validate
- Extract from best source (PDF preferred)
- Cross-validate against secondary source
- Compare to previous year's dates (sanity check — did they shift by >2 weeks?)
- Flag anomalies for review

### Step 4: Document Everything
- Record what worked/failed
- Update district profile
- Note any website changes

## Alternative Search Strategies (Fred's insight)

### Forum/Reddit Mining
- `"{District Name}" "spring break" 2026 site:reddit.com`
- `"{District Name}" "first day of school" 2025 site:reddit.com`
- `"{District Name}" school calendar 2025 site:facebook.com`
- Local news: `"{District Name}" school calendar 2025-2026 site:patch.com`

### Keyword Fragment Searches
- `"{District Name}" "August 7" school 2025` (when we know typical start date)
- `"{District Name}" "March 23" spring break` (search for specific dates)

### Third-Party Calendar Aggregators
- schools-calendar.com (has some districts)
- schooldistrictcalendar.org
- educounty.net  
- Facebook district pages (calendar images)

### Parent/Community Sources
- PTA websites
- Local newspaper articles
- Chamber of Commerce event calendars
- City government websites

## Hosting Platform Patterns
Districts use a small number of platforms. Knowing the platform helps find PDFs:

| Platform | URL Pattern | Notes |
|----------|-------------|-------|
| Finalsite | resources.finalsite.net/images/v{version}/{domain}/{hash}/{name}.pdf | Very common, CDN-hosted |
| Thrillshare | files-backend.assets.thrillshare.com/documents/... | Common in rural districts |
| SchoolWires/Blackboard | {district}.schoolwires.net | Redirects common |
| Core-Docs/S3 | core-docs.s3.us-east-1.amazonaws.com/documents/... | Direct S3 links |
| MyConnectSuite | content.myconnectsuite.com/api/documents/... | API-style URLs |
| Google Drive | drive.google.com/file/d/{id}/ | Some districts use GDrive |
| Edlio | www.edl.io/... | Older platform |
| WordPress | {district}.org/wp-content/uploads/... | Self-hosted WP |

## Quality Tiers

- **Verified**: Cross-checked against 2+ sources, or from state DOE
- **High**: From official district PDF, extracted cleanly
- **Medium**: From official website but HTML extraction
- **Low**: From third-party aggregator or single forum post
- **Unverified**: Extracted but not validated
