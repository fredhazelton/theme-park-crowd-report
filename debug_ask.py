#!/usr/bin/env python3
"""
Debug script to test ask_agent directly with the exact question that's failing
"""
import asyncio
import os
import sys
sys.path.append('/home/wilma/theme-park-crowd-report/tpcr-discord-bot')
from ask_agent import ask_agent

async def test_ask():
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("ERROR: No ANTHROPIC_API_KEY found")
        return
    
    question = "What is the predicted wait time at Space Mountain at noon on December 1, 2026"
    user_id = "debug_test"
    username = "debug"
    
    print(f"Testing question: {question}")
    print("Calling ask_agent...")
    
    try:
        answer = await ask_agent(question, user_id, api_key, username)
        print(f"Answer: {answer}")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ask())