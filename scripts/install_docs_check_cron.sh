#!/bin/bash
# install_docs_check_cron.sh - Install hourly docs-check job (survives reboot)
#
# Adds a cron job that runs check_docs_for_instructions.sh every hour.
# Cron daemon starts on boot, so the job will run after reboot.
#
# Usage:
#   ./scripts/install_docs_check_cron.sh         # Install
#   ./scripts/install_docs_check_cron.sh --remove   # Remove
#   ./scripts/install_docs_check_cron.sh --show     # Preview

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PROJECT_ROOT="$(get_project_root)"
OUTPUT_BASE="$(get_output_base "$PROJECT_ROOT")"
LOGS_DIR="$OUTPUT_BASE/logs"

# Fallback if output_base not available
if [[ ! -d "$LOGS_DIR" ]]; then
    LOGS_DIR="$PROJECT_ROOT/logs"
    mkdir -p "$LOGS_DIR" 2>/dev/null || true
fi

CRON_MARKER="# docs-check-hourly"
CRON_ENTRY="0 * * * * export PATH=\"\$HOME/.local/bin:\$PATH\" && cd $PROJECT_ROOT && $SCRIPT_DIR/check_docs_for_instructions.sh >> \"$LOGS_DIR/docs_check.log\" 2>&1 $CRON_MARKER"

show_cron() {
    echo "=== Docs check cron entry (hourly, survives reboot) ==="
    echo ""
    echo "$CRON_ENTRY"
    echo ""
    echo "Runs: check_docs_for_instructions.sh at minute 0 of every hour"
    echo "Log:  $LOGS_DIR/docs_check.log"
    echo ""
}

install_cron() {
    echo "Installing hourly docs-check cron job..."
    mkdir -p "$LOGS_DIR" 2>/dev/null || true
    (crontab -l 2>/dev/null | grep -v "$CRON_MARKER" || true; echo "# Hourly: check WILMA-BAMBAM.md for new instructions"; echo "$CRON_ENTRY") | crontab -
    echo "Done. Job runs every hour at :00 and survives reboot."
    echo "View: crontab -l"
    echo "Log:  tail -f $LOGS_DIR/docs_check.log"
}

remove_cron() {
    echo "Removing docs-check cron job..."
    crontab -l 2>/dev/null | grep -v "$CRON_MARKER" | crontab - || true
    echo "Done."
}

case "${1:-}" in
    --show)
        show_cron
        ;;
    --remove)
        remove_cron
        ;;
    --help|-h)
        echo "Usage: $0 [--show|--remove|--help]"
        echo ""
        echo "  (none)    Install hourly docs-check cron job"
        echo "  --show    Preview what would be installed"
        echo "  --remove  Remove the cron job"
        exit 0
        ;;
    "")
        install_cron
        ;;
    *)
        echo "Unknown option: $1"
        exit 1
        ;;
esac
