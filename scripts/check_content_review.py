#!/usr/bin/env python3
"""
Simple Content Review Checker

Checks #content-review for messages with ✅ but no 🏁
Executes approved actions and marks them complete

Run via cron every 5 minutes:
*/5 * * * * cd /home/wilma/clawd && python3 scripts/check_content_review.py

"""

import os
import sys
import json
import re
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, '/home/wilma/clawd')

def check_content_review():
    """Check for approved content that needs action"""
    # This would use Discord API to check reactions
    # For now, create a simple file-based system
    
    log_file = "/home/wilma/clawd/data/content_review_queue.json"
    
    if not os.path.exists(log_file):
        return
    
    with open(log_file, 'r') as f:
        queue = json.load(f)
    
    executed = []
    
    for item in queue:
        if item.get('status') == 'approved' and not item.get('executed'):
            try:
                result = execute_action(item)
                item['executed'] = True
                item['executed_at'] = datetime.now().isoformat()
                item['result'] = result
                executed.append(item)
                print(f"✅ Executed: {item.get('action', 'Unknown action')}")
            except Exception as e:
                print(f"❌ Failed to execute {item.get('action')}: {e}")
    
    # Save updated queue
    with open(log_file, 'w') as f:
        json.dump(queue, f, indent=2)
    
    return executed

def execute_action(item):
    """Execute a single approved action"""
    action_type = item.get('action_type', 'unknown')
    
    if action_type == 'publish_blog':
        return publish_blog(item)
    elif action_type == 'send_tweet':
        return send_tweet(item) 
    elif action_type == 'set_avatar':
        return set_avatar(item)
    else:
        return f"Generic action: {item.get('action', 'Unknown')}"

def publish_blog(item):
    """Publish a blog post"""
    # Placeholder - would integrate with actual blog system
    title = item.get('title', 'Untitled')
    return f"Published blog post: {title}"

def send_tweet(item):
    """Send a tweet"""
    # Placeholder - would use Twitter API
    content = item.get('content', '')[:100]
    return f"Sent tweet: {content}..."

def set_avatar(item):
    """Set Discord avatar"""
    # Placeholder - would use Discord API
    return "Updated Discord avatar"

if __name__ == "__main__":
    executed = check_content_review()
    
    if executed:
        print(f"Processed {len(executed)} approved actions")
    else:
        print("No pending approved actions")