# TODO — HERMES WORKFORGE

Living plan and agent handoff. Update as work ships; keep evidence (test counts, commits, real
output) next to each completed item. Grand-scheme backlog stays in `Z:/HERMES/.hermes/next.md`.

## Phase 1 — Monitoring foundation ✅ SHIPPED 2026-11-23

- [x] Versioned event schema (`schema_version`, stable `event_id`, UTC timestamps) — `workforce/models.py`
- [x] Evidence states: claimed → implemented → verified → committed → pushed
- [x] Write-first durable reporter: fsync spool, retry, collector-side dedupe, never raises
- [x] Secret redaction by value shape **and** sensitive key name
- [x] FastAPI collector: `POST /events`, `GET /api/health`, `/stream` WebSocket with history replay
- [x] SQLite WAL store: sessions / projects / workers / tasks / events / controls / platform_messages
- [x] State rebuilt from events; weighted progress from a declared task plan
- [x] Control requests + Discord message-ID persistence tables
- [x] Verified: 13/13 `python -m unittest discover -s tests -v`

## Phase 2 — CLI Mission Control ✅ SHIPPED 2026-11-23

- [x] `workforge monitor` — live Rich dashboard, 4 views, keys 1-4 / Q, non-TTY safe
- [x] `workforge snapshot`, `workforge replay`, `workforge doctor`, `workforge serve`
- [x] Attention panel: blocked / failed / stalled with "investigate, never auto-kill"
- [x] `examples/demo_session.py` — 5 projects, 48 events, 1 deliberately blocked
- [x] Verified end to end: demo → collector → snapshot (93.3% overall, 4 verified, 4 committed,
      1 critical attention) → 48-event replay → CLI snapshot + replay render → WebSocket history

## Packaging ✅ SHIPPED 2026-11-23

- [x] Unique generated mark: `assets/workforge.svg` + `scripts/make_icon.py` → PNG 16-512px and multi-size ICO
- [x] Self-contained `site/` with local favicon; deployed from `site/` with `wrangler pages deploy` to
      **https://hermes-workforge.pages.dev** (production Pages URL, HTTP 200 + favicon verified)
- [x] Desktop shortcut `HERMES WORKFORGE - Mission Control.lnk` created and verified (stable Python 3.11, correct args + icon)
- [x] Public repo `Chimthuwu/hermes-workforge`, commit `f2066b3` pushed
- [x] No Electron wrapper: native desktop target is existing Hermes Desktop (Phase 5)

## Phase 3 — Discord adapter ✅ SHIPPED 2026-11-23

- [x] Optional `discord.py` extra; one aggregate adapter (never one message per worker)
- [x] Persistent dashboard message edited in place; ID stored in `platform_messages`
- [x] Per-project threads for routine worker events
- [x] Attention-priority pushes: critical + approvals interrupt; info stays in the thread
- [x] Slash commands `/mission`, `/workers`, `/attention`, `/logs`, `/control` + `tree.sync()` on ready
- [x] Batched edits (2s), reconnect with backoff, final-batch flush on shutdown
- [x] Collector GET/PUT `/api/sessions/{id}/platform-messages` + unit tests
- [x] Verified with `--dry-run` against live collector: 48 events → 2 edits, 2 pushes,
      46 thread posts, stable `msg-1` ID; 18/18 tests green
- [ ] Live bot run needs the existing bot's token in `WORKFORCE_DISCORD_TOKEN` + channel ID —
      deliberately not attempted here (no credentials touched in chat)
- [ ] Acceptance still open: unplug Discord mid-run, workers continue; reconnect rebuilds history

## Phase 4 — Hermes web dashboard ✅ SHIPPED 2026-11-23

- [x] Unified plugin package at `integrations/hermes-workforge/`; installed with `install.py`
- [x] `dashboard/manifest.json` + IIFE bundle using `window.__HERMES_PLUGIN_SDK__`
- [x] `dashboard/plugin_api.py` proxy: status/snapshot/events/attention/control
- [x] `hermes plugins enable hermes-workforge` (official CLI, reversible), no core edits
- [x] Verified in the real dashboard via browser: Workforge tab rendered 48 events,
      5 projects, 93.3% progress, 1 blocked worker; backend hot-mounted, no restart
- [ ] Gateway-proxied WebSocket streaming (currently 3s snapshot polling - deliberate,
      keeps the plugin inside documented read-only APIs)

## Phase 5 — Hermes Desktop ✅ SHIPPED 2026-11-23

- [x] `desktop/plugin.js`: route `/workforge`, sidebar nav, palette command, status-bar chip
- [x] Reads the same scoped backend via `ctx.rest('/snapshot')`; no raw fetch, no state duplication
- [x] `hermes plugins validate` passes including its desktop-surface SDK check; JS syntax checked
- [ ] Live render not exercised - Desktop app was not running; app copies the unified
      half into `desktop-plugins/hermes-workforge/` on start/Rescan

## Phase 6 — Native runtime instrumentation ⏸ DEFERRED (deliberate)

Native tool/subagent/background-process events would require changing Hermes core.
Per the user's instruction, Workforge stays an observer of orchestration jobs and
uses documented extension points only. Revisit if Nous publishes a structured
native event API.

## Deliberate scope calls

- Gateway-proxied WebSocket streaming and a shared React component between
  dashboard and Desktop are **not** done: both interfaces already poll one
  shared backend (3s), which stays inside the documented SDK surfaces.

## Ideas, not commitments 💡

- Session replay scrubbing UI (timeline is in the API; the visual scrubber is not)
- Swarm visualisation: live node graph of agents / subagents / dependencies
- Dependency + overlap detection (two workers editing the same files)
- Resource/model intelligence: tokens, latency, retries, estimated cost, budgets
- Fullscreen wallboard with CRT/terminal theme option
- Windows Job Objects for supervising worker process trees

## Rules for the next agent

- Keep the monitoring service an **observer**. It never owns worker execution.
- Never compute progress from time. Use task weights from a declared plan.
- Never auto-kill a stalled worker. Investigate and report.
- Keep interfaces independent of ingestion: Discord/Web/CLI outages must not stop workers.
- Every shipped change: add a test, run `python -m unittest discover -s tests -v`, commit and push.
