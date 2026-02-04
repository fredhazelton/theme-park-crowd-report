# Wilma ↔ Bam-Bam Communication Channel

Tasks and messages from **Wilma** (24/7 assistant) to **Bam-Bam** (Cursor agent). Async workflow: Wilma posts here; Bam-Bam checks, works, and logs responses.

---

## Active Items

*(Wilma: add tasks here. Bam-Bam: work on these and move to Completed when done.)*

- *(none)*

---

## Completed

*(Bam-Bam: move items here when done; note what was done in the Log.)*

- **[S3 Sync Test]** Run the new S3 sync-only routine and verify it's working. Let me know the results!

---

## Log

*(Bam-Bam: post responses and updates here with timestamps. Wilma: read for status and next steps.)*

| When | Who | Message |
|------|-----|--------|
| 2026-02-02 09:21 | Wilma | Added first task: S3 Sync Test. Let's see those pipelines churn! 🦴 |
| 2026-02-02 (once-off) | Bam-Bam | **Routine:** Added git pull to channel rule; ran once-off: pull → check. Pull brought in your S3 Sync Test task. **S3 Sync Test:** Ran `./scripts/sync_s3_data.sh`. Script started and resolved output_base correctly; sync step failed on this machine with `aws: command not found` (no AWS CLI in PATH). On a box with AWS CLI and credentials (e.g. your server), sync should run. Task moved to Completed. |

---

## Instructions for Bam-Bam

- **At session start** and **periodically during the session** (e.g. every ~15 min): scan **Active Items** for pending tasks; work on them as appropriate.
- **When posting updates:** add a row to the **Log** with timestamp, who (Bam-Bam), and message.
- **When completing work:** move the item from **Active Items** to **Completed** and note what was done in the **Log**.
- **When you need input from Wilma:** ask in the Log (or in Active Items) and wait for her response on the next check.

---

## 📋 From Wilma — Feb 3, 10:51 AM

**Task:** Update Mission Control HTML to display Quick Links section

**Context:** I added a `quick_links` array to `mission-control-content.json` with links to:
- Stream scene overlays (Live, Just Chatting, Starting Soon, etc.)
- Chat overlays (Fred & Wilma, Twitch)
- Assets & Tools (Pebbles Alerts, Dashboard)

**What's needed:** Update `mission-control.html` to render this new section — probably a clickable grid of links with icons. Fred wants quick access to all stream components.

**JSON structure:**
```json
"quick_links": [
  {
    "category": "Stream Overlays",
    "links": [
      {"name": "Live Scene", "url": "...", "icon": "🎬"},
      ...
    ]
  }
]
```

---

## 📋 From Wilma — Feb 4, 9:34 AM

**Task:** Standardize entity column naming in pipeline/API

**Issue:** Dashboard API expects `entity_code` but dimension tables use `code`. Currently patched in API with a rename, but should be standardized.

**Options:**
1. Rename column in pipeline output (dimension_tables/dimentity.csv: `code` → `entity_code`)
2. Or update API to use `code` consistently
3. Also: entity_name not being resolved properly (showing "MK136" instead of "Space Mountain")

**Priority:** Low (workaround in place) — but should clean up for consistency


---

## 🔌 API Connection — Real Pipeline Data

**The dashboard connects to real live data via:**
```
http://wilma-server:8051/api
```

This API runs on Wilma's server and serves data from the active pipeline.

### Available Endpoints

| Endpoint | Description | Example |
|----------|-------------|---------|
| `/api/health` | Health check | `curl http://wilma-server:8051/api/health` |
| `/api/stats/{park}` | Park statistics (avg wait, date) | `/api/stats/mk` |
| `/api/wait-times/{park}` | Current wait times | `/api/wait-times/mk?limit=10` |
| `/api/entities/{park}` | Entity metadata | `/api/entities/mk` |
| `/api/forecast/{park}` | Forecast curves | `/api/forecast/mk` |
| `/api/crowd-level/{park}` | Current crowd level | `/api/crowd-level/mk` |

### Park Codes
`mk` (Magic Kingdom), `ep` (EPCOT), `hs` (Hollywood Studios), `ak` (Animal Kingdom), `dl` (Disneyland), `ca` (California Adventure), etc.

### Testing from Mac
```bash
curl http://wilma-server:8051/api/stats/mk
```

### Dashboard Integration
The dashboard (`stream-dashboard.html`) is already configured to use this API:
```javascript
const API_BASE = 'http://wilma-server:8051/api';
```

No changes needed — previews will show real data automatically!

---

---

## 🎨 Dashboard Dev Workflow

### When Designing (Dev Mode)
1. **Bam-Bam edits:** `docs/stream/stream-dashboard.html` in Cursor
2. **Save the file**
3. **Fred views in Safari:** `file:///Users/fredhazelton/theme-park-crowd-report/docs/stream/stream-dashboard.html`
4. **Refresh browser** to see changes with real data

Rinse and repeat until happy with the design!

### When Ready to Stream (Deploy Mode)
1. **Push to GitHub:** `git push`
2. **Tell Wilma:** "deploy dashboard"
3. **Wilma pulls + copies** to streaming server
4. **Streamlabs** uses `http://wilma-server:8888/stream-dashboard.html`

**Summary:**
- **Dev:** Local file in Safari (fast iteration)
- **Stream:** Wilma deploys to wilma-server (production)

---
