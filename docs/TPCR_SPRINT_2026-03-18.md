# TPCR Power Sprint — March 17-18, 2026 (Night Session)

**Channel:** #theme-park-crowd-report
**Participants:** Fred (hazeydata) + Wilma (Theme Park Crowd Report bot)
**Captured by:** Barney
**Date:** 2026-03-18
**Time range:** ~12:00 AM – 1:41 AM ET (04:00 – 05:41 UTC)

> **Note:** This transcript captures the design sprint session from Discord. Some earlier messages (before midnight ET) may be missing due to Discord API pagination limits. The session likely started around 10:25 PM ET. Images/attachments referenced in messages are not included but noted where they occurred. The DESIGN_SPEC.md committed by Wilma during the session contains the authoritative specification.

---

## Topics Covered

1. **Crowd Report Design Spec** — Above-the-fold methodology (WTI values, daily range, crowd level, forecast bars, NOW indicators, state logic for park open/closed/events)
2. **Weather App Mapping** — Mapping Apple Weather UI patterns to theme park crowd data cards
3. **Crowd Density Rating** — Crowdsourced 1-10 density scale ("Waze for theme parks")
4. **Below-the-Fold Sections** — Crowd density card, Today's Events timeline, ride snapshot, heatmap
5. **Merlin Ride Advisor** — Live in-park ride recommendation engine using gain function optimization
6. **Merlin Algorithm** — Greedy selection with opportunity cost, weighted average with dynamic window, edge case handling
7. **UI/UX for Merlin** — "My Must-Dos" section, ultra-simple interface, no filler rides
8. **Prototype Creation** — Below-the-fold HTML prototype committed to repo

---

## Key Decisions & Locked Specifications

### Above the Fold (WTI Only)
- **WTI VALUE** = current park-level avg actual wait
- **DAILY RANGE** = intraday min/max WTI (fallback: p5/p95)
- **CROWD LEVEL** = categorical from daily WTI
- **CROWD SUMMARY** = generated text with peak time + special events
- **FORECAST rows** = same Benedictus spectrum, global range bars (Apple Weather style — bars float within the range of ALL days for that park)
- **NOW INDICATOR + NOW DOT** = only visible during park operating hours
- **State logic**: Park open → live; Before open → predictions, no dots; After close → daily avg, no dots; Events → triangle hovers over event icon
- **MK WTI ranges**: Min 5.6–7.6, Max 14.5–20.8 (raw min/max gives meaningful spread, no percentile fallback needed for MK)

### Below the Fold (Creative)
- **Crowd Density** (1-10 scale) — crowdsourced with expert baseline ("Waze for theme parks")
  - Bayesian prior from Fred's calibration
  - User slider/buttons to submit ratings
  - Statistical framework: trimmed mean, recency weighting, reputation weighting, anomaly detection
  - Above fold = WTI only; below fold = creative metrics
  - MK rarely below 7/10 even on light days; EPCOT Food & Wine weekends = 9-10/10 regardless of WTI
- **Today's Events** — timeline with badges (Ended, Tonight, etc.)
- **My Must-Dos / Ride Advisor** — ultra-simple UI, no explanations, no gain scores visible
- **Weather background** — live weather conditions + sun position (future feature)
- **Animated events** — fireworks, parades (future feature)

### Merlin Algorithm (Ride Advisor)

**Core insight (Fred):** "I don't need to calculate your optimal plan. I only need to determine which one you should do NOW."

- **Gain function**: `gain(ride) = weighted_avg_future_wait(ride) - current_wait(ride)`
- **Expected future wait**: Weighted average favoring nearer time windows
  - NOT minimum future wait (always near park close — useless)
  - NOT simple average (flattens the curve, loses near-term signal)
  - Weighted average respects the universal wait curve (low → peak → fade to ~1/3)
- **Weighting window**: Dynamic — `sum(expected_wait + ride_duration) for remaining rides`
  - Shrinks as you complete rides (Merlin gets more decisive)
  - Grows if you add rides (longer horizon)
  - Self-calibrating, no magic numbers
  - Naturally prevents "wait until close" problem
