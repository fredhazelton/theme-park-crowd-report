# Stream Overlay Project
*Started: 2026-01-28*

## Goal
Build production-ready Twitch/YouTube streaming overlays for hazeydata.ai based on Figma designs.

## Scope

### Phase 1: Static Overlay + Controls (NOW)
- [ ] Export overlay components from Figma
- [ ] Build HTML/CSS for each overlay element:
  - TopBar (stream title + viewer count)
  - CameraFrame (with branding)
  - LowerThird ("CLEAR THE HAZE" + title)
  - SocialBar (platform icons)
  - GoalTracker (follower progress)
  - RecentEvent (latest follower)
- [ ] Build control panel to toggle elements
- [ ] Scene presets (Gaming, Tutorial, Just Chatting, All Features)
- [ ] Scene buttons (Main Stream, Starting Soon, BRB, Ending)

### Phase 2: Twitch Integration
- [ ] Get Twitch API credentials
- [ ] Real-time viewer count
- [ ] Follower goal tracking
- [ ] New follower alerts
- [ ] Chat integration (optional)

### Phase 3: YouTube Integration
- [ ] Get YouTube API credentials
- [ ] Adapt for YouTube Live
- [ ] Subscriber alerts
- [ ] Super Chat alerts (optional)

## Tech Stack
- **Overlay:** HTML/CSS/JS (browser source for OBS)
- **Control Panel:** Web-based, possibly with WebSocket for real-time control
- **APIs:** Twitch Helix API, YouTube Live Streaming API
- **Hosting:** GitHub Pages or local server

## Design Source
- Figma file: hazeydata.ai (JPWe8gZd4VPmAvnK6tLha1)
- Frame: "Twitch and YouTube Overlay Design"

## Color Palette (from Figma)
- Background: Dark navy (#040C1F)
- Primary text: Light blue-white (#E9F4FF)
- Accent: Deep red (#A60038)
- Secondary: Sky blue (#9DCBFF)

## To Get From Fred
- [ ] Twitch API Client ID + Secret
- [ ] Twitch channel name
- [ ] YouTube API key
- [ ] YouTube channel ID

---

*Status: Starting Phase 1*
