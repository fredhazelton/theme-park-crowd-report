#!/bin/bash
# Dropbox Scheduler
# Starts Dropbox at 4:00 AM and stops it at 4:30 AM daily

ACTION="$1"

case "$ACTION" in
    start)
        echo "$(date): Starting Dropbox..."
        open -a Dropbox
        ;;
    stop)
        echo "$(date): Stopping Dropbox..."
        # Try graceful quit first
        osascript -e 'tell application "Dropbox" to quit' 2>/dev/null
        # If that doesn't work, force kill after a short delay
        sleep 2
        pkill -x Dropbox 2>/dev/null || killall Dropbox 2>/dev/null
        ;;
    *)
        echo "Usage: $0 {start|stop}"
        exit 1
        ;;
esac

exit 0
