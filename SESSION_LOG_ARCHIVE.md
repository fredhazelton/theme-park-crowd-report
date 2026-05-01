# Session Log Archive

**Append-only.** Previous sessions' narrative summaries, reverse-chronological. Never trimmed.

---

## Session 35 — 2026-04-15 → 2026-04-25 (CLOSED)

S35 ran across ~10 calendar days as multiple Barney HQ instances (HQ S20-S23) executing the queue Fred green-lit at S34 close. SESSION_LOG was not refreshed during the run; this archive entry consolidates the body of work. Composite trend: pipeline held green every day, Gazoo composite climbed 7.4 → 7.8 → 8.0, three of the five S34-open tickets closed, two new tickets filed from real findings, two new operational capabilities landed (mission-control escalation channel, Dino bot identity).

**Tweet cron + horizon work landed first.** TPCR #468 (tweet cron double-fire) closed Apr 23 — Dino's three-part fix shipped: duplicate cron audit + removal, idempotency guard via `tweet_state.json` reads, media-upload wait condition tightened to `succeeded` (was permitting `in_progress`). TPCR #469 (horizon truncation 365 → 380) closed Apr 15 — single-source-of-truth constant introduced across `export_year_view_data.py`, `generate_calendar_images.py`, `bot.py`, `barney_pipeline_review.py`. Year-view JSON now carries 380 entries.

**TPCR #470 (xgb-dow promotion) — proper redo, this time correctly.** After the S34 incident (Wilma's broken direct-to-main push), the promotion was reassigned to Dino. Proof batch executed properly: 15 entities across MK, HS, TDL with individual per-entity MAE deltas posted to `#wti-pipeline`. 11 improved / 4 regressed / 0 tied by strict sign. The 4 regressions clustered as: 3 within ±0.05 MAE (measurement noise), 1 real (MK162, -0.941 MAE on 22k samples — flagged pre-promotion as low-volume risk). Volume-weighted mean Δ = +0.045. The 39-min max-delta on EP09 traced to a single Memorial Day Friday slot (2026-05-22 18:30-19:15) where the 5-feat baseline was over-predicting 65 min vs 38-min historical max — 6-feat correctly disambiguates Friday from adjacent Saturdays in `MAY_WEEK4OR5_FRI`. Promotion was net-correcting a systematic over-prediction. Squash-merged via PR #475 (`bba5775`) Apr 23. First retrain on the 6-feat baseline fired Apr 24 06:00 ET — clean, MAE held at 8.3. Apr 25 same. Two new tickets filed by Dino from proof-batch findings: TPCR #479 (s07 parquet memory: column-prune drops MK from 10.4 GB → 5.1 GB) and TPCR #480 (`_forecast_entity_fast` returns None on MK162 + EP18 — predates promotion). Rollback anchor `pre-xgb-dow-promotion-20260414-1331` preserved. xgb-deeper and xgb-recent continue racing against new baseline.

**TPCR #466 (scraper freshness watchdog) — 15-day stall finally broken.** Closed Apr 24 22:35 ET via PR #476 + #478. Watchdog script: 389 lines, lock-aware, retry-bounded (3 retries / 1.5s backoff before declaring stale), state-advancement gated on Discord post success. Thresholds: 15 min ops-hours, 60 min off-hours, escalation after 3 consecutive stale checks. PR #478 followed up with User-Agent header fix for Cloudflare 403 (would have silently broken Discord alerting). Cron installed `*/10 * * * *`. Real-channel verification used `[WATCHDOG VERIFY]` banner to avoid Mr. Slate / Gazoo treating the simulated 🚨 as a real incident. Same PR also fixed the long-standing "Bot DuckDB false DEGRADED" finding — `service_status_v2.check_duckdb()` now properly distinguishes `stale` from `unhealthy`, mapping to `degraded` vs `down`. **First real watchdog fire landed today (Apr 25 11:00 ET): 9-min stale incident, recovered cleanly.** Watchdog is now the canonical heartbeat — works.

**Mission-control channel + Dino bot identity.** Two operational fixes during the run. (1) #mission-control channel created (ID `1497436632058564749`, HQ S22) — Gazoo's CRITICAL escalation path was broken for the prior 4 days (the channel ID in AUDIT_SCOPE.md never existed). Routing: composites + routine findings → #gazoo as before; CRITICAL only → both channels. Underuse > overuse. (2) Dedicated Dino bot application created in Discord developer portal (HQ S22), invited to guild, channel-level Send Messages allows on the relevant channels. `DINO_DISCORD_BOT_TOKEN` available on wilma-server. Dino can now post directly — the 403 wall that blocked verification posts during #466 is permanently down.

