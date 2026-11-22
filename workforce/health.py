"""Heartbeat and stale-worker detection.

A stalled worker is NEVER auto-killed. The system investigates and reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class HealthConfig:
    idle_after_s: int = 60
    investigate_after_s: int = 180
    stalled_after_s: int = 300
    heartbeat_after_s: int = 120


DEFAULT_HEALTH = HealthConfig()

LEVEL_LABEL = {
    "healthy": "ACTIVE",
    "idle": "IDLE",
    "investigate": "INVESTIGATE",
    "stalled": "STALLED",
    "blocked": "BLOCKED",
    "finished": "FINISHED",
}


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def classify(
    last_event_at: str | None,
    last_heartbeat_at: str | None = None,
    status: str = "running",
    now: datetime | None = None,
    cfg: HealthConfig = DEFAULT_HEALTH,
) -> dict:
    now = now or datetime.now(timezone.utc)
    last = _parse(last_event_at) or _parse(last_heartbeat_at)
    if status in ("completed", "failed"):
        return {"level": "finished", "label": LEVEL_LABEL["finished"], "age_seconds": 0,
                "action": "none"}
    if status == "blocked":
        return {"level": "blocked", "label": LEVEL_LABEL["blocked"], "age_seconds": 0,
                "action": "awaiting a decision - investigate, never auto-kill"}
    if last is None:
        return {"level": "stalled", "label": LEVEL_LABEL["stalled"], "age_seconds": -1,
                "action": "no event ever received - investigate, never auto-kill"}
    age = max(0, int((now - last).total_seconds()))
    if age >= cfg.stalled_after_s:
        level = "stalled"
    elif age >= cfg.investigate_after_s:
        level = "investigate"
    elif age >= cfg.idle_after_s:
        level = "idle"
    else:
        level = "healthy"
    return {
        "level": level,
        "label": LEVEL_LABEL[level],
        "age_seconds": age,
        "action": "investigate (long tool calls are legitimate) - never auto-kill",
    }
