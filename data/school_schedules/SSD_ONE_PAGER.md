# SSD Product One-Pager — Customer-Facing

**US School Calendar Intelligence**
*hazeydata.ai*

---

## The Problem

Every business driven by seasonal family demand — theme parks, hotels, airlines, retailers — needs to know when students are on break. But no comprehensive, machine-readable, enrollment-weighted school calendar dataset exists as a commercial product. Companies either spend months collecting PDFs by hand, rely on incomplete aggregator sites, or simply guess.

## What We Built

The first enrollment-weighted US school calendar database with daily granularity.

**Coverage:**
- 13,400+ public school districts across all 50 states + DC
- 46M+ students (93%+ of US public school enrollment)
- Every major break: summer, winter, spring, fall, Thanksgiving
- Daily resolution: for any date, know exactly what % of students are on break

**Data Quality:**
- ~35-40% of enrollment backed by confirmed sources (direct from district calendars)
- Remaining districts modeled from state median patterns (±1 week accuracy)
- Enrollment-weighted using official NCES data
- Every data point tagged with a confidence level (confirmed / high / medium / inferred)

**Update Cadence:**
- Full annual refresh each summer (automated pipeline, <24 hours)
- Mid-year corrections for calendar amendments
- Historical data: 2024-2025 available; 2025-2026 current; expanding annually

## The Insight Layer

Raw calendars are table stakes. Our value is the analytics:

**The Spring Break Wave** — Spring break isn't one week. It's a rolling 6-week wave from early March through mid-April, peaking at ~35% of students off around late March/early April. We show you which districts are off on which days.

**Back-to-School Ramp** — Schools return over a 4-week period, from ~33% in session in early August to 90%+ by Labor Day. Timing varies by 4-6 weeks across states.

**Enrollment Weighting** — Not all districts are equal. Los Angeles Unified (426K students) matters more than a 200-student rural district. Our aggregate metrics reflect actual student populations, not just district counts.

## How It's Delivered

| Tier | What You Get | Price |
|------|-------------|-------|
| **Explorer API** | National + state-level daily aggregates | $99/mo |
| **Professional** | District-level access + bulk downloads + historical | $499/mo |
| **Enterprise** | Full dataset delivery + custom analytics + SLA | $25K-$100K/yr |

Formats: REST API (JSON), CSV, Parquet, Snowflake/BigQuery data share.

## Who It's For

- **Theme parks & attractions** — Attendance forecasting, staffing, dynamic pricing
- **Hotels & resorts** — Revenue management, demand prediction
- **Airlines** — Route planning, seasonal capacity, fare optimization
- **Retailers** — Back-to-school timing across markets
- **Travel platforms** — "When to book" features, search optimization
- **Marketing agencies** — Campaign timing, seasonal targeting

## How We Compare

| | hazeydata | Burbio | Inntopia SCX |
|--|-----------|--------|-------------|
| Districts | 13,400+ | ~15K (school-level) | 3,000+ |
| Universities | Not yet | No | Yes |
| Enrollment weighting | Yes | Unknown | No |
| Daily "% on break" | Yes | Yes (district %, not enrollment-weighted) | Dashboard only |
| API access | Planned | Limited | No |
| Historical depth | 2 years | Multi-year | 5+ years (since 20/21) |
| Update speed | Hours (automated) | Continuous | Quarterly |
| Primary market | All demand-driven | EdTech + travel/retail | Hospitality/resorts |
| Price range | $99/mo – $100K/yr | $3-6K/yr | Per-license |

**Our edge:** Enrollment weighting + automated pipeline + price flexibility.
**Their edge:** Burbio has broader EdTech intelligence; Inntopia has 5+ years history and university data.

## Get Started

Free 30-day Professional trial for qualified enterprise prospects.
Custom data samples available for your specific markets.

**Contact:** fred@hazeydata.ai | hazeydata.ai/school-calendars

---

*hazeydata.ai — School breaks drive demand. We have the data.*