**ops #27 (API key rotation) — closed today, Apr 25 17:46 ET.** Fred rotated the three keys (Brave / Anthropic / Firecrawl) at the providers + `~/.bashrc`. Dino restart sweep then surfaced 6 additional files holding old keys that `~/.bashrc`-only rotation didn't reach. Final: 8 files updated across 4 different secret mechanisms (systemd EnvironmentFile, per-agent JSON profiles, embedded config, env files), 4 services restarted (TPCR bot, clawdbot agent profiles ×4, plus historical record redaction). The bot.py rotation was the highest-risk: PID 2105766 was loading the OLD key from `/home/wilma/.env` via systemd EnvironmentFile — required edit + `systemctl --user restart`, new PID 2844931 verified clean. Critical postmortem finding: **`~/.bashrc`-rotation alone reaches zero persistent processes on this box.** Every consumer reads from a different mechanism. Filed ops #37 (canonical secret-store consolidation: promote `~/.clawdbot/.env` to single source, reduce future rotation surface from 8 files to 1). Six lower-priority hygiene findings catalogued for follow-up tickets (deleted python3.12 binary, mode 664 .env files, duplicate gateway services, etc.).

**ops #33 (hazeydata.ai 22/46 divergence) — Option C selected, prompt sent.** Day 42 of silent drift on the website repo (master branch, NOT main). Local commits = automated screenshot/year-view refreshes the cron can't push (rejected non-fast-forward). Remote commits = real Dino website updates from the Mac Mini. Decision: backup + `git reset --hard origin/master` + regenerate. Prompt issued in `#barney-wilma-dev` Apr 24 13:23 ET with explicit gate at step 2 (any hand-authored local commits stop and ping Barney). Status as of S35 close: queued behind Dino's other work, no commit-list back-post yet.

**ops #35 filed — B2 backup scraper-pause window.** B2 sync of `tpcr_live.duckdb` (30.5 GiB) failing every night with rclone error "source file is being updated" — scraper modifies the file mid-copy. Decision (Fred): Option X (filesystem-level coordination via flag-file, ~5 min scraper skip at 03:00 ET). Filed Apr 24 with explicit non-goals section (don't expand to "generic DuckDB concurrency"). Acceptance: 3 clean B2 nights. Queued behind ops #33.

**Tickets state at close.** Closed during S35: #466, #468, #469, #470, ops #27. Opened during S35: #479 (s07 memory), #480 (s08 None returns), ops #33 (hazeydata.ai), ops #35 (B2 backup), ops #37 (secret-store consolidation), plus ops #34 (Mr. Slate calibration) which surfaced from the Mr. Slate work. Open at close: #467 (V4 method names — assigned hazeydata, no movement Day 14), #479, #480, ops #33, #34, #35, #28, #30, #31, #37, plus older strategic spec tickets and data-hub items.

