#!/bin/bash
# start-stream.sh — Run this on Fred's Mac before streaming
# Starts the local dashboard server so Streamlabs can use localhost:8889

cd "$(dirname "$0")/.." || exit 1

echo "🎬 Starting HazeyData Stream Server..."
echo ""
echo "Dashboard URL: http://localhost:8889/stream-dashboard.html"
echo "API (wilma-server): http://wilma-server:8051/api"
echo ""
echo "Press Ctrl+C to stop."
echo ""

python3 dashboard/stream_server.py
