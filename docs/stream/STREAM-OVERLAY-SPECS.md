# Stream Overlay Specs — Hazeydata.ai

*Last Updated: 2026-02-03 00:49 EST*
*Finalized after extensive alignment testing with Fred*

---

## 📺 Canvas Size
- **Resolution:** 1920 × 1080 (Full HD)
- **All positions are absolute from top-left origin**

---

## 🎯 Right-Side Boxes Layout

All 4 boxes share:
- **Width:** 320px
- **Right edge:** 20px from screen edge
- **X position (Streamlabs):** 1580 (1920 - 320 - 20)
- **Gap between boxes:** ~10px

### Box 1: Goal Tracker (FOLLOWER_GOAL)
| Property | Value |
|----------|-------|
| Top | 77px |
| Height | 120px |
| Bottom edge | 197px |

### Box 2: Ad Rotator (FRESH DATA / rotating content)
| Property | Value |
|----------|-------|
| Top | 207px |
| Height | 115px |
| Bottom edge | 322px |

### Box 3: Chat Container (CHAT_FEED / Fred & Wilma Chat)
| Property | Value |
|----------|-------|
| Top | 309px |
| Height | 544px (1080 - 309 - 227) |
| Bottom | 227px from screen bottom |
| Bottom edge | 853px |

### Box 4: Camera Frame (CAM-01 // PRIMARY)
| Property | Value |
|----------|-------|
| Bottom | 10px |
| Height | 207px (27px header + 180px 16:9 content) |
| Top edge | 863px |

---

## 🗨️ Fred & Wilma Chat Overlay

### File Locations
- **Source:** `/home/wilma/clawd-anthropic/streaming/chat-overlay.html`
- **URL:** `http://wilma-server:8888/chat-overlay.html`
- **Chat data:** `/home/wilma/clawd-anthropic/streaming/chat.json`

### CSS Dimensions
| Property | Value | Notes |
|----------|-------|-------|
| Width | 320px | Matches box 3 |
| Height | 540px | Slightly smaller than container for border visibility |
| Border | 1px sides, 2px bottom | Bottom border thicker for visibility |
| Border color | rgba(74, 144, 164, 0.5-0.7) | Cyan glow |
| Background | rgba(10, 22, 40, 0.92) | Semi-transparent navy |
| Border radius | 4px | |

### Streamlabs Browser Source Settings
| Setting | Value |
|---------|-------|
| URL | `http://wilma-server:8888/chat-overlay.html` |
| X | 1580 |
| Y | 309 |
| Width | 320 |
| Height | 544 |
| Crop | All zeros |

### Idle Behavior
- **Default timeout:** 30 seconds
- **Customizable:** Add `?idle=45` to URL for 45 seconds
- **Behavior:** Fades to fully transparent (opacity: 0)
- **Reactivates:** On new message or typing indicator

---

## 📹 Webcam Positioning

### Camera Frame (overlay element)
| Setting | Value |
|---------|-------|
| X | 1580 |
| Y | 863 |
| Width | 320 |
| Height | 207 |

### Actual Webcam Source (inside frame)
| Setting | Value |
|---------|-------|
| X | 1580 |
| Y | 890 (863 + 27px header) |
| Width | 320 |
| Height | 180 (16:9 aspect ratio) |

---

## 🎨 Brand Colors (for reference)

| Color | Hex | Usage |
|-------|-----|-------|
| Navy (bg) | #0a1628 / rgba(10,22,40) | Backgrounds |
| Cyan | #4a90a4 / rgba(74,144,164) | Borders, accents |
| Text primary | #e9f4ff | Main text |
| Red accent | #A60038 | Wilma messages |
| Green | #00ff88 | Live indicators |

---

## 📁 File Structure

```
~/clawd-anthropic/streaming/
├── chat-overlay.html      ← Fred & Wilma chat (ACTIVE)
├── chat.json              ← Chat messages data
├── chat-server.service    ← Systemd service config
└── STREAM-OVERLAY-SPECS.md ← This file

~/theme-park-crowd-report/docs/stream/
├── main-dashboard.html    ← Main overlay with all elements
├── fred-wilma-chat.html   ← Backup copy (GitHub Pages)
├── dashboard.html         ← iOS-style dashboard
├── starting-soon.html     ← Pre-stream screen
├── be-right-back.html     ← BRB screen
├── stream-ending.html     ← End screen
└── tron-data.json         ← Live wait time data
```

---

## 🖥️ Chat Server

### Service Status
```bash
systemctl --user status chat-server
```

### Restart
```bash
systemctl --user restart chat-server
```

### Service File
`~/.config/systemd/user/chat-server.service`

### Server Details
- **Port:** 8888
- **Working directory:** `/home/wilma/clawd-anthropic/streaming`
- **Type:** Python http.server
- **Auto-restart:** Yes

---

## 📋 Streamlabs Scene: "Live"

### Sources (bottom to top)
1. **Brio Webcam** — Physical camera, positioned at X=1580, Y=890
2. **Live Overlay** — Main dashboard HTML, X=0, Y=0, 1920×1080
3. **Telegram Chat** — Fred & Wilma chat overlay, X=1580, Y=309, 320×544

---

## ⚠️ Troubleshooting

### Chat not updating?
1. Check chat-server is running: `systemctl --user status chat-server`
2. Verify chat.json exists: `cat ~/clawd-anthropic/streaming/chat.json`
3. Refresh browser source in Streamlabs (right-click → Refresh)

### Border cut off?
- Ensure Streamlabs source height is 544px
- CSS height is 540px (4px buffer for border)

### Wrong file loading?
- Main server runs from `~/clawd-anthropic/streaming/`
- NOT from `~/theme-park-crowd-report/docs/stream/`
- URL should be `http://wilma-server:8888/chat-overlay.html`

---

*Document created by Wilma after late-night alignment session with Fred 🦴*
