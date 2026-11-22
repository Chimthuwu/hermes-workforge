"""Versioned, redacted event schema shared by every Workforge interface.

The event is the contract. Workers emit events; the collector owns state.
No interface is allowed to calculate its own progress or completion.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = "1.0"
Status = Literal["queued", "running", "blocked", "completed", "failed"]

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,})"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{16,}", re.I),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[^\s'\",]{6,}"),
)


_SENSITIVE_KEY = re.compile(
    r"(?i)password|passwd|pwd|secret|token|api[_-]?key|authorization|credential|cookie"
)


def redact(value: Any, _key: str | None = None) -> Any:
    """Recursively scrub credential-shaped strings. Never raises.

    Both the value shape and the key name are checked: a plain string stored
    under 'password' is a secret even when it does not look like an API key.
    """
    if _key and _SENSITIVE_KEY.search(_key) and isinstance(value, (str, int, float)):
        return "[REDACTED]"
    if isinstance(value, str):
        out = value
        for pattern in _SECRET_PATTERNS:
            out = pattern.sub("[REDACTED]", out)
        return out
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, _key) for v in value]
    return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Evidence(BaseModel):
    """Proof of work. A green light needs more than the word 'done'."""

    claimed: bool = False
    implemented: bool = False
    verified: bool = False
    committed: bool = False
    pushed: bool = False
    files_changed: int = 0
    tests_passed: int | None = None
    commit: str | None = None
    note: str | None = None

    @property
    def level(self) -> str:
        for key in ("pushed", "committed", "verified", "implemented", "claimed"):
            if getattr(self, key):
                return key
        return "none"

    @field_validator("note", "commit")
    @classmethod
    def _scrub(cls, v: str | None) -> str | None:
        return redact(v) if v else v


class WorkerEvent(BaseModel):
    """The one event shape used by workers, runner, CLI, Discord and Web."""

    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    project_id: str
    worker_id: str
    event: str
    status: Status = "running"
    task: str | None = None
    message: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence: Evidence | None = None

    @field_validator("task", "message")
    @classmethod
    def _scrub_text(cls, v: str | None) -> str | None:
        return redact(v) if v else v

    @field_validator("metadata")
    @classmethod
    def _scrub_meta(cls, v: dict[str, Any]) -> dict[str, Any]:
        return redact(v)

    def json_line(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_line(cls, line: str) -> "WorkerEvent":
        return cls.model_validate_json(line)

    @classmethod
    def from_row(cls, row: Any) -> "WorkerEvent":
        import json

        keys = (
            "schema_version", "event_id", "session_id", "project_id", "worker_id",
            "event", "status", "task", "message", "timestamp", "metadata_json", "evidence_json",
        )
        d = dict(zip(keys, row))
        d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        ev = d.pop("evidence_json")
        d["evidence"] = Evidence.model_validate_json(ev) if ev else None
        return cls.model_validate(d)


class TaskSpec(BaseModel):
    """Planned work. Weight is planned effort, never elapsed time."""

    id: str
    name: str
    weight: float = 1.0
    status: Status = "queued"
    evidence: Evidence = Field(default_factory=Evidence)
