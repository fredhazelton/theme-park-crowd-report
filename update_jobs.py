#!/usr/bin/env python3
"""
Update all 31 cron jobs to add the schedule status update block.
"""

import subprocess
import json
import sys

# Job mapping: jobId -> (job_key, current_message_extract_or_pattern)
JOBS_TO_UPDATE = {
    "1c922b4f-f9b5-485a-8556-6bec9654c4d2": ("arnold-work", "Arnold work session"),
    "07cb0d35-7e1c-4c7e-833e-63671fe1b7fb": ("betty-work", "Betty work session"),  
    "d2f43a73-bc86-4d2e-adb8-12c5c3a74cce": ("pebbles-work", "Pebbles work session"),
    "dc2588c3-6299-4cfa-9b51-e28a4f20436f": ("mrslate-work", "Mr. Slate work session"),
    "58caf682-2a87-4136-92ee-9246081a2257": ("wilma-work", "Wilma work session"),
    "e0e69578-85b9-4001-8950-3c3edf6912bf": ("park-intel", "Park Intel daily"),
    "fe1f823c-fbb3-4d1d-93e0-0ca3f683d8e7": ("accuracy-report", "Daily accuracy report"),
    "c63be83e-5330-495c-9c33-34f6351b5292": ("morning-tweet", "Daily morning tweet"),
    "c3566e00-f234-4918-97b6-ae64d204a192": ("stale-tasks", "Stale task daily check"),
    "337d8bab-ccf0-433f-ab0a-dc5ce0480566": ("bam-bam-am", "Bam-bam active sprint AM"),
    "4c395b0e-4933-480e-a24d-2e257643d4ea": ("blog-promo", "Daily blog promo tweet"),
    "49badc8f-a921-4f98-b847-5c201d314fe8": ("reddit-scout", "Reddit scout"),
    "0a21a0b1-1876-4c7a-a341-78e7c1396b8d": ("betty-midday", "Betty midday sprint"),
    "e6fed3d2-4999-4d52-b5f1-5d346bb9262a": ("competitor-watch", "Competitor watch daily"),
    "7212cb79-6f2b-41f3-aa1c-6c070cf42085": ("bam-bam-midday", "Bam-bam active sprint midday"),
    "422c2768-2f56-4817-8b90-37c6255aba60": ("pebbles-midday", "Pebbles midday sprint"),
    "80e218c8-e589-4ab9-860e-4a70c4290b81": ("arnold-midday", "Arnold midday sprint"),
    "65b40661-91ab-40e0-8b93-9144074819e8": ("dino-midday", "Dino midday sprint"),
    "adb8e05f-e14d-4bdb-8ddb-7bcd73f25a46": ("mrslate-midday", "Mr. Slate midday sprint"),
    "e2079918-9917-4d1a-8b51-d2ec730e66e2": ("afternoon-tweet", "Daily afternoon tweet"),
    "8d4e72ea-13a3-4aba-8264-8e6eb229338c": ("bam-bam-pm", "Bam-bam active sprint PM"),
    "5d1dd8a9-8531-4920-8043-056334c8fac0": ("betty-pm", "Betty PM sprint"),
    "306a84d8-51bc-4883-afa2-8dc3d24a34fa": ("pebbles-pm", "Pebbles PM sprint"),
    "00c91318-2f8b-4808-af7d-92f908415748": ("arnold-pm", "Arnold PM sprint"),
    "a3109137-9ffe-42d4-af02-0fe563f33668": ("dino-pm", "Dino PM sprint"),
    "4c04d622-52af-40c5-a7d0-7e3ac108762d": ("mrslate-pm", "Mr. Slate PM sprint"),
    "085ec075-2228-4492-9232-30014df757b3": ("gazoo-review", "Gazoo review daily"),
    "2d3e8742-5d14-4cd8-8d2b-d05222f652fa": ("bam-bam-patrol", "Bam-bam patrol"),
    "e9e8f2e6-36c4-4a2b-af50-1bbe89b5f9cf": ("orlando-blog", "Orlando this week blog"),
    "78c73df6-41f3-42bb-a115-4b6dde64f3e1": ("tokyo-blog", "Tokyo this week blog"),
    "b7b545e3-0eca-42c2-a12e-1859e06608c5": ("disneyland-blog", "Disneyland this week blog"),
}

def get_status_update_block(job_key):
    """Generate the status update block for a job."""
    return f"""
## 📡 Schedule Status Update — MANDATORY FINAL STEP
After ALL work is complete, update the live schedule board:
- Success: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' ok`
- Skipped: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' skip`
- Failed: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' error`
DO NOT SKIP THIS STEP."""

def load_backup_jobs():
    """Load jobs from backup file."""
    with open('/home/wilma/.clawdbot/cron/jobs.json.bak', 'r') as f:
        backup = json.load(f)
    return {job['id']: job for job in backup['jobs']}

def update_job(job_id, original_message, job_key):
    """Update a single job with the status block."""
    # Add status update block to the message
    status_block = get_status_update_block(job_key)
    updated_message = original_message.rstrip() + status_block
    
    # Also update PIPELINE GATE sections if present
    if "PIPELINE GATE" in updated_message and job_key != "gazoo-review":
        # Find PIPELINE GATE sections and update them
        lines = updated_message.split('\n')
        for i, line in enumerate(lines):
            if "PIPELINE GATE" in line and i + 1 < len(lines):
                # Look for the exit instruction
                next_line = lines[i + 1]
                if "post" in next_line and "exit" in next_line.lower():
                    # Update to include status updater call
                    lines[i + 1] = next_line.replace("and exit", f", run `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' skip`, then exit")
        updated_message = '\n'.join(lines)
    
    # Use clawdbot cron edit to update the job
    try:
        result = subprocess.run([
            'clawdbot', 'cron', 'edit', job_id,
            '--message', updated_message
        ], capture_output=True, text=True, check=True)
        
        print(f"✅ Updated {job_id} ({job_key})")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to update {job_id} ({job_key}): {e}")
        print(f"   Error output: {e.stderr}")
        return False

def main():
    print("Loading backup jobs...")
    backup_jobs = load_backup_jobs()
    
    success_count = 0
    total_count = len(JOBS_TO_UPDATE)
    
    print(f"Updating {total_count} jobs...")
    
    for job_id, (job_key, description) in JOBS_TO_UPDATE.items():
        if job_id in backup_jobs:
            original_message = backup_jobs[job_id]['payload']['message']
            
            # Skip if already has status update
            if "Schedule Status Update" in original_message:
                print(f"⏭️  Skipped {job_id} ({job_key}) - already has status update")
                success_count += 1
                continue
                
            if update_job(job_id, original_message, job_key):
                success_count += 1
        else:
            print(f"⚠️  Job {job_id} ({job_key}) not found in backup")
    
    print(f"\n✅ Successfully updated {success_count}/{total_count} jobs")

if __name__ == "__main__":
    main()