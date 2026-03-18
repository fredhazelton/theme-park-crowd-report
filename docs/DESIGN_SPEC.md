# Crowd Card — Design Spec

*Apple Weather-style WTI card for Theme Park Crowd Report*  
*Last updated: 2026-03-18*

---

## Element Naming Convention

### Top Section
| Element | Description |
|---------|-------------|
| **WATERMARK** | "WAIT TIME INDEX" at ~28% opacity, letterspaced, top of card |
| **PARK NAME** | Current park name (e.g., "Magic Kingdom") |
| **WTI VALUE** | Current park-level average predicted actual wait time — the "right now" value aligned with the NOW INDICATOR. When park is closed: reverts to daily average observed WTI. |
| **CROWD LEVEL** | Categorical descriptor based on daily park-level WTI (e.g., "Low Crowds", "Moderate Crowds") |
| **DAILY RANGE** | L:H — intraday min/max of park-level WTI predicted. Fallback to p5/p95 if min ≈ 0. |

### Info Card (Glass)
| Element | Description |
|---------|-------------|
| **INFO CARD** | Glassmorphism container (backdrop-filter blur, dark tint, NOT white) |
| **CROWD SUMMARY** | Generated text: crowd description, peak time, special events/hours (Early Entry ☀️, party nights 🎉, extra magic hours 🌙) |
| **DIVIDER** | Thin separator between CROWD SUMMARY and HOUR-BY-HOUR BAR |
| **EARLY ENTRY PILL** | ☀️ emoji pill, left of bar. Taller than bar (extends above/below). No divider between pill and bar. No hour label underneath. |
| **HOUR-BY-HOUR BAR** | Continuous Benedictus spectrum showing park-level WTI from park open → park close. Rendered from real 5-min intraday curve data. |
| **NOW INDICATOR** | White triangle above the bar. Only visible when current time is within park operating hours. During early entry: hovers over the ☀️ pill. During evening event: hovers over the 🎉 pill. |
| **TIME LABELS** | Park open hour (bold, left-aligned with bar start) → distributed labels → Park close hour (bold, right-aligned with bar end). No labels under pills. |
| **AFTER-HOURS PILL** | 🌙 (extra magic hours) or 🎉 (evening event), right of bar. Same sizing as early entry pill. |

### Forecast Card (Glass)
| Element | Description |
|---------|-------------|
| **FORECAST CARD** | Second glassmorphism container |
| **FORECAST HEADER** | "📅 7-Day Crowd Forecast" |
| **DAY NAME** | Day of week (or "Today") |
| **CROWD DOT** | Color-coded dot, mapped to the daily WTI value for that park-day (same value used in Discord/everywhere else) |
| **LOW WTI** | Left value of range (same methodology as DAILY RANGE: intraday min, fallback p5) |
| **RANGE BAR** | Benedictus gradient bar showing the intraday WTI range for that day |
| **HIGH WTI** | Right value of range (same methodology: intraday max, fallback p95) |
| **NOW DOT** | White dot on Today's row showing current WTI position within the daily range. Only visible during park operating hours. |

### Footer
| Element | Description |
|---------|-------------|
| **FOOTER** | "hazeydata.ai • Theme Park Crowd Report" |

---

## Color Palette — Benedictus Scale

Blue → White → Pink → Red

| Level | Hex | RGB |
|-------|---------|-----|
| 1 (Empty) | `#0A2F8F` | 10, 47, 143 |
| 2 | `#305FD1` | 48, 95, 209 |
| 3 | `#5A96EA` | 90, 150, 234 |
| 4 | `#9BC4F2` | 155, 196, 242 |
| 5 | `#C1DDFC` | 193, 221, 252 |
| 6 (Neutral) | `#E9F4FF` | 233, 244, 255 |
| 7 | `#FFE0E9` | 255, 224, 233 |
| 8 | `#FFB1C9` | 255, 177, 201 |
| 9 | `#EB427B` | 235, 66, 123 |
| 10 (Packed) | `#A60038` | 166, 0, 56 |

