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

## Phase 3 — Discord adapter ⬜ NEXT

- [ ] Optional `discord.py` extra; one adapter aggregates events (never one message per worker)
- [ ] Persistent dashboard message, message ID stored per session in `platform_messages`
- [ ] Per-project threads for detailed worker activity
- [ ] Attention-priority notifications: critical + approvals push; info stays in the timeline
- [ ] Slash commands: `/mission`, `/workers`, `/project`, `/worker`, `/logs`, `/git`, `/pause`, `/resume`
- [ ] Batch embed edits; Discord rate limits must never affect agent execution
- [ ] Acceptance: unplug Discord mid-run, workers continue; reconnect rebuilds state from history

## Phase 4 — Webapp ⬜

- [ ] Gateway-proxied WebSocket (not a raw localhost socket from the browser)
- [ ] Mission Control view, worker inspection, timeline, Git evidence, controls
- [ ] Reuse React component so Desktop can consume it later

## Phase 5 — Hermes Desktop ⬜

- [ ] Integrate into actual Desktop navigation/backend — a separate React app is *not* Desktop integration
- [ ] Correlate native Hermes sessions to workers; parent/child session graph

## Phase 6 — Native runtime instrumentation ⬜

- [ ] Inspect the installed Hermes source first: tool execution, delegation and background-process
      lifecycle boundaries. The prototype hooks in the source conversation are **not** real signatures.
- [ ] Emit `tool_started` / `tool_completed` / `tool_failed`, subagent lifecycle, approval lifecycle
- [ ] Same event schema for native and external workers

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
