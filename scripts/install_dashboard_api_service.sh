#!/bin/bash
#
# Install Dashboard API systemd service for Wilma
#
# Copies the service file to systemd user directory and enables it.
#
# Usage:
#   ./scripts/install_dashboard_api_service.sh    # Install, enable, and start
#   ./scripts/install_dashboard_api_service.sh --start-only   # Copy and start (don't enable on boot)
#   ./scripts/install_dashboard_api_service.sh --remove       # Stop and disable

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="dashboard-api.service"
SERVICE_FILE="$SCRIPT_DIR/dashboard-api-wilma.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
TARGET_SERVICE="$SYSTEMD_USER_DIR/$SERVICE_NAME"

case "${1:-}" in
    --remove)
        echo "Stopping and disabling dashboard-api..."
        systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
        rm -f "$TARGET_SERVICE"
        systemctl --user daemon-reload
        echo "Done. Service removed."
        exit 0
        ;;
    --start-only)
        echo "Copying service file to $TARGET_SERVICE..."
        mkdir -p "$SYSTEMD_USER_DIR"
        cp "$SERVICE_FILE" "$TARGET_SERVICE"
        systemctl --user daemon-reload
        echo "Starting dashboard-api..."
        systemctl --user start "$SERVICE_NAME"
        echo "Done. Service started (not enabled on boot)."
        echo "  Status: systemctl --user status $SERVICE_NAME"
        echo "  To enable on boot: systemctl --user enable $SERVICE_NAME"
        exit 0
        ;;
    --help|-h)
        echo "Usage: $0 [--start-only|--remove|--help]"
        echo ""
        echo "  (none)       Install, enable, and start (runs on boot)"
        echo "  --start-only Copy service file and start (don't enable on boot)"
        echo "  --remove     Stop, disable, and remove the service"
        exit 0
        ;;
    "")
        ;;
    *)
        echo "Unknown option: $1"
        echo "Use --help for usage information"
        exit 1
        ;;
esac

echo "Installing Dashboard API service for Wilma..."

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: Service file not found: $SERVICE_FILE"
    exit 1
fi

# Create systemd user directory if it doesn't exist
mkdir -p "$SYSTEMD_USER_DIR"

# Copy service file
echo "Copying service file to $TARGET_SERVICE..."
cp "$SERVICE_FILE" "$TARGET_SERVICE"

# Reload systemd
echo "Reloading systemd daemon..."
systemctl --user daemon-reload

# Enable service (starts on boot)
echo "Enabling service (starts on boot)..."
systemctl --user enable "$SERVICE_NAME"

# Start service
echo "Starting service..."
systemctl --user start "$SERVICE_NAME"

# Show status
echo ""
echo "Service installed and started!"
echo ""
echo "Status:"
systemctl --user status "$SERVICE_NAME" --no-pager || true

echo ""
echo "Useful commands:"
echo "  Check status:  systemctl --user status dashboard-api"
echo "  View logs:     journalctl --user -u dashboard-api -f"
echo "  Restart:       systemctl --user restart dashboard-api"
echo "  Stop:          systemctl --user stop dashboard-api"
echo ""
echo "API should be running on: http://wilma-server:8051"
