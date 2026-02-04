"""
Stream Dashboard Server

Serves the dashboard.html file and API endpoints.

Usage:
    python dashboard/stream_server.py
    # Dashboard: http://localhost:8052
    # API: http://localhost:8051 (run dashboard/api.py separately)
    
    Or use a single server:
    python dashboard/stream_server.py --combined
    # Everything on http://localhost:8052
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS

# We'll import API functions directly instead of the app
# to avoid circular imports

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ROOT / "docs" / "stream"

app = Flask(__name__, static_folder=str(DASHBOARD_DIR))
CORS(app)


@app.route("/")
def index():
    """Serve dashboard.html."""
    return send_from_directory(DASHBOARD_DIR, "dashboard.html")


@app.route("/<path:path>")
def serve_static(path):
    """Serve static files from dashboard directory."""
    return send_from_directory(DASHBOARD_DIR, path)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Stream Dashboard Server")
    parser.add_argument(
        "--combined",
        action="store_true",
        help="Run API and dashboard on same server (port 8052)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8052,
        help="Port to run dashboard on (default: 8052)",
    )
    args = parser.parse_args()
    
    if args.combined:
        # For combined mode, we'd need to restructure the API
        # For now, just serve the dashboard and note that API runs separately
        print(f"Starting dashboard server on http://localhost:{args.port}")
        print(f"  Dashboard: http://localhost:{args.port}/")
        print(f"  Note: Combined mode not yet implemented")
        print(f"  Run API separately: python dashboard/api.py")
    else:
        print(f"Starting dashboard server on http://localhost:{args.port}")
        print(f"  Dashboard: http://localhost:{args.port}/")
        print(f"  Note: API must be running separately on port 8051")
        print(f"  Run: python dashboard/api.py")
    
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
