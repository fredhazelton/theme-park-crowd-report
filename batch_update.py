#!/usr/bin/env python3
import json
import subprocess
import sys

# Remaining jobs to update
REMAINING_JOBS = [
    ('085ec075-2228-4492-9232-30014df757b3', 'gazoo-review'),
    ('e9e8f2e6-36c4-4a2b-af50-1bbe89b5f9cf', 'orlando-blog'),
    ('b7b545e3-0eca-42c2-a12e-1859e06608c5', 'disneyland-blog'),
    ('4c395b0e-4933-480e-a24d-2e257643d4ea', 'blog-promo'),
    ('78c73df6-41f3-42bb-a115-4b6dde64f3e1', 'tokyo-blog'),
    ('337d8bab-ccf0-433f-ab0a-dc5ce0480566', 'bam-bam-am'),
    ('7212cb79-6f2b-41f3-aa1c-6c070cf42085', 'bam-bam-midday'),
    ('8d4e72ea-13a3-4aba-8264-8e6eb229338c', 'bam-bam-pm'),
    ('2d3e8742-5d14-4cd8-8d2b-d05222f652fa', 'bam-bam-patrol'),
    ('0a21a0b1-1876-4c7a-a341-78e7c1396b8d', 'betty-midday'),
    ('422c2768-2f56-4817-8b90-37c6255aba60', 'pebbles-midday'),
    ('80e218c8-e589-4ab9-860e-4a70c4290b81', 'arnold-midday'),
    ('65b40661-91ab-40e0-8b93-9144074819e8', 'dino-midday'),
    ('adb8e05f-e14d-4bdb-8ddb-7bcd73f25a46', 'mrslate-midday'),
    ('5d1dd8a9-8531-4920-8043-056334c8fac0', 'betty-pm'),
    ('306a84d8-51bc-4883-afa2-8dc3d24a34fa', 'pebbles-pm'),
    ('00c91318-2f8b-4808-af7d-92f908415748', 'arnold-pm'),
    ('a3109137-9ffe-42d4-af02-0fe563f33668', 'dino-pm'),
    ('4c04d622-52af-40c5-a7d0-7e3ac108762d', 'mrslate-pm'),
]

def get_status_block(job_key):
    return f'''
## 📡 Schedule Status Update — MANDATORY FINAL STEP
After ALL work is complete, update the live schedule board:
- Success: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' ok`
- Skipped: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' skip`
- Failed: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' error`
DO NOT SKIP THIS STEP.'''

def update_pipeline_gate(msg, job_key):
    """Update PIPELINE GATE sections to include status updater call."""
    if "PIPELINE GATE" not in msg:
        return msg
        
    lines = msg.split('\n')
    for i, line in enumerate(lines):
        if "PIPELINE GATE" in line and i + 1 < len(lines):
            next_line = lines[i + 1]
            if "post" in next_line.lower() and "exit" in next_line.lower():
                # Update to include status updater call
                if f"update_schedule_status.py '{job_key}' skip" not in next_line:
                    lines[i + 1] = next_line.replace(
                        "and exit", 
                        f", run `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' skip`, then exit"
                    ).replace(
                        "then exit.",
                        f", run `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '{job_key}' skip`, then exit."
                    )
    return '\n'.join(lines)

def main():
    with open('/home/wilma/.clawdbot/cron/jobs.json.bak', 'r') as f:
        backup = json.load(f)
    
    job_lookup = {job['id']: job for job in backup['jobs']}
    
    success_count = 0
    
    for job_id, job_key in REMAINING_JOBS:
        if job_id in job_lookup:
            job = job_lookup[job_id]
            msg = job['payload']['message']
            
            # Update pipeline gate if present
            msg = update_pipeline_gate(msg, job_key)
            
            # Add status block
            status_block = get_status_block(job_key)
            updated_msg = msg.rstrip() + status_block
            
            # Write to temp file and update
            with open('/tmp/update_msg.txt', 'w') as f:
                f.write(updated_msg)
            
            try:
                result = subprocess.run([
                    'clawdbot', 'cron', 'edit', job_id,
                    '--message', updated_msg
                ], capture_output=True, text=True, check=True)
                
                print(f'✅ Updated {job_key} ({job_id})')
                success_count += 1
            except subprocess.CalledProcessError as e:
                print(f'❌ Failed {job_key}: {e.stderr}')
        else:
            print(f'⚠️  Job {job_key} ({job_id}) not found in backup')
    
    print(f'\n✅ Successfully updated {success_count}/{len(REMAINING_JOBS)} remaining jobs')

if __name__ == "__main__":
    main()