Color mapping: WTI value → normalized to 0-1 range (where ~50+ WTI = fully red) → interpolated through the Benedictus scale.

---

## Data Methodology

### WTI VALUE (the big number)
- **When park is open:** Current park-level average predicted actual wait time at the current time slot. This is the mean of `predicted_actual` across all operating entities at the current 5-min slot.
- **When park is closed:** Daily average observed WTI for that day (or predicted if no observations yet).

### DAILY RANGE (L:H)
- Intraday min and max of the park-level WTI curve (average across entities per time slot).
- If min ≈ 0 (edge case): use 5th and 95th percentile instead.
- Range covers park open → park close only.

### CROWD LEVEL
Categorical label based on the current WTI VALUE:
- ≤10: "Very Low Crowds"
- ≤18: "Low Crowds"  
- ≤28: "Moderate Crowds"
- ≤40: "High Crowds"
- ≤55: "Very High Crowds"
- >55: "Extreme Crowds"

*(Thresholds TBD — may need calibration per park)*

### CROWD SUMMARY
Generated text including:
- Crowd description for the day
- Peak time (e.g., "Peak around 2PM")
- Special hours: "Early Entry ☀️ available"
- Events: party nights, extra magic hours
- Any notable conditions

### HOUR-BY-HOUR BAR
- 5-minute resolution park-level WTI data, rendered as a continuous Benedictus gradient.
- Spans from park official open → park official close.
- Extended hours shown as emoji pills outside the bar.

### FORECAST ROWS
- Same L:H methodology as DAILY RANGE (intraday min/max or p5/p95).
- CROWD DOT color = daily WTI value for that day, mapped through Benedictus.
- RANGE BAR = Benedictus gradient from low to high.
- NOW DOT = current WTI position within range (Today only, park open only).

---

## State Rules

### Park is open (current time within operating hours)
- WTI VALUE = current park-level WTI
- NOW INDICATOR (triangle) = visible, positioned at current time
- NOW DOT (forecast) = visible on Today's row
- CROWD DOT = visible on all rows
- Everything displays as designed

### Before park opens today
- WTI VALUE = daily predicted WTI (the all-day average)
- NOW INDICATOR = hidden
- NOW DOT = hidden
- CROWD DOT = hidden
- All other elements display normally (predictions for the day)

### After park closes tonight
- WTI VALUE = daily average observed WTI
- NOW INDICATOR = hidden
- NOW DOT = hidden  
- CROWD DOT = hidden
- Card reverts to "daily summary" view

### During Early Entry (before official open)
- NOW INDICATOR hovers over the ☀️ EARLY ENTRY PILL
- WTI VALUE = current WTI (early entry crowds are measurable)

### During Evening Event (after official close)
- NOW INDICATOR hovers over the 🎉 or 🌙 pill
- WTI VALUE = current WTI during event

---

## Data Sources

| Source | Path | Contents |
|--------|------|----------|
| Daily WTI | `wti/wti.parquet` | park_code, park_date, wti, n_entities, source |
| Intraday curves | `curves/forecast_parquet/all_forecasts.parquet` | entity_code, park_date, time_slot (5-min), predicted_actual |
| Park hours | `dimension_tables/dimparkhours.csv` | open/close, EMH morning/evening, party nights |
| Entity list | `dimension_tables/dimentity.csv` | entity codes, has_posted flag |
| **Historical WTI ranges** | `wti/wti.parquet` (aggregated) | **MIN/MAX WTI per park across all historical data for global range bars** |

All paths relative to `/home/wilma/hazeydata/pipeline/`.

---

## Design Principles

1. **Minimize words/letters** — use emoji (☀️🌙🎉) over text labels
2. **Glassmorphism** — dark tinted glass, never white backgrounds
3. **Breathing room** — generous spacing in the top section
4. **Bold open/close** — park opening and closing hours are bold + higher opacity
5. **Benedictus everywhere** — consistent color language across all elements
6. **Current value first** — big number = right now, like the Weather app

---

## Technical Stack