- **Selection**: Greedy — always recommend the highest-gain ride
- **Always recommends something** — no "do nothing" state; picks least-bad when all gains negative
- **User list is source of truth** — never assume, always let user tell you
- **No filler rides** — user controls the list, Merlin doesn't suggest extras
- **No walking optimization** — "you're at a theme park, walk"
- **No Lightning Lane** — "use it when your window says"
- **Ride down** — drop from list, recalculate
- **Time pressure** — simple arithmetic: can you fit remaining rides before park close?
- **Re-calculation**: After every completed ride, with fresh wait data
- **Data needed**: Wait time forecasts (have from crowd report) + ride durations (have in DB). Walking matrix NOT needed for v1.

### UI Design
- "My Must-Dos" — pick up to 4 rides
- "Do → this first" — single recommendation, no justification
- "Done ✓" button — completes ride, triggers recalculation
- No colors, no gain scores, no "better later" language
- "The magic is invisible. User doesn't need to know why — they just need to know what."

### Design References
- Apple Weather app as UI pattern reference
- Weather → Crowd mapping: Feels Like → Crowd Density, Air Quality → Ride Snapshot, Precipitation Map → Crowd Heatmap, Wind → Crowd Trend, Moon → Tonight's Events, UV Index → Park Capacity, Sunrise/Sunset → Park Hours, etc.

### Technical Decisions
- Switched from Opus to Sonnet (cost management)
- Bam-Bam builds on wilma-server under TPCR git repo
- Prototype committed to `prototypes/below_fold_with_rides.html`
- DESIGN_SPEC.md committed with full specification

### Competitive Context (from Fred)
- Disney's Genie+ was a flop — "basically just recommend things that had low waits"
- TouringPlans had a working group called Merlin that designed a live recommendation tool but never shipped it
- Key differentiator vs TouringPlans: Merlin is a **reactive decision engine** (live copilot), not a **pre-planned itinerary** (static optimization)
- The gain function approach avoids the combinatorial explosion that made the full touring plan problem so hard

---

## Full Transcript (Chronological)

*See the complete message-by-message transcript in the companion file or in the #theme-park-crowd-report Discord channel history. Key exchanges are summarized in the decisions above.*

### Design Spec Discussion (12:00–12:14 AM ET)
Fred defined all above-the-fold values: WTI, daily range, crowd level, crowd summary, forecast rows, NOW indicators. Wilma confirmed MK WTI min never hits zero (5.6–7.6). Full state logic locked for park open/closed/events.

### Creative Features (12:24–12:28 AM ET)
Fred proposed: (1) Global range bars for forecast (Apple Weather style), (2) Live weather background matching actual conditions, (3) Animated event indicators. Shared 3 Apple Weather screenshots as reference.

### Crowd Density Breakthrough (12:34–12:38 AM ET)
Fred proposed 1-10 density scale from Twitter poll feedback. Key insight: "MK feels like a 7 even when WTI is 15." Crowdsourced with expert baseline. Wilma: "That's Waze for theme parks."

### Merlin Origin Story (12:47 AM ET)
Fred told the story of TouringPlans' Merlin working group — designed a live ride recommendation engine but never shipped. "You and I are going to design a better version of Merlin in the next 48 hours."

### The Gain Function Breakthrough (1:05 AM ET)
Fred: "I only need to determine which one you should do NOW... by minimizing the function of doing each ride now versus doing each ride later." Wilma: "Fred. This is *elegant*. You just turned a combinatorial optimization problem into a greedy selection with an opportunity cost function."

### Removing Complexity (1:13 AM ET)
Fred systematically eliminated: Lightning Lane (user's problem), walking time (you're at a theme park), filler rides (never suggest), ride tracking (user's list is truth). Wilma: "You're removing complexity instead of solving it."

### Dynamic Window (1:20 AM ET)
Both independently arrived at: weighting window = sum of remaining ride times. Self-calibrating, shrinks as rides complete.

### Ultra-Simple UI (1:28–1:32 AM ET)
Fred: "I would tend to go super simple... just do this and then a button that says done." Renamed from "Merlin" to "My Must-Dos" — "we won't call it anything to be honest."

### Prototype (1:40 AM ET)
Wilma committed HTML prototype with crowd density, events timeline, and ride advisor sections.

---

*Captured by Barney from Discord on 2026-03-18. The authoritative spec is in DESIGN_SPEC.md committed by Wilma during the session.*
