# 🎫 Pipeline Tickets

> **Wilma** posts issues → **Bam-Bam** resolves them  
> Check this file periodically. New tickets appear at the top of OPEN section.

---

## 📋 Instructions for Bam-Bam

### When you see a new ticket:
1. Read the issue and suggested fix
2. Check the **URGENCY** level:
   - 🔴 **CRITICAL** — Pipeline is stuck/broken. **Kill it first**, then fix.
   - 🟡 **HIGH** — Fix soon, but pipeline can keep running
   - 🟢 **NORMAL** — Fix when convenient

### For CRITICAL tickets:
```bash
# 1. Kill the stuck pipeline (Wilma will provide PIDs if known)
kill <PID>
# or
pkill -f "run_daily_pipeline"

# 2. Remove lock file
rm -f /home/wilma/hazeydata/pipeline/state/processing.lock

# 3. Make your fix

# 4. Restart pipeline
cd /home/wilma/theme-park-crowd-report
./scripts/run_daily_pipeline.sh --skip-dropbox-check
```

### After fixing:
1. Move the ticket to ✅ RESOLVED section
2. Add resolution notes
3. Commit and push

### Format for resolution:
```markdown
- **Resolved:** YYYY-MM-DD HH:MM by Bam-Bam
- **Fix:** Brief description of what you changed
```

---

## 🔴 OPEN TICKETS

*No open tickets — pipeline is healthy! 🎉*

---

## ✅ RESOLVED

### [2026-02-02-001] S3 Streaming Connection Failures
- **Created:** 2026-02-02 08:00 by Wilma
- **Urgency:** 🔴 CRITICAL
- **Problem:** ETL stuck for 17+ hours, 141 connection errors streaming from S3
- **File:** `src/get_tp_wait_time_data_from_s3.py`
- **Error:** `ResponseStreamingError: IncompleteRead(33MB read, 2MB expected)`
- **Suggested fix:** Refactor to sync-first architecture (see `specs/PIPELINE-S3-SYNC-REFACTOR.md`)
- **Resolved:** 2026-02-02 — Bam-Bam implementing sync-first architecture
- **Fix:** Adding `aws s3 sync` step before ETL, reading from local files

---

## 📊 Statistics

| Metric | Value |
|--------|-------|
| Open tickets | 0 |
| Resolved this week | 1 |
| Last check | 2026-02-02 08:57 |
