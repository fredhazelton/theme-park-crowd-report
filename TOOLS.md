# TOOLS.md - Local Notes

Skills define *how* tools work. This file is for *your* specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:
- Camera names and locations
- SSH hosts and aliases  
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras
- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH
- home-server → 192.168.1.100, user: admin

### TTS
- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

### Discord Forum Thread Creation
Clawdbot's `message action=thread-create` does NOT work for forum channels (missing `message.content` and `applied_tags` support). Use the helper script instead:

```bash
~/clawd/scripts/discord_forum_post.sh <channel_id> "<thread_name>" "<message_content>" "<tag_id1,tag_id2>"
```

**#briefing forum** (1482227277508120576) tags:
- 🎢 TPCR: `1482254047120719921`
- 🇨🇦 ACCORD: `1482254047120719922`
- 🚂 CDR: `1482254047120719923`
- 🏫 SSD: `1482263824793866272`
- 👥 Team: `1482254047636361297`
- 📊 Daily Report: `1482254047636361298`

**IMPORTANT:** When cron prompts say "use message action=thread-create with channelId=...", they should use this script instead. Update cron prompts accordingly.

**#links forum** (1482236997786534091) tags:
- 🎢 TPCR: `1482237033568145481`
- 🇨🇦 ACCORD: `1482237033568145482`
- 🚂 CDR: `1482237033568145483`
- 💰 Hazeydata: `1482237033568145484`
- 🔗 Tools: `1482237033568145485`
- 📊 Decks: `1482237033568145486`
- 📝 Docs: `1482237033568145487`
- 📦 Repos: `1482237033601826886`
- 🎨 Assets: `1482268718179422271`

**Note:** #links is a forum channel — use `discord_forum_post.sh` with tag IDs, or use the Discord API directly to add tags to threads.

### Discord Schedule Thread
Pinned schedule lives in #briefing thread ID `1483080808574222458`. **Always update this thread when cron schedule changes.**

### Live Schedule Status Board
Script: `~/clawd/scripts/update_schedule_status.py`
- Updates the pinned schedule thread with real-time status indicators as cron jobs complete
- Usage: `source ~/.clawdbot/.env && python3 ~/clawd/scripts/update_schedule_status.py '<job-key>' ok|error|skip|running`
- Reset: `python3 ~/clawd/scripts/update_schedule_status.py --reset`
- Auto-reset cron runs at 2:00 AM daily (before first work session at 2:30 AM)
- All cron jobs have a MANDATORY FINAL STEP to call this script
- Status emoji: ✅ ok · ❌ fail · ⏭️ skip · ⏳ running
- Job keys are defined in JOB_MAP in the script

---

Add whatever helps you do your job. This is your cheat sheet.