- **Renderer:** HTML/CSS/JS (responsive, mobile-first 390px viewport)
- **Data generator:** Python (queries pipeline parquet files, outputs JSON per park)
- **Screenshot:** Puppeteer + Chromium headless (for social/Discord sharing)
- **Hosting:** Static page on hazeydata.ai
- **Fonts:** Inter (weights: 200, 300, 400, 500, 600, 700)

---

## Above vs Below the Fold

**Above the fold = WTI only.** Pure, objective, verifiable metric.  
**Below the fold = creative metrics.** Crowd density, ride data, events, weather, comparisons.

---

## Below-the-Fold Sections

All sections use glassmorphism cards matching the Info Card and Forecast Card styling. Mix of full-width and 2-column layouts (see Apple Weather reference screenshots).

### 🏰 CROWD DENSITY (full-width, core section)
- **Expert-curated + crowdsourced** 1-10 rating
- Starts with Fred's expert baseline: f(WTI, park, day_of_week, season, events)
- **User slider/buttons** allow guests to adjust up/down and submit
- Display = weighted average of all user submissions
- **Statistical safeguards:**
  - Trimmed mean (drop top/bottom 10%)
  - Recency weighting (recent submissions matter more)
  - Reputation weighting (consistent users get more influence)
  - Anomaly detection (anti-gaming)
  - Bayesian prior from expert baseline (pulls toward expert rating when few submissions, converges to crowd consensus as N grows)
- **Layout:** Big number (7), "out of 10", Benedictus bar with indicator, description text, slider/submit UI
- **Key insight:** MK at WTI 15 might "feel" like 7/10. EPCOT Food & Wine weekends = 9/10 regardless of WTI. This captures what WTI can't: walkway congestion, restaurant waits, elbow room, event crowds.

### 🎢 RIDE SNAPSHOT (full-width)
- Top 5 shortest waits + Top 5 longest waits right now
- Each ride: name + current WTI + Benedictus dot
- Like Air Quality card: big number + scale bar + context text
- "Average wait: 15 min • 5 rides under 10 min"

### 📊 CROWD HEATMAP (full-width)
- Hour × Day grid for the week
- Benedictus-colored cells
- Like Precipitation Map: visual at a glance
- Instantly shows "Thursday afternoon = worst, Saturday morning = golden"

### 📈 CROWD TREND (full-width)
- Like Wind card: directional indicator
- "Getting busier ↑" / "Crowds easing ↓" / "Steady →"
- Shows rate of change in park-level WTI over last 30-60 min
- Compass-style gauge or simple arrow

### 🎆 TONIGHT'S EVENTS (full-width)
- Like Moon card: visual + details
- Timeline: Early Entry 8:30AM → Cavalcade 2PM → Fireworks 9:15PM → Extended Hours 11PM
- Could show castle silhouette / park icon
- Event schedule from park hours data

### 🌡️ WEATHER AT PARK + ☔ RAIN CHANCE (2-column)
- Real weather at the park location (guests care!)
- Temp, conditions, rain probability
- Useful for ride closure predictions (outdoor rides close in storms)
- Requires weather API feed for park coordinates

### 🌅 PARK HOURS + 🎢 RIDE AVAILABILITY (2-column)
- Park Hours: open/close with arc visual (like Sunrise/Sunset)
- Ride Availability: "32 of 35 rides operating" with count

### 📉 VS AVERAGE + ⚡ LIGHTNING LANE (2-column)
- vs Average: "4 min below average Tuesday" — today vs historical
- Lightning Lane: demand level / pricing if available

### 📊 WAIT DISTRIBUTION (2-column or full-width)
- Like Pressure gauge: "60% of rides under 20 min"
- Donut chart or gauge showing the spread of wait times

### 🗺️ OTHER PARKS TODAY (full-width)
- Compact row of other resort parks
- Each: park name + current WTI + Benedictus dot
- "EPCOT: 12 · HS: 24 · AK: 9"
- Helps park-hop decisions

### 🎢 MY MUST-DOS (full-width)
**Live ride recommendation engine** based on gain function algorithm. Super simple UX — no explanations, no complexity.

