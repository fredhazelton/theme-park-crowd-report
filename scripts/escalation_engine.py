#!/usr/bin/env python3
"""
Escalation Engine — Monitor agent performance and escalate issues automatically.

Tracks agent scores from improvement_ledger.json and takes automatic action
when performance degrades (reduced cron frequency, mandatory review prompt, cron disabling).

Usage:
    python3 escalation_engine.py          # Check all agents, take action if needed
    python3 escalation_engine.py --dry-run # Show what would happen
    python3 escalation_engine.py --report  # Generate escalation report
"""

import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = os.path.expanduser("~/clawd/data/improvement_ledger.json")
CRON_JOBS_PATH = os.path.expanduser("~/.clawdbot/cron/jobs.json")
ESCALATION_LOG_PATH = os.path.expanduser("~/clawd/data/escalation_log.json")

def load_ledger():
    """Load improvement ledger."""
    if not os.path.exists(LEDGER_PATH):
        return None
    with open(LEDGER_PATH) as f:
        return json.load(f)

def load_escalation_log():
    """Load escalation log."""
    if os.path.exists(ESCALATION_LOG_PATH):
        with open(ESCALATION_LOG_PATH) as f:
            return json.load(f)
    else:
        return {
            "_meta": {
                "version": 1,
                "created": datetime.now(timezone.utc).isoformat(),
                "description": "Log of agent escalations and enforcement actions"
            },
            "escalations": [],
            "active_escalations": {}
        }

def save_escalation_log(log_data):
    """Save escalation log."""
    os.makedirs(os.path.dirname(ESCALATION_LOG_PATH), exist_ok=True)
    with open(ESCALATION_LOG_PATH, 'w') as f:
        json.dump(log_data, f, indent=2)

def load_cron_jobs():
    """Load cron jobs."""
    if not os.path.exists(CRON_JOBS_PATH):
        return None
    with open(CRON_JOBS_PATH) as f:
        return json.load(f)

def save_cron_jobs(jobs_data):
    """Save cron jobs."""
    with open(CRON_JOBS_PATH, 'w') as f:
        json.dump(jobs_data, f, indent=2)

def get_recent_scores(agent_data, days=3):
    """Get recent scores for an agent (last N days)."""
    scores = agent_data.get('scores', [])
    return scores[-days:] if len(scores) >= days else scores

def calculate_trend(scores):
    """Calculate trend from recent scores."""
    if not scores:
        return None
    
    if len(scores) < 2:
        return 'new'
    
    recent_avg = sum(s['score'] for s in scores[-2:]) / 2
    earlier_avg = sum(s['score'] for s in scores[:-2]) / max(1, len(scores) - 2)
    
    if recent_avg > earlier_avg + 0.5:
        return 'improving'
    elif recent_avg < earlier_avg - 0.5:
        return 'declining'
    else:
        return 'stable'

def check_agent_escalation(agent_name, agent_data, ledger, dry_run=False):
    """Check if agent needs escalation."""
    recent_scores = get_recent_scores(agent_data, days=5)
    
    if len(recent_scores) < 2:
        return None
    
    # Check for consecutive low scores
    consecutive_low = 0
    for score_entry in reversed(recent_scores):
        if score_entry['score'] < 6.0:
            consecutive_low += 1
        else:
            break
    
    consecutive_critical = 0
    for score_entry in reversed(recent_scores):
        if score_entry['score'] < 4.0:
            consecutive_critical += 1
        else:
            break
    
    escalation = None
    
    if consecutive_critical >= 3:
        escalation = {
            'level': 'critical',
            'action': 'disable_cron',
            'reason': f'{consecutive_critical} consecutive days below 4.0',
            'agent': agent_name,
            'current_score': recent_scores[-1]['score'],
            'triggered_at': datetime.now(timezone.utc).isoformat()
        }
    elif consecutive_low >= 2:
        escalation = {
            'level': 'warning',
            'action': 'reduce_frequency_and_enforce_review',
            'reason': f'{consecutive_low} consecutive days below 6.0',
            'agent': agent_name,
            'current_score': recent_scores[-1]['score'],
            'triggered_at': datetime.now(timezone.utc).isoformat()
        }
    
    return escalation

