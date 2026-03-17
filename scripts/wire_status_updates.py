#!/usr/bin/env python3
"""
Wire up all cron jobs with schedule status update calls.
Reads current cron state, appends the status update instruction to each job's prompt.
Outputs the cron update commands needed.
"""

# Mapping: cron job ID -> status update key
JOBS = {
    "200a6443-9f11-4980-bb06-a4e74f7e75fb": "dino-work",
    "1c922b4f-f9b5-485a-8556-6bec9654c4d2": "arnold-work",
    "07cb0d35-7e1c-4c7e-833e-63671fe1b7fb": "betty-work",
    "d2f43a73-bc86-4d2e-adb8-12c5c3a74cce": "pebbles-work",
    "dc2588c3-6299-4cfa-9b51-e28a4f20436f": "mrslate-work",
    "58caf682-2a87-4136-92ee-9246081a2257": "wilma-work",
    "e0e69578-85b9-4001-8950-3c3edf6912bf": "park-intel",
    "fe1f823c-fbb3-4d1d-93e0-0ca3f683d8e7": "accuracy-report",
    "c63be83e-5330-495c-9c33-34f6351b5292": "morning-tweet",
    "c3566e00-f234-4918-97b6-ae64d204a192": "stale-tasks",
    "337d8bab-ccf0-433f-ab0a-dc5ce0480566": "bam-bam-am",
    "4c395b0e-4933-480e-a24d-2e257643d4ea": "blog-promo",
    "49badc8f-a921-4f98-b847-5c201d314fe8": "reddit-scout",
    "0a21a0b1-1876-4c7a-a341-78e7c1396b8d": "betty-midday",
    "e6fed3d2-4999-4d52-b5f1-5d346bb9262a": "competitor-watch",
    "7212cb79-6f2b-41f3-aa1c-6c070cf42085": "bam-bam-midday",
    "422c2768-2f56-4817-8b90-37c6255aba60": "pebbles-midday",
    "80e218c8-e589-4ab9-860e-4a70c4290b81": "arnold-midday",
    "65b40661-91ab-40e0-8b93-9144074819e8": "dino-midday",
    "adb8e05f-e14d-4bdb-8ddb-7bcd73f25a46": "mrslate-midday",
    "e2079918-9917-4d1a-8b51-d2ec730e66e2": "afternoon-tweet",
    "8d4e72ea-13a3-4aba-8264-8e6eb229338c": "bam-bam-pm",
    "5d1dd8a9-8531-4920-8043-056334c8fac0": "betty-pm",
    "306a84d8-51bc-4883-afa2-8dc3d24a34fa": "pebbles-pm",
    "00c91318-2f8b-4808-af7d-92f908415748": "arnold-pm",
    "a3109137-9ffe-42d4-af02-0fe563f33668": "dino-pm",
    "4c04d622-52af-40c5-a7d0-7e3ac108762d": "mrslate-pm",
    "085ec075-2228-4492-9232-30014df757b3": "gazoo-review",
    "2d3e8742-5d14-4cd8-8d2b-d05222f652fa": "bam-bam-patrol",
    "e9e8f2e6-36c4-4a2b-af50-1bbe89b5f9cf": "orlando-blog",
    "78c73df6-41f3-42bb-a115-4b6dde64f3e1": "tokyo-blog",
    "b7b545e3-0eca-42c2-a12e-1859e06608c5": "disneyland-blog",
}

STATUS_BLOCK = """
## 📡 Schedule Status Update — MANDATORY FINAL STEP
After ALL work is complete (success or failure), update the live schedule board:
- If everything succeeded: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{key}' ok`
- If you skipped (pipeline gate, etc.): `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{key}' skip`
- If anything failed: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{key}' error`
This updates the pinned schedule in #briefing with a real-time status indicator. DO NOT SKIP THIS STEP."""

for job_id, key in JOBS.items():
    block = STATUS_BLOCK.replace("{key}", key)
    print(f"JOB_ID={job_id} KEY={key}")
    print(block)
    print("---")
