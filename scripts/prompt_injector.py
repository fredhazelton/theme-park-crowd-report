#!/usr/bin/env python3
"""
Prompt Injector — Inject enforcement instructions into agent cron prompts.

Reads unresolved issues from improvement_ledger.json and injects specific
enforcement instructions into the relevant agent's cron prompts.

Usage:
    # Inject all pending enforcement instructions
    python3 prompt_injector.py

    # Inject for specific agent
    python3 prompt_injector.py --agent dino

    # Dry run (show what would be injected)
    python3 prompt_injector.py --dry-run

    # Remove enforcement instructions (clean prompts)
    python3 prompt_injector.py --clean
"""

import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = os.path.expanduser("~/clawd/data/improvement_ledger.json")
CRON_JOBS_PATH = os.path.expanduser("~/.clawdbot/cron/jobs.json")
BACKUP_DIR = os.path.expanduser("~/clawd/data/prompt_backups")

def load_ledger():
    """Load improvement ledger."""
    if not os.path.exists(LEDGER_PATH):
        print(f"Improvement ledger not found: {LEDGER_PATH}")
        sys.exit(1)
    
    with open(LEDGER_PATH) as f:
        return json.load(f)

def load_cron_jobs():
    """Load cron jobs configuration."""
    if not os.path.exists(CRON_JOBS_PATH):
        print(f"Cron jobs file not found: {CRON_JOBS_PATH}")
        sys.exit(1)
    
    with open(CRON_JOBS_PATH) as f:
        return json.load(f)

def save_cron_jobs(jobs_data):
    """Save cron jobs configuration."""
    # Create backup
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"jobs_{timestamp}.json")
    
    with open(backup_path, 'w') as f:
        json.dump(jobs_data, f, indent=2)
    
    # Save updated jobs
    with open(CRON_JOBS_PATH, 'w') as f:
        json.dump(jobs_data, f, indent=2)
    
    print(f"Cron jobs updated. Backup saved to: {backup_path}")

def get_agent_cron_jobs(agent_name):
    """Find cron jobs for a specific agent."""
    jobs_data = load_cron_jobs()
    agent_jobs = []
    
    # Map agent names to cron job patterns
    agent_patterns = {
        'dino': ['dino'],
        'arnold': ['arnold'],
        'betty': ['betty'],
        'pebbles': ['pebbles'],
        'mr-slate': ['mr-slate', 'slate'],
        'bam-bam': ['bam-bam', 'bambam'],
        'gazoo': ['gazoo'],
        'wilma': ['wilma']
    }
    
    patterns = agent_patterns.get(agent_name, [agent_name])
    
    for job in jobs_data.get('jobs', []):
        job_name = job.get('name', '').lower()
        for pattern in patterns:
            if pattern in job_name:
                agent_jobs.append(job)
                break
    
    return agent_jobs, jobs_data

def generate_enforcement_instruction(issue):
    """Generate specific enforcement instruction for an issue."""
    severity_prefixes = {
        'critical': '🚨 CRITICAL ENFORCEMENT',
        'high': '⚠️ HIGH PRIORITY ENFORCEMENT',
        'medium': '📋 ENFORCEMENT REQUIRED',
        'low': '💡 IMPROVEMENT ENFORCEMENT'
    }
    
    prefix = severity_prefixes.get(issue.get('severity', 'medium'), '📋 ENFORCEMENT REQUIRED')
    
    instruction = f"""
## {prefix} - Issue {issue['id']}
**Problem:** {issue['description']}
**Open for:** {issue.get('cycles_open', 0)} cycles
**Action required:** Address this specific issue in today's work session.
**Status:** This instruction will be automatically removed once the issue is marked as fixed.
"""
    
    return instruction.strip()

