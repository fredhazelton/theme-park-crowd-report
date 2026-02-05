#!/bin/bash
# Uninstall Dropbox Scheduler LaunchAgent

set -e

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "Uninstalling Dropbox scheduler..."

# Unload launch agents
launchctl unload "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-scheduler.plist" 2>/dev/null || true
launchctl unload "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-stop.plist" 2>/dev/null || true

# Remove plist files
rm -f "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-scheduler.plist"
rm -f "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-stop.plist"

echo "✓ Dropbox scheduler uninstalled successfully!"
