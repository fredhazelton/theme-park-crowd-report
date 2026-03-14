# HEARTBEAT.md

## Content Review Check
- Scan #content-review (channel:1479351605051654215) for posts with ✅ reactions that haven't been actioned
- If found: execute the pending action (publish, set avatar, send tweet, etc.)

## School Schedules Scraper Monitor
- Check if brave_scraper.py is running: `ps aux | grep brave_scraper | grep -v grep`
- If running: `tail -5 ~/theme-park-crowd-report/data/school_schedules/brave_scraper.log` — note progress
- If stopped: check exit status, report final stats, consider restarting
- Target: 95%+ confirmed coverage (currently 45.8%)

## Dropbox Move Monitor
- Check if the TouringPlans Dropbox move is still running: `ps aux | grep "mv.*Dropbox" | grep -v grep`
- If done: run `df -h /` and report the freed space. Clean up .dropbox and .dropbox-dist in /home/fred/

## Rotation (cycle through these)
- Check wilma@hazeydata.ai inbox (~twice daily, morning + afternoon)
- Disk space check: `df -h / /mnt/data` — warn at 85%, alert at 90% (see orchestration-rules.md)
- Pipeline quick check: `systemctl --user is-active pipeline-daily.service` — only if accuracy briefing didn't already cover it today