def inject_enforcement_into_prompt(original_prompt, enforcement_instructions):
    """Inject enforcement instructions at the beginning of a prompt."""
    if not enforcement_instructions:
        return original_prompt
    
    # Remove existing enforcement sections
    cleaned_prompt = remove_enforcement_sections(original_prompt)
    
    # Add new enforcement instructions at the top
    enforcement_block = "\n".join(enforcement_instructions)
    enforcement_section = f"""
{enforcement_block}

---
""".strip()
    
    # Insert after any pipeline gate but before main content
    if "PIPELINE GATE:" in cleaned_prompt:
        parts = cleaned_prompt.split("PIPELINE GATE:")
        if len(parts) > 1:
            gate_end = parts[1].find('\n\n')
            if gate_end != -1:
                before_gate = parts[0]
                gate_section = "PIPELINE GATE:" + parts[1][:gate_end + 2]
                after_gate = parts[1][gate_end + 2:]
                return f"{before_gate}{gate_section}{enforcement_section}\n\n{after_gate}"
    
    # Default: add at the beginning
    return f"{enforcement_section}\n\n{cleaned_prompt}"

def remove_enforcement_sections(prompt):
    """Remove existing enforcement sections from a prompt."""
    import re
    
    # Remove enforcement blocks
    patterns = [
        r'## 🚨 CRITICAL ENFORCEMENT.*?(?=\n##|\n---|\Z)',
        r'## ⚠️ HIGH PRIORITY ENFORCEMENT.*?(?=\n##|\n---|\Z)',
        r'## 📋 ENFORCEMENT REQUIRED.*?(?=\n##|\n---|\Z)',
        r'## 💡 IMPROVEMENT ENFORCEMENT.*?(?=\n##|\n---|\Z)',
        r'---\n(?=\n##)'  # Remove separator lines before main content
    ]
    
    cleaned = prompt
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.MULTILINE)
    
    # Clean up multiple newlines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    
    return cleaned.strip()

def inject_for_agent(agent_name, dry_run=False):
    """Inject enforcement instructions for a specific agent."""
    ledger = load_ledger()
    
    if agent_name not in ledger.get('agents', {}):
        print(f"Agent not found in ledger: {agent_name}")
        return False
    
    agent_data = ledger['agents'][agent_name]
    
    # Get open issues
    open_issues = [issue for issue in agent_data.get('issues', []) if issue.get('status') == 'open']
    
    if not open_issues:
        print(f"No open issues for {agent_name}")
        return False
    
    # Generate enforcement instructions
    enforcement_instructions = []
    for issue in open_issues:
        instruction = generate_enforcement_instruction(issue)
        enforcement_instructions.append(instruction)
    
    # Find agent's cron jobs
    agent_jobs, jobs_data = get_agent_cron_jobs(agent_name)
    
    if not agent_jobs:
        print(f"No cron jobs found for {agent_name}")
        return False
    
    changes_made = False
    
    for job in agent_jobs:
        if 'payload' in job and 'message' in job['payload']:
            original_prompt = job['payload']['message']
            updated_prompt = inject_enforcement_into_prompt(original_prompt, enforcement_instructions)
            
            if original_prompt != updated_prompt:
                if dry_run:
                    print(f"Would update job '{job['name']}' for {agent_name}")
                    print(f"Enforcement instructions: {len(enforcement_instructions)}")
                else:
                    job['payload']['message'] = updated_prompt
                    
                    # Add metadata
                    if 'enforcement_metadata' not in job:
                        job['enforcement_metadata'] = {}
                    
                    job['enforcement_metadata'].update({
                        'last_updated': datetime.now(timezone.utc).isoformat(),
                        'issues_enforced': [issue['id'] for issue in open_issues],
                        'injector_version': '1.0',
                        'total_issues': len(open_issues)
                    })
                    
                    print(f"Updated job '{job['name']}' with {len(enforcement_instructions)} enforcement instruction(s)")
                    changes_made = True
    
    if changes_made and not dry_run:
        save_cron_jobs(jobs_data)
        
        # Commit to git
        commit_message = f"enforce: {agent_name} issues {', '.join([i['id'] for i in open_issues])} via Gazoo"
        try:
            subprocess.run(['git', 'add', CRON_JOBS_PATH], cwd=os.path.expanduser('~/clawd'), check=True)
            subprocess.run(['git', 'commit', '-m', commit_message], cwd=os.path.expanduser('~/clawd'), check=True)
            print(f"Committed changes: {commit_message}")
        except subprocess.CalledProcessError as e:
            print(f"Git commit failed: {e}")
    
    return changes_made

