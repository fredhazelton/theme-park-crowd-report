# 🧙 Merlin — Live Theme Park Ride Advisor

## Vision
A live, in-park tool that tells you which ride to do **right now** from your personal must-do list, based on current wait times and forecasted future waits.

Not a touring plan. A live copilot.

## Core Concept

### The Gain Function
For each ride on the user's list, calculate:

```
gain(ride) = expected_future_wait(ride) - current_wait(ride)
```

- **Positive gain** = "This ride is cheaper now than it will be later" → do it now
- **Negative gain** = "This ride will be cheaper later" → save it
- **Merlin always recommends something** — pick the highest gain, even if all are negative

### The Loop
1. User selects 3-4 must-do rides
2. Merlin scores each ride using the gain function
3. Recommends the highest-gain ride: "Do this one now"
4. User rides it → it drops off the list
5. User can add a new ride (or not)
6. Recalculate with fresh wait times → repeat

## The Gain Function — Formal Definition

### Expected Future Wait = Weighted Average with Dynamic Window

**Method chosen:** Weighted average of forecasted waits, favoring nearer time windows.

**Why not the others:**
- ~~Minimum future wait~~ → Always points to park close. Tells someone at 10 AM to wait until 9:45 PM. Useless.
- ~~Simple average~~ → Flattens the curve, loses the signal of what's about to happen.
- ✅ **Weighted average** → Respects the curve shape. Morning = "go now, it's getting worse." Peak = "wait if you can." Evening = "everything's fine, order barely matters."

### Dynamic Weighting Window
The look-ahead window scales with remaining ride time:

```
window ≈ sum(current_wait(ride) + ride_duration(ride)) for each remaining ride
```

**Why dynamic:**
- Shrinks as you complete rides → Merlin gets more decisive
- Grows if you add rides → looks further ahead
- Self-calibrating — no magic number to tune
- Naturally prevents "wait until close" recommendations

**Weighting:** Exponential decay within the window. Near-term slots weighted heavily, far-term slots fade out.

**Walking time:** Ignored. Could add a small buffer (~5 min per ride) but unlikely to change recommendations meaningfully. Will validate through testing.

### Key Insight: The Universal Wait Curve
Nearly every ride follows the same shape (the hazeydata logo):
- Near zero at park open
- Climb toward a peak in mid-afternoon
- Fade to ~1/3 of peak by park close

This means the gain function behaves predictably:
- **Morning (pre-peak):** Gain is positive for everything → "go now, waits are climbing"
- **Peak hours:** Gain is negative → Merlin picks the least-bad option
- **Evening (post-peak):** Small gains, recommendations are gentler

## Scope Decisions (Complexity Removed)

| Thing | Decision | Rationale |
|-------|----------|-----------|
| Lightning Lane | Excluded | LL is scheduled — user handles it, nothing to optimize |
| Walking distances | Ignored | You're at a theme park, you walk. If walking order matters to you, just do walking order. |
| Filler rides | Not suggested | Merlin only works with user-selected rides. No assumptions about what you want. |
| Re-rides | User-managed | Want to ride again? Add it back to the list. Merlin doesn't assume. |
| Pre-planning | Not required | Select rides anytime — morning, midday, spontaneously. Merlin optimizes from "now." |

## Time Pressure
Simple arithmetic check:
```
remaining_park_time = park_close - now
minimum_ride_time = sum(ride_duration for each ride on list)
if minimum_ride_time > remaining_park_time:
    warn user: "You may not have time for all of these"
```
No walking time needed — this is a lower bound. If you can't do it even at teleportation speed, you definitely can't do it walking.

## Ride Goes Down
- Monitor queue times data for closure signals
- Drop ride from user's list (with notification)
- Recalculate remaining rides

## Data Requirements

### Must Have
- **Live wait times** — from Queue Times API (already available)
- **Wait time forecasts** — from our crowd model (already being built)
- **Ride durations** — static data, stored once per attraction

### Nice to Have (v2+)
- Walking distances (GPS-based approximation)
- Historical accuracy of gain recommendations
- User feedback loop

