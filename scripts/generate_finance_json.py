#!/usr/bin/env python3
"""
Generate finance.json for Mission Control v3 Finance tab.

Outputs structured JSON with revenue, cost, and Stripe data.
Currently mostly static — can be enhanced to pull from Stripe API.

Usage:
    python scripts/generate_finance_json.py
"""

import json
import os
from datetime import datetime, timezone

def main():
    now = datetime.now(timezone.utc)

    output = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "mrr": "$0",
            "monthly_costs": "~$65",
            "phase": "Alpha",
            "subscribers": "0",
        },
        "revenue": {
            "items": [
                {"emoji": "🎢", "name": "TPCR Subscriptions", "value": "$0 (alpha)", "class": "free"},
                {"emoji": "📊", "name": "API Access", "value": "Not yet", "class": ""},
                {"emoji": "🎥", "name": "Twitch/YouTube", "value": "Not yet", "class": ""},
            ],
            "note": "🦕 Everything is free during alpha. Focus is on accuracy and growth before monetizing. Post-alpha: Free + Pro ($5/mo) tiers planned.",
        },
        "costs": {
            "items": [
                {"emoji": "🤖", "name": "Anthropic API (Claude)", "value": "~$30/mo"},
                {"emoji": "🧠", "name": "OpenAI API (Codex)", "value": "~$15/mo"},
                {"emoji": "☁️", "name": "Cloudflare (Pages + R2)", "value": "$0"},
                {"emoji": "🌐", "name": "Domain (hazeydata.ai)", "value": "~$2/mo"},
                {"emoji": "💬", "name": "Discord (free tier)", "value": "$0"},
                {"emoji": "🔧", "name": "GitHub (free tier)", "value": "$0"},
                {"emoji": "💾", "name": "B2 Cloud Storage", "value": "~$5/mo"},
                {"emoji": "🖥️", "name": "Server (wilma-server)", "value": "Owned"},
                {"emoji": "⚡", "name": "Electricity (server)", "value": "~$10/mo"},
            ],
            "total": "~$62/mo",
            "note": "Infrastructure is lean — self-hosted server with cloud backup. API costs are the main expense.",
        },
        "stripe": {
            "product_name": "TPCR Premium",
            "items": [
                {"emoji": "📦", "name": "Product", "value": "TPCR Premium"},
                {"emoji": "💲", "name": "Alpha Price", "value": "$0.00"},
                {"emoji": "🔗", "name": "Checkout", "value": "Live (Cloudflare)"},
                {"emoji": "🪝", "name": "Webhooks", "value": "Configured"},
                {"emoji": "🔑", "name": "Mode", "value": "Test Keys"},
            ],
            "note": "Stripe is fully wired up but using test keys. Switch to live keys when ready to charge. Checkout flow: hazeydata.ai → Cloudflare Pages Functions → Stripe.",
        },
        "infrastructure": {
            "items": [
                {"emoji": "🖥️", "name": "wilma-server", "value": "NVMe 1.8TB + Data 1.8TB"},
                {"emoji": "☁️", "name": "Cloudflare Pages", "value": "Free tier"},
                {"emoji": "💾", "name": "B2 Cloud Backup", "value": "Nightly 3am cron"},
                {"emoji": "📡", "name": "Dropbox (rclone)", "value": "Configured"},
                {"emoji": "🐍", "name": "Pipeline", "value": "Python + cron"},
            ],
            "note": "Self-hosted on dedicated hardware. B2 backup runs nightly at 3am. Cloudflare handles CDN + serverless functions.",
        },
    }

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    out_path = os.path.join(repo_root, "docs", "analytics-data", "finance.json")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Written finance.json to {out_path}")
    print(f"   MRR: {output['summary']['mrr']} | Costs: {output['summary']['monthly_costs']} | Phase: {output['summary']['phase']}")


if __name__ == "__main__":
    main()