def clean_enforcement_instructions(agent_name=None, dry_run=False):
    """Remove all enforcement instructions from cron prompts."""
    jobs_data = load_cron_jobs()
    changes_made = False
    
    for job in jobs_data.get('jobs', []):
        job_name = job.get('name', '').lower()
        
        # Skip if specific agent requested and this job doesn't match
        if agent_name:
            agent_patterns = {
                'dino': ['dino'],
                'arnold': ['arnold'],
                'betty': ['betty'],
                'pebbles': ['pebbles'],
                'mr-slate': ['mr-slate', 'slate'],
                'bam-bam': ['bam-bam', 'bambam'],
                'gazoo': ['gazoo'],
                'wilma': ['wilma']
            }
            patterns = agent_patterns.get(agent_name, [agent_name])
            if not any(pattern in job_name for pattern in patterns):
                continue
        
        if 'payload' in job and 'message' in job['payload']:
            original_prompt = job['payload']['message']
            cleaned_prompt = remove_enforcement_sections(original_prompt)
            
            if original_prompt != cleaned_prompt:
                if dry_run:
                    print(f"Would clean job '{job['name']}'")
                else:
                    job['payload']['message'] = cleaned_prompt
                    
                    # Remove enforcement metadata
                    if 'enforcement_metadata' in job:
                        del job['enforcement_metadata']
                    
                    print(f"Cleaned enforcement instructions from '{job['name']}'")
                    changes_made = True
    
    if changes_made and not dry_run:
        save_cron_jobs(jobs_data)
        
        # Commit to git
        target = f" {agent_name}" if agent_name else ""
        commit_message = f"clean: remove enforcement instructions{target}"
        try:
            subprocess.run(['git', 'add', CRON_JOBS_PATH], cwd=os.path.expanduser('~/clawd'), check=True)
            subprocess.run(['git', 'commit', '-m', commit_message], cwd=os.path.expanduser('~/clawd'), check=True)
            print(f"Committed changes: {commit_message}")
        except subprocess.CalledProcessError as e:
            print(f"Git commit failed: {e}")
    
    return changes_made

def inject_all_pending(dry_run=False):
    """Inject enforcement instructions for all agents with open issues."""
    ledger = load_ledger()
    agents_updated = []
    
    for agent_name, agent_data in ledger.get('agents', {}).items():
        open_issues = [issue for issue in agent_data.get('issues', []) if issue.get('status') == 'open']
        
        if open_issues:
            if inject_for_agent(agent_name, dry_run):
                agents_updated.append(agent_name)
    
    if agents_updated:
        print(f"\n{'Would update' if dry_run else 'Updated'} {len(agents_updated)} agent(s): {', '.join(agents_updated)}")
    else:
        print("No agents required enforcement instruction updates.")
    
    return len(agents_updated) > 0

def main():
    """Main function."""
    dry_run = '--dry-run' in sys.argv
    clean_mode = '--clean' in sys.argv
    agent_filter = None
    
    # Parse agent filter
    if '--agent' in sys.argv:
        try:
            agent_idx = sys.argv.index('--agent')
            if agent_idx + 1 < len(sys.argv):
                agent_filter = sys.argv[agent_idx + 1]
        except (ValueError, IndexError):
            print("Error: --agent requires an agent name")
            sys.exit(1)
    
    if clean_mode:
        clean_enforcement_instructions(agent_filter, dry_run)
    elif agent_filter:
        inject_for_agent(agent_filter, dry_run)
    else:
        inject_all_pending(dry_run)

if __name__ == "__main__":
    main()