## Open Questions
1. ~~How do we define "expected future wait"?~~ ✅ Weighted average with dynamic window (see above)
2. ~~Which parks first?~~ ✅ Magic Kingdom
3. ~~How do we present the gain score to users?~~ ✅ Not shown. The ranked order IS the output. Insight card explains #1 pick in plain English.
4. **What happens when two rides have nearly identical gain?** Tie-breaking strategy TBD.
5. **Refresh rate?** How often does Merlin recalculate? On-demand? Every 5 min?
6. ~~What's the UI?~~ ✅ Below-the-fold section in crowd report. See UX spec below.

## Edge Cases to Stress Test
- [ ] All rides negative gain at 11 AM (park is crowded, everything is worse now)
- [ ] User selects only 1 ride (trivial — just go do it)
- [ ] Two rides with identical gain scores
- [ ] Ride wait drops to 0 (walk-on) — is gain still meaningful?
- [ ] Park is nearly empty — all waits are low, gains are flat
- [ ] User keeps adding rides, list grows to 8+ (do we cap it?)
- [ ] Forecast is wrong — actual wait differs significantly from predicted

## Architecture (Proposed)
```
[Queue Times API] → Live Waits
[Crowd Model]     → Forecasted Waits
                         ↓
              [Gain Function Engine]
                         ↓
                  [Ride Ranking]
                         ↓
                   [User Interface]
                     ↕ (add/remove/complete)
                   [Ride List State]
```

---

## UX Specification (Finalized 2026-03-18)

> Full UX decisions documented in `~/clawd/docs/pebbles-design-decisions.md`
> Approved prototypes at `hazeydata.ai/preview/`

### User Flow
```
[+] tap → Ride Picker modal (list + mini-map)
  → Select up to 4 rides → Done
  → Cards appear in user's selection order (blank ranks)
  → Animated shuffle to optimized order (gain function)
  → Rank numbers pop in (1, 2, 3, 4)
  → "Merlin's Pick" insight card explains WHY #1 was chosen
  → Leader line connects insight → highlighted #1 card
  → Auto-peek nudge teaches swipe gestures
  → Swipe right = Done ✓ | Swipe left = Remove ✕
  → Card removed → recalculate → re-rank remaining
  → "+ Add another ride" to refill slots
```

### Ride Picker (modal bottom sheet)
- Compact text rows grouped by **land cards** (color-coded)
- **No wait times shown** — picker is about desire, not logistics
- Search bar + max 4 rides + slot indicator
- ✦ REC badges on optimizer-recommended rides
- Collapsible **mini-map** (~150px) shows selected ride locations
- Auto-opens on first selection

### Optimizer Result (main page section)
- Cards: rank badge · ride name · description · current wait time
- **Animated FLIP reorder** from user order → optimized order = the "computation visible" moment
- **"✦ Merlin's Pick" insight card** above #1: plain-English explanation of WHY
  - e.g., "Wait times are at their lowest right now. Heading here first saves you up to 37 minutes."
- Animated dashed leader line → highlighted #1 card (cyan glow)
- #1 rank badge = filled cyan; others = outlined

### Swipe Actions (iOS-style)
- **Swipe RIGHT** → compact cyan pill: "✓ Done" (logged as completed)
- **Swipe LEFT** → compact red pill: "Remove ✕" (logged as removed/skipped)
- Auto-peek nudge on #1 card teaches interaction
- Directional swipe captures user intent = free behavioral data

### Design Principles
1. Less is more — ruthlessly cut text and visual noise
2. Show, don't tell — animated reorder > loading spinner
3. Desire over logistics — picker = want; optimizer = strategy
4. Computation must be felt — the shuffle IS the intelligence
5. iOS conventions — bottom sheets, swipe actions, compact pills
6. Benedictus palette only — navy, cyan, red, gold
7. Data is a byproduct — swipe direction captures intent passively

### Approved Prototypes
| File | Status |
|------|--------|
| `hazeydata.ai/preview/ride-picker-v4.html` | ✅ FINAL — Ride picker with mini-map |
| `hazeydata.ai/preview/optimizer-v3.html` | ✅ FINAL — Optimizer with insight card + swipe |

---

## Timeline
48 hours. Go.

---
*Design started: 2026-03-18*
*Fred Hazelton & Wilma*
