# HEARTBEAT.md

## Content Review Check
- Scan #content-review (channel:1479351605051654215) for posts with ✅ reactions that haven't been actioned
- If found: execute the pending action (publish, set avatar, send tweet, etc.)

## 🔴 #1 PRIORITY: LLM Scraper Monitor
- Check if llm_scraper.py is running: `ps aux | grep llm_scraper | grep -v grep`
- If running: `tail -10 ~/theme-park-crowd-report/data/school_schedules/llm_scraper.log` — note progress
- If stopped: check exit status immediately. Report to Fred in #school-schedules. Consider restarting with `cd ~/theme-park-crowd-report/data/school_schedules && screen -dmS scraper bash -c 'export BRAVE_SEARCH_API_KEY="BSAEB_N4ZkM3WOQN6bokdPKGkL6HWuN"; cd /home/wilma/theme-park-crowd-report/data/school_schedules; exec python3 -u llm_scraper.py --resume >> llm_scraper.log 2>&1'`
- Quick stats: `python3 -c "import json; d=json.load(open('llm_scraper_results.json')); found=sum(1 for r in d.values() if r.get('status')=='found'); print(f'{found} found / {len(d)} processed ({found/len(d)*100:.1f}%)')"`
- Started: 2026-03-14 ~16:00, ~6,685 districts in queue, ~69.5% hit rate
- Alert Fred immediately if it crashes or stalls

## Rotation (cycle through these)
- Check wilma@hazeydata.ai inbox (~twice daily, morning + afternoon)
- Disk space check: `df -h / /mnt/data` — warn at 85%, alert at 90% (see orchestration-rules.md)
- Pipeline quick check: `ls ~/hazeydata/pipeline/logs/v3_$(date +%Y-%m-%d).log 2>/dev/null && tail -3 ~/hazeydata/pipeline/logs/v3_$(date +%Y-%m-%d).log || echo "NO PIPELINE LOG TODAY"` — only if accuracy briefing didn't already cover it today
