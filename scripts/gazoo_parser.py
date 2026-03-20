#!/usr/bin/env python3
"""
Gazoo Parser — Extract structured data from daily Gazoo reviews.

Parses daily Gazoo reviews (from ~/clawd/gazoo-reviews/) and feeds
structured data into improvement_ledger.json. This powers the 
accountability enforcement layer.

Usage:
    # Parse today's review
    python3 gazoo_parser.py

    # Parse specific review
    python3 gazoo_parser.py 2026-03-19.md

    # Parse all reviews in directory
    python3 gazoo_parser.py --all
"""

import json
import os
import sys
import re
from datetime import datetime, timezone
from pathlib import Path

GAZOO_REVIEWS_DIR = os.path.expanduser("~/clawd/gazoo-reviews")
LEDGER_PATH = os.path.expanduser("~/clawd/data/improvement_ledger.json")

def load_ledger():
    """Load improvement ledger."""
    if os.path.exists(LEDGER_PATH):
        with open(LEDGER_PATH) as f:
            return json.load(f)
    else:
        # Initialize basic structure if doesn't exist
        return {
            "_meta": {
                "version": 1,
                "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "description": "Recursive improvement tracking. Gazoo raises issues, Wilma tracks patterns, prompts evolve."
            },
            "agents": {},
            "system": {
                "total_cycles": 0,
                "prompt_patches_pending_review": 0,
                "escalations_active": 0
            }
        }

def save_ledger(data):
    """Save improvement ledger."""
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, "w") as f:
        json.dump(data, f, indent=2)

def extract_agent_scores(review_text):
    """Extract agent scores from review text."""
    scores = {}
    
    # Common patterns for agent scores
    patterns = [
        r'(\w+):\s*(\d+(?:\.\d+)?)/10',
        r'(\w+)\s+(\d+(?:\.\d+)?)/10',
        r'(\w+).*?grade.*?(\d+(?:\.\d+)?)',
        r'(\w+).*?score.*?(\d+(?:\.\d+)?)',
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, review_text, re.IGNORECASE)
        for match in matches:
            agent = match.group(1).lower()
            score = float(match.group(2))
            if agent in ['dino', 'arnold', 'betty', 'pebbles', 'mr-slate', 'bam-bam', 'gazoo', 'wilma']:
                scores[agent] = min(10.0, max(0.0, score))  # Clamp to 0-10
    
    return scores

def extract_issues_raised(review_text, date_str):
    """Extract issues raised in the review."""
    issues = []
    
    # Look for issues patterns
    issue_patterns = [
        r'Issue raised.*?(\w+).*?severity:?\s*(\w+).*?"([^"]+)"',
        r'(\w+).*?problem.*?severity:?\s*(\w+).*?"([^"]+)"',
        r'(\w+).*?issue.*?"([^"]+)".*?severity:?\s*(\w+)',
        r'Raised.*?(\w+)-(\d+).*?"([^"]+)".*?(\w+)',
    ]
    
    for pattern in issue_patterns:
        matches = re.finditer(pattern, review_text, re.IGNORECASE | re.DOTALL)
        for match in matches:
            groups = match.groups()
            if len(groups) >= 3:
                agent = groups[0].lower() if groups[0].lower() in ['dino', 'arnold', 'betty', 'pebbles', 'mr-slate', 'bam-bam', 'gazoo', 'wilma'] else None
                severity = 'medium'  # default
                description = ''
                
                # Try to parse groups based on pattern
                for i, group in enumerate(groups):
                    if group.lower() in ['low', 'medium', 'high', 'critical']:
                        severity = group.lower()
                    elif len(group) > 10 and '"' not in group:  # Likely description
                        description = group
                
                if agent and description:
                    issues.append({
                        'agent': agent,
                        'severity': severity,
                        'problem': description.strip(),
                        'date_raised': date_str,
                        'status': 'open'
                    })
    
    return issues

def extract_issues_fixed(review_text):
    """Extract issues marked as fixed."""
    fixed = []
    
    # Look for fixed issue patterns
    fixed_patterns = [
        r'Fixed\s+([A-Z]+-\d+)',
        r'([A-Z]+-\d+).*?fixed',
        r'Issue\s+([A-Z]+-\d+).*?resolved',
        r'Closed\s+([A-Z]+-\d+)',
    ]
    
    for pattern in fixed_patterns:
        matches = re.finditer(pattern, review_text, re.IGNORECASE)
        for match in matches:
            issue_id = match.group(1).upper()
            fixed.append(issue_id)
    
    return fixed

def extract_grade_trends(review_text):
    """Extract grade trend indicators (improving/declining)."""
    trends = {}
    
    # Look for trend indicators
    trend_patterns = [
        r'(\w+).*?(improving|declined|declining|flat|better|worse)',
        r'(improving|declining|flat|better|worse).*?(\w+)',
    ]
    
    for pattern in trend_patterns:
        matches = re.finditer(pattern, review_text, re.IGNORECASE)
        for match in matches:
            groups = match.groups()
            for group in groups:
                if group.lower() in ['dino', 'arnold', 'betty', 'pebbles', 'mr-slate', 'bam-bam', 'gazoo', 'wilma']:
                    agent = group.lower()
                    for other in groups:
                        if other.lower() in ['improving', 'better']:
                            trends[agent] = 'improving'
                        elif other.lower() in ['declining', 'declined', 'worse']:
                            trends[agent] = 'declining'
                        elif other.lower() == 'flat':
                            trends[agent] = 'flat'
    
    return trends

