# Setting Up Dashboard on Wilma Server

The dashboard needs to be accessible at `http://wilma-server:8888/stream-dashboard.html`

## Current Setup

- **Server**: Python http.server on port 8888
- **Working Directory**: `/home/wilma/clawd-anthropic/streaming/`
- **Files served from**: That directory

## Steps to Deploy

### 1. Copy Dashboard File

Copy the dashboard HTML to the streaming directory:

```bash
cp /home/wilma/theme-park-crowd-report/docs/stream/dashboard.html \
   /home/wilma/clawd-anthropic/streaming/stream-dashboard.html
```

Or create a symlink (so updates are automatic):

```bash
ln -s /home/wilma/theme-park-crowd-report/docs/stream/dashboard.html \
      /home/wilma/clawd-anthropic/streaming/stream-dashboard.html
```

### 2. Start the API Server

The dashboard needs the API running. Create a systemd service or run it manually:

**Option A: Manual (for testing)**
```bash
cd /home/wilma/theme-park-crowd-report
source .venv/bin/activate
python dashboard/api.py
```

**Option B: Systemd Service (recommended)**

Use the install script:

```bash
cd /home/wilma/theme-park-crowd-report
bash scripts/install_dashboard_api_service.sh
```

This will:
- Copy the service file to `~/.config/systemd/user/`
- Enable it to start on boot
- Start it immediately

The service file is at `scripts/dashboard-api-wilma.service` if you need to customize it.

### 3. Verify Access

- **Dashboard**: http://wilma-server:8888/stream-dashboard.html
- **API**: http://wilma-server:8051/api/health

### 4. Check API Connection

The dashboard will automatically detect it's running on `wilma-server` and use `http://wilma-server:8051/api` for the API base URL.

If you need to change the API URL, edit the `API_BASE` constant in `dashboard.html` (around line 610).

## Troubleshooting

### Dashboard loads but shows "Loading..." forever
- Check API is running: `curl http://wilma-server:8051/api/health`
- Check browser console for CORS errors
- Verify API can access pipeline data (check `output_base` in config)

### 404 on stream-dashboard.html
- Verify file exists: `ls -la /home/wilma/clawd-anthropic/streaming/stream-dashboard.html`
- Check server is running: `systemctl --user status chat-server` (or whatever serves port 8888)
- Restart server if needed

### API errors
- Check API logs: `journalctl --user -u dashboard-api -f`
- Verify output_base path in config
- Ensure WTI data exists: `ls /home/wilma/hazeydata/pipeline/wti/wti.parquet`