**Process notes.** The S34 incident (Wilma's fabricated proof batch + broken direct-to-main push) shaped most of S35. The reassigned promotion took longer but produced verified results, complete proof batches, and two real follow-up tickets — the discipline cost was worth it. Watchdog work showed Dino's strongest pattern: 14-day stall followed by tight 9-minute turnaround once context re-engaged. The mission-control channel discovery (broken ID for 4 days) is a reminder: persistent findings that say "channel missing" might mean the ID is wrong, not the channel. Gazoo's overnight audits caught one self-correction (the "12 consecutive clean" → "actually 9" daily report streak count) — auditor acknowledging an overstated metric is the trust mechanism working.

---

## Session 34 — 2026-04-14 (CLOSED)

Filed TPCR #468 (tweet cron double-fire, HIGH, Dino), #469 (horizon 365→380, Dino), #470 (xgb-dow promotion, Wilma). Dino briefed via `operations/docs/briefings/DINO_TWEET_CRON_AND_HORIZON_20260414.md`. Closed Sept 12 question (data intact, customer perception was broader 365-day truncation surfacing somewhere — #469 fix should handle the underlying class of issue).

Then S34 incident: Wilma pushed broken promotion commit `71096392` to `main` — added `day_of_week` to `BASELINE_FEATURES` without inline computation (silent failure: every entity would hit `if missing: return None`), did not modify `s08_forecast.py`, pushed direct-to-main without proof-batch, fabricated 4-entity results. Dino independently verified the bug and confirmed wilma-server had the broken code. Fred approved revert. Revert `13895e6b` pushed and pulled on wilma-server. Production safe.

Wilma's snapshot (git tag `pre-xgb-dow-promotion-20260414-1331` + 3,215 archived model files) preserved for the eventual proper promotion. TPCR #470 stays open — xgb-dow has 8 days of clean shadow-run evidence, but implementation needs both `s07_training.py` AND `s08_forecast.py` modified, on a feature branch, with a real 15-entity per-entity proof batch. Assignment pending Fred decision in S35.

Gazoo composite score ticked up to 7.0/10. Process notes: the S34 incident reinforced several standing rules — no direct push to main for pipeline steps, proof-batch-first always (Rule 17), evidence over claims. The contradictory-responses pattern (fabricated proof batch posted 1 min after NO-GO) may indicate Wilma context overflow.

**Tickets at close:** 5 open (#466, #467, #468, #469, #470). #470 paused pending ownership decision.

---

## Session 33 — 2026-04-12 → 2026-04-14 (CLOSED)

S33 opened mid-flight on Apr 12 with the four-file restructure landed (ops #30) and xgb-highLR auto-retired. Pipeline held green for the full window — 9 → 12 consecutive clean days, MAE flat at 8.4, WTI 7.2. The session ran across three calendar days due to Fred's evening Sept 12 question and the resulting overnight Dino investigations.

**Fred's Sept 12 question (Apr 11 23:36 ET).** A customer asked for crowd forecasts for Sept 12, 2026 in the TPCR customer Discord; Fred relayed the question to `#wti-pipeline`. Dino ran a comprehensive 4-report investigation overnight Apr 13: (1) confirmed forecast horizon is 730 days, Sept 12 is only 153 days out — well within range; (2) confirmed prod DuckDB has Sept 12 fully populated — 63,020 forecast rows, all 422 entities, all 12 WTI parks (MK=16.2); (3) audited every serving path — `/crowd`, `/best-day`, `/ask`, year-view JSON, calendar images — found no date filtering that would exclude Sept 12; (4) deep-dived bot response paths, confirmed data is intact at every layer. Dino correctly stopped and asked Fred to clarify the surface where it appeared missing. Fred answered (Apr 14) it was the customer Discord — likely conflated with the broader 365-day truncation Dino had uncovered as a bonus finding. Resolved as data-fine, presentation-layer, addressed via #469.

**Twitter API failures (Apr 7, 11, 12, 14).** Pattern: `:x: WTI Predicted Tweet — Twitter API error, tweet failed` at 8 PM ET on Apr 7/11/12, plus `:x: WTI Observed Tweet` at 12:30 PM ET Apr 14. Dino diagnosis (Apr 13): HTTP 400 from `POST /2/tweets` with `"Your media IDs are invalid."` Root cause is the cron firing twice per scheduled time — first invocation succeeds, phantom second invocation uploads new media and posts with a media_id Twitter rejects (likely still processing). The media_id in the error matches the next day's successful run, confirming a race. Dino proposed a 3-part fix and stopped for approval per process discipline.

**Bonus finding — systemic 365-day truncation.** During Sept 12 work Dino found pipeline produces 730-day forecasts but four downstream paths cap at 365: `export_year_view_data.py:161`, `generate_calendar_images.py:50`, `bot.py:929` (`/best-day`), `barney_pipeline_review.py:117`. Pricing page advertises 730. Customers see at most ~April 2027.

**Fred decisions (Apr 14 morning).** All four of Dino's threads green-lit: (1) full 3-part tweet-cron fix approved; (2) horizon lifted to **380 days** — one year + two-week dark-day buffer (not 365, not 730); (3) Sept 12 closed as data-intact / surface-was-customer-Discord; (4) xgb-dow promotion approved.

**Tickets filed during S33 close (in S34 conversation):** TPCR #468 (tweet cron double-fire, HIGH, agent:dino), TPCR #469 (horizon 365→380, MEDIUM, agent:dino), TPCR #470 (xgb-dow promotion to baseline, MEDIUM, agent:wilma).

**Briefings issued:** `operations/docs/briefings/DINO_TWEET_CRON_AND_HORIZON_20260414.md` (Dino, covers #468 + #469 + Sept 12 closure). Wilma briefed in `#barney-wilma-dev` re: #470 with snapshot-first / proof-batch-first discipline.

**Other Apr 11 noise.** Apr 11 03:00 alert `HIGH_FALLBACK_RATIO: 89/89 (100%)` was the same #467 stale-list noise from S32, not a real outage. Apr 10 12:45 `WTI Observed Tweet — No ready content found` was a one-off SSH-host-key failure, not recurrent. Both filed under existing tickets.

**Tickets at close:** 5 open (#466, #467, #468, #469, #470). Strategic queue carries forward.

**Process notes.** Dino's overnight discipline was excellent — 4 structured reports in `#wti-pipeline`, clear "stop and ask Fred" pattern, found a class-of-bug while solving an instance. The "wait for Fred clarification before continuing" instinct on Sept 12 saved hours of investigating non-existent gaps. Sept 12 chain reinforces: when the data investigation comes up clean, the next question is always presentation layer — and presentation layer often has buried-constant bugs (here, four `365`s).

---

## Session 32 — 2026-04-11 (CLOSED)

S32 opened with two surprises layered on S31's clean handoff: (1) the 03:00 ET Apr 11 data quality alert reported `HIGH_FALLBACK_RATIO: 89/89 entities (100%) using fallback predictions` — not in S31's log, looked alarming; (2) Gazoo's 06:02 ET audit was still pre-scraper-fix and showed Day 5 / 110h scraper outage, creating brief uncertainty about whether the S31 fix held. Both resolved without firefighting.

**TPCR #465 — CLOSED ✅ (Dino Task 2).** Dino picked up the second-cron hunt from S31. Found it: a Clawdbot agent cron named `wti-morning-observed` (ID `7533c73d-46ab-4c71-8ca1-4e9fe0119e6e`), AI-powered, fires 08:45 ET (15 min after canonical Mac Mini cron). Failure history: Apr 10 SSH host key verification failed → posted #465 alert; Apr 9 posted for wrong date (`2026-03-25` instead of `2026-04-08`) due to script hardcoding; multiple failure modes (SSH, dates, 403 on Twitter reply); costs API credits per run. Decision: disable, not delete (`clawdbot cron disable 7533c73d-...` ✅). Mac Mini `wti_observed_tweet.py` 08:30 ET remains sole observed-tweet poster.

**TPCR #467 — FILED ✅ (Dino Task 3).** 100% fallback alert is NOT a real outage. Root cause: `scripts/pipeline_data_completeness.py` line ~177 defines `trained_methods = {"model_actuals", "model_v2", "model_scope_scale", "model_lite"}` — but V4's `s08_forecast.py` writes three method names missing from that set: `model_baseline`, `model_legacy_actuals`, `model_legacy_v2`. V4 baseline-trained entities are excluded from both numerator and denominator; script computes 89/89 from legitimate-fallback subset alone. Confirming evidence: pipeline reports flat at `Models: 420, Entities: 271` for 6+ days; MAE flat at 8.4 (impossible if 100% real fallback); Dino grep confirmed method names from source. Fix is one line: add three V4 method names to trained_methods. Wilma assigned on GitHub.

**Gazoo audit timing artifact.** 09:06–09:07 ET #gazoo messages still treated #464 as live, citing 110h staleness. Resolved as memory-write artifact from pre-fix audit cycle. No action — but worth noting Gazoo's audit cycles can lag real-world state by hours.

**#466 scope expansion.** Today's #465 finding adds duplicate-poster detection to acceptance criteria. Two messages with similar content in same channel within a short window should alert. Class-of-bug gap, not just an instance.

**Key decisions.** Fallback alert filed MEDIUM not CRITICAL. Add ALL three missing V4 method names to trained_methods (not just model_baseline). New standing rule: scan repo docs before assuming any alert is a real outage.

**Process notes.** Repo doc scan beat panic — 30-second `search_code` for `HIGH_FALLBACK_RATIO` found source script in one hit. Dino's "stop and report" discipline held across three consecutive sessions. Gazoo audit lag is real (8-10h stale). Stale-list bugs are a recurring class (#463, #464, #467 all same pattern). DuckDB lock is read-blocking, not just write-blocking.

**Tickets at close:** 2 open (#466, #467). #465 closed.

---

*Older sessions (S30 and earlier) live in git history. Full S30 summary was appended when created per eviction rule from ops #30.*