def parse_gazoo_review(filepath, update_ledger=True):
    """Parse a single Gazoo review file."""
    if not os.path.exists(filepath):
        print(f"Review file not found: {filepath}")
        return None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract date from filename
    filename = os.path.basename(filepath)
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    review_date = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")
    
    # Parse review components
    parsed = {
        'date': review_date,
        'source_file': filepath,
        'agent_scores': extract_agent_scores(content),
        'issues_raised': extract_issues_raised(content, review_date),
        'issues_fixed': extract_issues_fixed(content),
        'grade_trends': extract_grade_trends(content),
        'raw_content': content[:1000] + '...' if len(content) > 1000 else content  # Truncated for storage
    }
    
    if update_ledger:
        update_improvement_ledger(parsed)
    
    return parsed

def update_improvement_ledger(parsed_review):
    """Update improvement ledger with parsed review data."""
    ledger = load_ledger()
    review_date = parsed_review['date']
    
    # Update agent scores
    for agent, score in parsed_review['agent_scores'].items():
        if agent not in ledger['agents']:
            ledger['agents'][agent] = {
                'role': get_agent_role(agent),
                'issues': [],
                'scores': [],
                'trend': 'new',
                'prompt_patches': [],
                'stats': {
                    'total_issues': 0,
                    'fixed': 0,
                    'avg_cycles_to_fix': 0.0
                }
            }
        
        # Add score (don't duplicate same date)
        existing_dates = [s['date'] for s in ledger['agents'][agent]['scores']]
        if review_date not in existing_dates:
            ledger['agents'][agent]['scores'].append({
                'date': review_date,
                'score': score
            })
            
            # Keep only last 14 days
            ledger['agents'][agent]['scores'] = ledger['agents'][agent]['scores'][-14:]
    
    # Update trends
    for agent, trend in parsed_review['grade_trends'].items():
        if agent in ledger['agents']:
            ledger['agents'][agent]['trend'] = trend
    
    # Mark issues as fixed
    for issue_id in parsed_review['issues_fixed']:
        for agent_name, agent_data in ledger['agents'].items():
            for issue in agent_data['issues']:
                if issue['id'] == issue_id and issue['status'] == 'open':
                    issue['status'] = 'fixed'
                    issue['fixed_on'] = review_date
                    agent_data['stats']['fixed'] += 1
                    
                    # Recalculate avg cycles to fix
                    fixed_issues = [i for i in agent_data['issues'] if i['status'] == 'fixed']
                    if fixed_issues:
                        avg = sum(i.get('cycles_open', 0) for i in fixed_issues) / len(fixed_issues)
                        agent_data['stats']['avg_cycles_to_fix'] = round(avg, 1)
                    break
    
    # Add new issues
    for issue_data in parsed_review['issues_raised']:
        agent = issue_data['agent']
        if agent not in ledger['agents']:
            continue
            
        # Generate issue ID
        agent_data = ledger['agents'][agent]
        prefix = get_agent_prefix(agent)
        existing_nums = [int(i['id'].split('-')[-1]) for i in agent_data['issues'] if '-' in i['id']]
        next_num = max(existing_nums, default=0) + 1
        issue_id = f"{prefix}-{next_num:03d}"
        
        new_issue = {
            'id': issue_id,
            'raised': issue_data['date_raised'],
            'description': issue_data['problem'],
            'severity': issue_data['severity'],
            'status': 'open',
            'cycles_open': 0,
            'notes': []
        }
        
        agent_data['issues'].append(new_issue)
        agent_data['stats']['total_issues'] += 1
        
        print(f"Added issue {issue_id}: {issue_data['problem']}")
    
    save_ledger(ledger)
    print(f"Updated improvement ledger from review: {parsed_review['source_file']}")

def get_agent_role(agent):
    """Get role description for agent."""
    roles = {
        'dino': 'Task Management & Project Coordination',
        'arnold': 'News & Intelligence',
        'betty': 'Content & Communications',
        'pebbles': 'Visual Design & UX',
        'mr-slate': 'Business Strategy & Operations',
        'bam-bam': 'Engineering & Development',
        'gazoo': 'QA & Process Improvement',
        'wilma': 'System Architecture & Orchestration'
    }
    return roles.get(agent, 'Unknown Role')

def get_agent_prefix(agent):
    """Get issue ID prefix for agent."""
    prefixes = {
        'dino': 'D', 'arnold': 'A', 'betty': 'B', 'pebbles': 'P',
        'mr-slate': 'S', 'bam-bam': 'BB', 'gazoo': 'G', 'wilma': 'W'
    }
    return prefixes.get(agent, 'X')

def main():
    """Main function."""
    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            # Parse all reviews
            if not os.path.exists(GAZOO_REVIEWS_DIR):
                print(f"Gazoo reviews directory not found: {GAZOO_REVIEWS_DIR}")
                sys.exit(1)
            
            review_files = list(Path(GAZOO_REVIEWS_DIR).glob("*.md"))
            for review_file in sorted(review_files):
                print(f"Parsing {review_file}")
                parse_gazoo_review(str(review_file))
        else:
            # Parse specific file
            filepath = sys.argv[1]
            if not filepath.startswith('/'):
                filepath = os.path.join(GAZOO_REVIEWS_DIR, filepath)
            parse_gazoo_review(filepath)
    else:
        # Parse today's review
        today = datetime.now().strftime("%Y-%m-%d")
        review_file = os.path.join(GAZOO_REVIEWS_DIR, f"{today}.md")
        
        if not os.path.exists(review_file):
            print(f"No review found for today: {review_file}")
            sys.exit(1)
        
        parse_gazoo_review(review_file)

if __name__ == "__main__":
    main()