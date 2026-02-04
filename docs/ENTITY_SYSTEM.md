# HazeyData Canonical Entity System

## Overview

We maintain our own canonical entity identification system that is **source-agnostic**. This allows us to:
- Integrate data from multiple sources (TouringPlans, queue-times.com, future APIs)
- Survive if any single source changes IDs or goes away
- Have a single source of truth for entity metadata

## Schema

**File:** `dimension_tables/hazeydata_entities.csv`

| Column | Type | Description |
|--------|------|-------------|
| `hazeydata_id` | string | Our canonical ID (e.g., `HZ00001`) |
| `name` | string | Canonical entity name |
| `short_name` | string | Abbreviated name |
| `park_code` | string | Park code (mk, ep, hs, ak, dl, ca, etc.) |
| `land` | string | Land/area within the park |
| `entity_type` | string | Type: attraction, show, meet, restaurant, etc. |
| `is_active` | bool | Currently operating? |
| `has_wait_times` | bool | Does this entity have posted wait times? |
| `touringplans_code` | string | TouringPlans entity code (e.g., MK01) |
| `touringplans_entity_id` | int | TouringPlans internal ID |
| `queue_times_id` | int | Queue-times.com ride ID |
| `opened_on` | date | Opening date |
| `extinct_on` | date | Closure date (null if active) |
| `duration_minutes` | float | Ride/show duration |
| `hourly_capacity` | float | Estimated hourly capacity |

## ID Format

- **hazeydata_id:** `HZ` + 5-digit zero-padded number (e.g., `HZ00001`, `HZ01478`)
- Sequential assignment, never reused
- New entities get the next available number

## External ID Mappings

The canonical table includes columns for external IDs:
- `touringplans_code` → TouringPlans entity code (MK01, EP05, etc.)
- `queue_times_id` → Queue-times.com internal ride ID

Future columns can be added:
- `themeparks_wiki_id` → ThemeParks.wiki API ID
- `disney_api_id` → Disney's internal ID (if available)

## Usage

### In Pipeline Code
```python
# Load canonical entities
entities = pd.read_csv("dimension_tables/hazeydata_entities.csv")

# Translate queue-times ID to hazeydata_id
def qt_to_hz(qt_id):
    match = entities[entities['queue_times_id'] == qt_id]
    return match.iloc[0]['hazeydata_id'] if not match.empty else None
```

### In Dashboard/API
All internal systems should reference `hazeydata_id`. External IDs are only used at ingest boundaries.

## Adding New Sources

1. Fetch entity list from new source
2. Match to existing canonical entities by name (fuzzy matching)
3. Add new column for the source's ID (e.g., `new_source_id`)
4. For unmatched entities, create new hazeydata_ids

## Maintenance

When TouringPlans or queue-times adds new attractions:
1. Run the entity sync script (TBD)
2. Review new/unmatched entities
3. Assign hazeydata_ids to new attractions
4. Update mappings as needed

---
*Created: 2026-02-04*
*Seeded from: TouringPlans dimentity.csv (1707 entities)*