**Algorithm:**
```
gain(ride) = expected_future_wait(ride) - current_wait(ride)
```
- **Positive gain** = cheaper now than later → recommend now
- **Negative gain** = better later → save for later  
- Always recommends something (highest gain, even if all negative)

**Expected future wait** = weighted average of forecasted waits over dynamic window
- **Window size** = `sum(current_wait + ride_duration)` for remaining rides
- Window shrinks as rides completed → more decisive recommendations
- Weights favor near-term time slots, far-term fade out

**User Interface:**
- User selects 3-4 must-do rides (tap to add/remove)
- Simple ride tags with × to remove
- **"Next up: Seven Dwarfs Mine Train"** — clear recommendation
- **[Done ✓] button** — completes ride, triggers recalculation
- **[+ Add a ride]** option when under 4 selected
- No gain scores shown, no explanations — just trust the algorithm

**Product Decisions:**
- Lightning Lane excluded (user handles scheduled rides)
- Walking distances ignored ("you're at a theme park, you walk")
- No filler ride suggestions (only user-selected rides)
- Re-rides user-managed (want to ride again? add it back)
- Works regardless of when rides are selected (morning/midday/anytime)

**Key Insight:** Universal wait curve pattern (low → peak → fade to ~1/3) makes gain function predictable:
- Morning (pre-peak): Gain positive → "go now, waits climbing"
- Peak hours: Gain negative → recommend least-bad option
- Evening (post-peak): Small gains → order matters less

**Data Requirements:**
- Live wait times (Queue-Times API)
- Wait time forecasts (crowd model) 
- Ride durations (static lookup)
- Current time + park hours

**Layout:** Matches other glassmorphism cards. Ride selector at top, recommendation prominently displayed, done button below.

---

## Background & Visual Design

### Dynamic Background (like Weather app)
- **Time of day:** Bright/sunny → twilight → dark/starry
- **Weather conditions:** Clear sky → partly cloudy → overcast → rain
- **Sun position:** reflects actual sun position at park location
- Requires weather API + sun position calculation for park coordinates

### Animations (Future)
- [ ] Fireworks animation during fireworks hours
- [ ] Animated emoji for parades, shows, festivals
- [ ] Rain/weather effects on background
- [ ] Castle silhouette in background

---

## Global Design Rules

### Forecast Range Bars (Apple Weather Style)
**GLOBAL HISTORICAL RANGE:** The "track" for ALL forecast range bars spans the **full historical range** for that specific park from the database (not just the 7 days displayed).

**Example:** If Magic Kingdom's all-time database range is 3.2 (lowest ever) to 58.7 (highest ever), then:
- **Background track** = 3.2 to 58.7 for ALL forecast rows at Magic Kingdom
- **Each day's colored bar** floats proportionally within that historical track  
- **Today's 15.8** appears as a relatively low value within the full historical context
- **Visual result:** Users instantly see if today is unusually high/low compared to what's ever been recorded

This provides true historical context. A "15" at Magic Kingdom vs "15" at EPCOT would appear differently if parks have different historical ranges. Same as Apple Weather where 75°F in Phoenix vs 75°F in Seattle occupy different positions on their respective historical scales.

---

## Future Considerations

- [ ] Observed vs predicted blending (past = observed, future = predicted)
- [ ] Live intraday forecast adjustment based on current observations
- [ ] Multi-park list view (like Weather app city list)
- [ ] Mobile app wrapper (deferred — browser-first)
- [ ] Crowdsourced density rating community features
- [ ] Ride-level detail view (tap to expand)

---

## File Locations (prototype)

- **Above-the-fold card HTML:** `~/clawd/data/crowd-cards/crowd_card.html`
- **Below-the-fold prototype:** `prototypes/below_fold_with_rides.html`
- **Ride advisor algorithm spec:** `merlin/DESIGN.md`
- Annotated diagram: `~/clawd/data/crowd-cards/crowd_v9_annotated.png`
- Data JSON: `~/clawd/data/crowd-cards/mk_data.json`
- Screenshot script: `~/clawd/data/crowd-cards/screenshot.js`

Will move to `theme-park-crowd-report/web/crowd-card/` when committing.