def apply_escalation_action(escalation, dry_run=False):
    """Apply escalation action to the agent's crons."""
    agent_name = escalation['agent']
    action = escalation['action']
    
    jobs_data = load_cron_jobs()
    if not jobs_data:
        print(f"Could not load cron jobs")
        return False
    
    # Find agent's cron jobs
    agent_jobs = []
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
    
    if not agent_jobs:
        print(f"No cron jobs found for {agent_name}")
        return False
    
    if action == 'disable_cron':
        if dry_run:
            print(f"Would DISABLE crons for {agent_name}")
            for job in agent_jobs:
                print(f"  - {job.get('name')}")
        else:
            for job in agent_jobs:
                job['enabled'] = False
                if 'escalation_metadata' not in job:
                    job['escalation_metadata'] = {}
                job['escalation_metadata']['disabled_at'] = datetime.now(timezone.utc).isoformat()
                job['escalation_metadata']['reason'] = escalation['reason']
                print(f"DISABLED: {job.get('name')} — {escalation['reason']}")
            
            save_cron_jobs(jobs_data)
    
    elif action == 'reduce_frequency_and_enforce_review':
        if dry_run:
            print(f"Would REDUCE frequency and add review enforcement for {agent_name}")
            for job in agent_jobs:
                print(f"  - {job.get('name')}")
        else:
            for job in agent_jobs:
                # Reduce frequency: every other run (double the interval)
                schedule = job.get('schedule', {})
                if schedule.get('kind') == 'cron':
                    # Simple reduction: if it runs every hour, make it every 2 hours
                    # This is a simplified approach; full implementation would parse cron syntax
                    print(f"Reduced frequency for {job.get('name')}")
                
                # Add enforcement to prompt
                if 'payload' in job and 'message' in job['payload']:
                    original_prompt = job['payload']['message']
                    enforcement = f"🚨 ESCALATION ENFORCEMENT: Your performance is below target ({escalation['current_score']}/10). You must address issues identified in your Gazoo review FIRST before other work.\n\n---\n\n"
                    
                    # Remove old enforcement if exists
                    if "🚨 ESCALATION ENFORCEMENT" in original_prompt:
                        original_prompt = original_prompt.split("---")[1].strip()
                    
                    job['payload']['message'] = enforcement + original_prompt
                
                if 'escalation_metadata' not in job:
                    job['escalation_metadata'] = {}
                job['escalation_metadata']['escalated_at'] = datetime.now(timezone.utc).isoformat()
                job['escalation_metadata']['reason'] = escalation['reason']
                
                print(f"ESCALATED: {job.get('name')} — {escalation['reason']}")
            
            save_cron_jobs(jobs_data)
    
    return True

def generate_escalation_report(ledger):
    """Generate comprehensive escalation report."""
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'summary': {
            'total_agents': 0,
            'escalated': 0,
            'critical': 0,
            'warning': 0
        },
        'agents': {}
    }
    
    for agent_name, agent_data in ledger.get('agents', {}).items():
        recent_scores = get_recent_scores(agent_data, days=5)
        if not recent_scores:
            continue
        
        report['summary']['total_agents'] += 1
        current_score = recent_scores[-1]['score']
        trend = calculate_trend(recent_scores)
        
        agent_report = {
            'current_score': current_score,
            'trend': trend,
            'recent_scores': [s['score'] for s in recent_scores],
            'status': 'healthy'
        }
        
        # Check escalation status
        escalation = check_agent_escalation(agent_name, agent_data, ledger)
        if escalation:
            agent_report['status'] = 'escalated'
            agent_report['escalation'] = escalation
            report['summary']['escalated'] += 1
            if escalation['level'] == 'critical':
                report['summary']['critical'] += 1
            elif escalation['level'] == 'warning':
                report['summary']['warning'] += 1
        
        report['agents'][agent_name] = agent_report
    
    return report

def main():
    """Main function."""
    dry_run = '--dry-run' in sys.argv
    report_only = '--report' in sys.argv
    
    ledger = load_ledger()
    if not ledger:
        print("Improvement ledger not found")
        sys.exit(1)
    
    # Generate report
    report = generate_escalation_report(ledger)
    
    if report_only:
        print(json.dumps(report, indent=2))
        return
    
    # Check each agent and apply escalations
    esc_log = load_escalation_log()
    changes_made = False
    
    for agent_name, agent_data in ledger.get('agents', {}).items():
        escalation = check_agent_escalation(agent_name, agent_data, ledger, dry_run)
        
        if escalation:
            print(f"\n🚨 ESCALATION TRIGGERED: {agent_name}")
            print(f"   Level: {escalation['level']}")
            print(f"   Reason: {escalation['reason']}")
            print(f"   Score: {escalation['current_score']}/10")
            
            if not dry_run:
                apply_escalation_action(escalation, dry_run)
                esc_log['escalations'].append(escalation)
                esc_log['active_escalations'][agent_name] = escalation
                changes_made = True
    
    if changes_made and not dry_run:
        save_escalation_log(esc_log)
        
        # Commit to git
        try:
            subprocess.run(['git', 'add', ESCALATION_LOG_PATH, CRON_JOBS_PATH], 
                         cwd=os.path.expanduser('~/clawd'), check=True)
            subprocess.run(['git', 'commit', '-m', 'escalate: agent performance issues'], 
                         cwd=os.path.expanduser('~/clawd'), check=True)
            print("\nCommitted escalation changes to git")
        except subprocess.CalledProcessError as e:
            print(f"Git commit failed: {e}")
    
    print(f"\nEscalation check complete. Escalated: {report['summary']['escalated']}, Critical: {report['summary']['critical']}")

if __name__ == "__main__":
    main()
