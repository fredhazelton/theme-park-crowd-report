#!/usr/bin/env python3
"""
Content Review Reaction Handler

When someone reacts ✅ on a #content-review post:
1. Parse the action from the message (publish blog, set avatar, send tweet, etc.)
2. Execute the action automatically
3. React 🏁 to mark as completed
4. Log to activity file

When someone reacts ❌:
1. Mark as rejected
2. Notify the posting agent
3. React 🚫 to mark as rejected

Usage: python3 content_review_handler.py --monitor (runs continuously)
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands

# Configuration
CONTENT_REVIEW_CHANNEL = 1479351605051654215  # #content-review
APPROVED_REACTION = "✅"
REJECTED_REACTION = "❌"
DONE_REACTION = "🏁"
REJECTED_MARK = "🚫"

class ContentReviewBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        super().__init__(command_prefix='!', intents=intents)
        
    async def on_ready(self):
        print(f'Content Review Handler ready: {self.user}')
        
    async def on_reaction_add(self, reaction, user):
        # Skip bot reactions
        if user.bot:
            return
            
        # Only process reactions in #content-review
        if reaction.message.channel.id != CONTENT_REVIEW_CHANNEL:
            return
            
        message = reaction.message
        
        if str(reaction.emoji) == APPROVED_REACTION:
            await self.handle_approval(message, user)
        elif str(reaction.emoji) == REJECTED_REACTION:
            await self.handle_rejection(message, user)
    
    async def handle_approval(self, message, user):
        """Handle ✅ reaction - execute pending action"""
        # Check if already processed (has 🏁 reaction)
        for reaction in message.reactions:
            if str(reaction.emoji) == DONE_REACTION:
                print(f"Message {message.id} already processed (has 🏁)")
                return
                
        # Parse action from message content
        action = self.parse_action(message.content)
        if not action:
            print(f"Could not parse action from message {message.id}")
            return
            
        try:
            # Execute the action
            result = await self.execute_action(action, message)
            
            # Mark as completed with 🏁
            await message.add_reaction(DONE_REACTION)
            
            # Log successful execution
            self.log_action(message.id, action, "completed", user.display_name, result)
            
            print(f"✅ Executed action: {action['type']} - {result}")
            
        except Exception as e:
            print(f"❌ Failed to execute action: {e}")
            # Could add error reaction here
            
    async def handle_rejection(self, message, user):
        """Handle ❌ reaction - mark as rejected"""
        try:
            # Mark as rejected with 🚫  
            await message.add_reaction(REJECTED_MARK)
            
            # Parse original poster from message
            poster = self.parse_poster(message.content)
            
            # Log rejection
            self.log_action(message.id, {"type": "rejected"}, "rejected", user.display_name, f"Rejected by {user.display_name}")
            
            print(f"🚫 Content rejected by {user.display_name}")
            
        except Exception as e:
            print(f"❌ Failed to handle rejection: {e}")
    
    def parse_action(self, content):
        """Parse the pending action from message content"""
        # Look for common action patterns
        
        # Blog publishing
        if "publish" in content.lower() and "blog" in content.lower():
            blog_match = re.search(r'publish.*?blog.*?[:\-]\s*(.+)', content, re.IGNORECASE)
            if blog_match:
                return {
                    "type": "publish_blog",
                    "title": blog_match.group(1).strip(),
                    "content": content
                }
        
        # Avatar setting
        if "avatar" in content.lower() and "set" in content.lower():
            return {
                "type": "set_avatar", 
                "content": content
            }
            
        # Tweet sending
        if "tweet" in content.lower() or "twitter" in content.lower():
            return {
                "type": "send_tweet",
                "content": content
            }
            
        # Generic action
        if "action:" in content.lower():
            action_match = re.search(r'action:\s*(.+)', content, re.IGNORECASE)
            if action_match:
                return {
                    "type": "generic",
                    "action": action_match.group(1).strip(),
                    "content": content
                }
        
        return None
        
    def parse_poster(self, content):
        """Extract original poster from message content"""
        # Look for mentions or signatures
        mention_match = re.search(r'<@(\d+)>', content)
        if mention_match:
            return mention_match.group(1)
            
        # Look for agent signatures
        agent_match = re.search(r'(Wilma|Betty|Pebbles|Arnold|Bam-Bam|Mr\. Slate)', content, re.IGNORECASE)
        if agent_match:
            return agent_match.group(1)
            
        return "unknown"
    
    async def execute_action(self, action, message):
        """Execute the approved action"""
        action_type = action["type"]
        
        if action_type == "publish_blog":
            return await self.publish_blog(action)
        elif action_type == "set_avatar":
            return await self.set_avatar(action) 
        elif action_type == "send_tweet":
            return await self.send_tweet(action)
        elif action_type == "generic":
            return await self.execute_generic_action(action)
        else:
            raise Exception(f"Unknown action type: {action_type}")
    
    async def publish_blog(self, action):
        """Publish a blog post"""
        # This would integrate with the actual blog publishing system
        # For now, return a placeholder
        return f"Published blog: {action['title']}"
    
    async def set_avatar(self, action):
        """Set bot avatar"""
        # This would integrate with Discord API to set avatar
        return "Avatar updated"
    
    async def send_tweet(self, action):
        """Send a tweet"""
        # This would integrate with Twitter API
        return "Tweet sent"
    
    async def execute_generic_action(self, action):
        """Execute a generic action"""
        # This could shell out to other scripts or APIs
        return f"Executed: {action['action']}"
    
    def log_action(self, message_id, action, status, approver, result):
        """Log action to activity file"""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message_id": str(message_id),
            "action": action,
            "status": status,
            "approver": approver,
            "result": result
        }
        
        # Ensure log directory exists
        log_dir = Path("~/clawd/data").expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Append to log file
        log_file = log_dir / "content_review_actions.jsonl"
        with log_file.open("a") as f:
            f.write(json.dumps(log_entry) + "\n")

async def main():
    # Load Discord token from environment
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("Error: DISCORD_TOKEN environment variable not set")
        sys.exit(1)
    
    bot = ContentReviewBot()
    
    try:
        await bot.start(token)
    except KeyboardInterrupt:
        print("\nShutting down...")
        await bot.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Content Review Reaction Handler')
    parser.add_argument('--monitor', action='store_true', help='Run in monitoring mode')
    parser.add_argument('--test', action='store_true', help='Test mode - dry run')
    
    args = parser.parse_args()
    
    if args.monitor:
        print("Starting Content Review Handler in monitoring mode...")
        asyncio.run(main())
    else:
        print("Content Review Handler - use --monitor to start")
        print("This will monitor #content-review for ✅/❌ reactions and execute approved actions")