#!/bin/bash
# Install Dropbox Scheduler LaunchAgent
# This creates a daily job that starts Dropbox at 4:00 AM and stops it at 4:30 AM

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

# Ensure logs directory exists
mkdir -p "$REPO_ROOT/logs"

echo "Installing Dropbox scheduler..."

# Copy plist files to LaunchAgents directory
cp "$SCRIPT_DIR/com.hazeydata.dropbox-scheduler.plist" "$LAUNCH_AGENTS_DIR/"
cp "$SCRIPT_DIR/com.hazeydata.dropbox-stop.plist" "$LAUNCH_AGENTS_DIR/"

# Update paths in plist files to use absolute paths
sed -i '' "s|/Users/fredhazelton/theme-park-crowd-report|$REPO_ROOT|g" "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-scheduler.plist"
sed -i '' "s|/Users/fredhazelton/theme-park-crowd-report|$REPO_ROOT|g" "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-stop.plist"

# Load the launch agents
echo "Loading launch agents..."
launchctl load "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-scheduler.plist" 2>/dev/null || launchctl load -w "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-scheduler.plist"
launchctl load "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-stop.plist" 2>/dev/null || launchctl load -w "$LAUNCH_AGENTS_DIR/com.hazeydata.dropbox-stop.plist"

echo "✓ Dropbox scheduler installed successfully!"
echo ""
echo "Schedule:"
echo "  - Starts Dropbox: Daily at 4:00 AM"
echo "  - Stops Dropbox: Daily at 4:30 AM"
echo ""
echo "To check status:"
echo "  launchctl list | grep dropbox"
echo ""
echo "To uninstall:"
echo "  ./scripts/uninstall_dropbox_scheduler.sh"
