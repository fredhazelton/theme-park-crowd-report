# 🖥️ Mac Mini Setup Checklist
> **Arrival:** Tuesday, Feb 4 (2 days!)
> **Goal:** Stream-ready for Twitch + YouTube cross-platform

---

## 📦 Day 1: Unboxing & Basic Setup

### Hardware
- [ ] Unbox Mac Mini, check all cables
- [ ] Connect to monitor, keyboard, mouse
- [ ] Connect ethernet (faster than WiFi for streaming)
- [ ] Power on, complete macOS setup

### macOS Basics
- [ ] Sign into Apple ID
- [ ] Run Software Update
- [ ] Set computer name (e.g., "hazey-mac-mini")
- [ ] Enable Remote Login (System Settings → General → Sharing)
- [ ] Set up Time Machine backup (optional but smart)

---

## 🎬 Day 1-2: Streaming Software

### Streamlabs Desktop
- [ ] Download from [streamlabs.com](https://streamlabs.com)
- [ ] Install and sign in with Twitch account
- [ ] Import overlay scenes from GitHub Pages
- [ ] Test scene switching

### Connect Platforms
- [ ] **Twitch:** Should auto-connect with Streamlabs login
- [ ] **YouTube:** 
  - [ ] Go to [youtube.com/live_dashboard](https://youtube.com/live_dashboard)
  - [ ] Enable live streaming (may require 24hr wait if first time)
  - [ ] Verify phone number if prompted
  - [ ] Connect YouTube account in Streamlabs

### Multistreaming Setup
**Option A: Streamlabs Ultra ($19/mo)**
- [ ] Upgrade to Streamlabs Ultra
- [ ] Enable Multistream in settings
- [ ] Add YouTube as second destination
- [ ] Test dual output

**Option B: Restream.io (Free)**
- [ ] Create account at [restream.io](https://restream.io)
- [ ] Connect Twitch channel
- [ ] Connect YouTube channel
- [ ] Get RTMP URL and stream key
- [ ] Configure Streamlabs to stream to Restream

---

## 🎨 Overlay Setup

### Import from GitHub Pages
Stream assets: `https://hazeydata.github.io/theme-park-crowd-report/stream/`

- [ ] **Starting Soon** scene → `starting-soon.html`
- [ ] **Main Stream** scene → `dashboard.html` (or custom)
- [ ] **BRB** scene → `brb.html`
- [ ] **Ending** scene → `ending.html`
- [ ] **Just Chatting** scene → minimal overlay
- [ ] **Full Screen** scene → no overlay (for demos)

### Browser Sources in Streamlabs
For each overlay:
1. Add Source → Browser Source
2. URL: `https://hazeydata.github.io/theme-park-crowd-report/stream/[scene].html`
3. Width: 1920, Height: 1080
4. ✅ Refresh browser when scene becomes active

---

## 🎤 Audio/Video

### Camera
- [ ] Connect webcam or capture device
- [ ] Test in Streamlabs
- [ ] Adjust positioning, lighting
- [ ] Create "camera on" and "camera off" scenes

### Microphone
- [ ] Connect mic (USB or interface)
- [ ] Set as input in Streamlabs
- [ ] Add noise suppression filter
- [ ] Add compressor filter (optional)
- [ ] Test levels (aim for -12 to -6 dB peaks)

### Desktop Audio
- [ ] Capture desktop audio for music/sounds
- [ ] Set up audio ducking if needed (music quieter when talking)

---

## 🧪 Test Streams

### Private Test (Twitch)
- [ ] Set stream to "Not Live" or use Twitch Inspector
- [ ] Run 5-minute test
- [ ] Check video quality, audio sync
- [ ] Test scene transitions
- [ ] Verify overlays load correctly

### Private Test (YouTube)
- [ ] Create unlisted/private stream
- [ ] Run 5-minute test
- [ ] Verify stream key works
- [ ] Check latency settings

### Multistream Test
- [ ] Test both platforms simultaneously
- [ ] Monitor CPU/GPU usage
- [ ] Check for dropped frames
- [ ] Verify audio on both platforms

---

## 📊 Stream Settings (Recommended)

### Video
- **Resolution:** 1920x1080
- **FPS:** 30 (or 60 if Mac handles it)
- **Encoder:** Apple VT H264 Hardware Encoder

### Streaming
- **Bitrate:** 4500-6000 kbps (for 1080p30)
- **Keyframe Interval:** 2 seconds
- **Audio Bitrate:** 160 kbps

---

## 🚀 First Stream Prep

### Content
- [ ] Plan first stream topic (e.g., "Building the dashboard LIVE with Wilma!")
- [ ] Create stream title and description
- [ ] Design thumbnail (Pebbles?)
- [ ] Set category (Software & Game Dev / Science & Tech)

### Promotion
- [ ] Announce on Twitter/X
- [ ] Set stream schedule
- [ ] Create "going live" notification

### Day-of Checklist
- [ ] Close unnecessary apps
- [ ] Disable notifications (Do Not Disturb)
- [ ] Have water nearby
- [ ] Test everything one more time
- [ ] Deep breath... GO LIVE! 🎬

---

## 🔗 Quick Links

| Resource | URL |
|----------|-----|
| Stream Overlays | [GitHub Pages](https://hazeydata.github.io/theme-park-crowd-report/stream/) |
| Streamlabs | [streamlabs.com](https://streamlabs.com) |
| Restream | [restream.io](https://restream.io) |
| Twitch Dashboard | [dashboard.twitch.tv](https://dashboard.twitch.tv) |
| YouTube Studio | [studio.youtube.com](https://studio.youtube.com) |

---

## 🦴 Wilma's Role During Streams

I can help with:
- Real-time park data lookups
- Answering chat questions (if integrated)
- Monitoring pipeline status
- Generating content on the fly

Let's make the first stream awesome! 🎉
