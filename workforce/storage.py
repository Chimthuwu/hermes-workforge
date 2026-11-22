"""SQLite WAL store: append-only events plus a rebuilt session snapshot."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .health import classify
from .models import Evidence, WorkerEvent, utcnow

DEFAULT_DB = os.environ.get(
    "WORKFORCE_DB", str(Path.home() / ".workforce" / "workforce.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, name TEXT, created_at TEXT, updated_at TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    session_id TEXT, project_id TEXT, name TEXT, status TEXT,
    current_task TEXT, updated_at TEXT,
    PRIMARY KEY (session_id, project_id)
);
CREATE TABLE IF NOT EXISTS workers (
    session_id TEXT, worker_id TEXT, project_id TEXT, status TEXT, task TEXT,
    last_event_at TEXT, last_heartbeat_at TEXT, updated_at TEXT,
    PRIMARY KEY (session_id, worker_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    session_id TEXT, project_id TEXT, task_id TEXT, name TEXT, weight REAL,
    status TEXT, evidence_json TEXT, updated_at TEXT,
    PRIMARY KEY (session_id, project_id, task_id)
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, schema_version TEXT, session_id TEXT,
    project_id TEXT, worker_id TEXT, event TEXT, status TEXT, task TEXT,
    message TEXT, timestamp TEXT, metadata_json TEXT, evidence_json TEXT,
    received_at TEXT
);
CREATE INDEX IF NOT EXISTS events_session_ts ON events (session_id, timestamp);
CREATE TABLE IF NOT EXISTS controls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, target TEXT,
    action TEXT, requested_by TEXT, requested_at TEXT, status TEXT
);
CREATE TABLE IF NOT EXISTS platform_messages (
    session_id TEXT, platform TEXT, message_id TEXT, thread_id TEXT,
    updated_at TEXT, PRIMARY KEY (session_id, platform)
);
"""


class Store:
    def __init__(self, path: str = DEFAULT_DB):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- writes ---------------------------------------------------------
    def insert_event(self, event: WorkerEvent) -> bool:
        """Insert an event and update registries. False = duplicate, no state change."""
        now = utcnow().isoformat()
        ts = event.timestamp.astimezone(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.event_id, event.schema_version, event.session_id,
                    event.project_id, event.worker_id, event.event, event.status,
                    event.task, event.message, ts,
                    json.dumps(event.metadata, sort_keys=True),
                    event.evidence.model_dump_json() if event.evidence else None,
                    now,
                ),
            )
            if cur.rowcount == 0:
                return False
            self.conn.execute(
                """INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?)""",
                (event.session_id, event.session_id, ts, now, "running"),
            )
            self.conn.execute(
                """UPDATE sessions SET updated_at=?, status='running' WHERE id=?""",
                (now, event.session_id),
            )
            self.conn.execute(
                """INSERT OR IGNORE INTO projects VALUES (?,?,?,?,?,?)""",
                (event.session_id, event.project_id, event.project_id,
                 "queued", None, now),
            )
            self.conn.execute(
                """UPDATE projects SET status=?, current_task=COALESCE(?, current_task),
                   updated_at=? WHERE session_id=? AND project_id=?""",
                (event.status, event.task, now, event.session_id, event.project_id),
            )
            hb = ts if event.event == "worker_heartbeat" else None
            self.conn.execute(
                """INSERT OR IGNORE INTO workers VALUES (?,?,?,?,?,?,?,?)""",
                (event.session_id, event.worker_id, event.project_id,
                 event.status, event.task, ts, hb, now),
            )
            self.conn.execute(
                """UPDATE workers SET status=?, project_id=?,
                   task=COALESCE(?, task),
                   last_event_at=CASE WHEN ? IS NULL THEN last_event_at ELSE ? END,
                   last_heartbeat_at=COALESCE(?, last_heartbeat_at),
                   updated_at=? WHERE session_id=? AND worker_id=?""",
                (event.status, event.project_id, event.task, ts, ts, hb,
                 now, event.session_id, event.worker_id),
            )
            if event.event == "task_plan":
                for task in event.metadata.get("tasks", []):
                    spec = task if isinstance(task, dict) else task.model_dump(mode="json")
                    self.set_task(event.session_id, event.project_id, spec)
            task_id = event.metadata.get("task_id")
            if task_id:
                patch: dict[str, Any] = {}
                if event.event in ("task_completed", "task_failed", "task_started", "task_status"):
                    patch["status"] = {
                        "task_completed": "completed", "task_failed": "failed",
                        "task_started": "running",
                    }.get(event.event, event.metadata.get("status", "queued"))
                if event.evidence:
                    patch["evidence"] = event.evidence
                if patch:
                    self.patch_task(event.session_id, event.project_id, str(task_id), patch)
            if event.event in ("worker_completed", "worker_failed", "worker_blocked"):
                self.conn.execute(
                    """UPDATE workers SET status=? WHERE session_id=? AND worker_id=?""",
                    ({"worker_completed": "completed", "worker_failed": "failed",
                      "worker_blocked": "blocked"}[event.event],
                     event.session_id, event.worker_id),
                )
            self.conn.commit()
            return True

    def set_task(self, session_id: str, project_id: str, spec: dict[str, Any]) -> None:
        ev = spec.get("evidence") or {}
        if isinstance(ev, Evidence):
            ev = ev.model_dump(mode="json")
        with self._lock:
            self.conn.execute(
                """INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(session_id,project_id,task_id) DO UPDATE SET
                   name=excluded.name, weight=excluded.weight, status=excluded.status,
                   evidence_json=excluded.evidence_json, updated_at=excluded.updated_at""",
                (session_id, project_id, str(spec["id"]), spec.get("name", ""),
                 float(spec.get("weight", 1)), spec.get("status", "queued"),
                 json.dumps(ev), utcnow().isoformat()),
            )
            self.conn.commit()

    def patch_task(self, session_id: str, project_id: str, task_id: str,
                   patch: dict[str, Any]) -> None:
        with self._lock:
            row = self.conn.execute(
                """SELECT * FROM tasks WHERE session_id=? AND project_id=? AND task_id=?""",
                (session_id, project_id, task_id),
            ).fetchone()
            if not row:
                self.conn.execute(
                    """INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)""",
                    (session_id, project_id, task_id, task_id, 1.0,
                     patch.get("status", "queued"),
                     (patch["evidence"].model_dump_json() if patch.get("evidence") else "{}"),
                     utcnow().isoformat()),
                )
            else:
                ev = dict(json.loads(row["evidence_json"] or "{}"))
                if patch.get("evidence"):
                    ev.update(patch["evidence"].model_dump(mode="json"))
                self.conn.execute(
                    """UPDATE tasks SET status=?, evidence_json=?, updated_at=?
                       WHERE session_id=? AND project_id=? AND task_id=?""",
                    (patch.get("status", row["status"]), json.dumps(ev),
                     utcnow().isoformat(), session_id, project_id, task_id),
                )
            self.conn.commit()

    def set_control(self, session_id: str, target: str, action: str,
                    requested_by: str = "api") -> dict:
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO controls (session_id,target,action,requested_by,requested_at,status)
                   VALUES (?,?,?,?,?,'requested')""",
                (session_id, target, action, requested_by, utcnow().isoformat()),
            )
            self.conn.commit()
            return {"id": cur.lastrowid, "session_id": session_id, "target": target,
                    "action": action, "status": "requested"}

    def set_platform_message(self, session_id: str, platform: str,
                             message_id: str, thread_id: str | None = None) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO platform_messages VALUES (?,?,?,?,?)
                   ON CONFLICT(session_id,platform) DO UPDATE SET
                   message_id=excluded.message_id, thread_id=excluded.thread_id,
                   updated_at=excluded.updated_at""",
                (session_id, platform, message_id, thread_id, utcnow().isoformat()),
            )
            self.conn.commit()

    # -- reads -----------------------------------------------------------
    def list_sessions(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def latest_session_id(self) -> str | None:
        sessions = self.list_sessions()
        return sessions[0]["id"] if sessions else None

    def list_events(self, session_id: str | None = None, limit: int = 100,
                    since: str | None = None, offset: int = 0) -> list[WorkerEvent]:
        sql = "SELECT * FROM events WHERE 1=1"
        args: list[Any] = []
        if session_id:
            sql += " AND session_id=?"
            args.append(session_id)
        if since:
            sql += " AND timestamp>=?"
            args.append(since)
        sql += " ORDER BY timestamp DESC, rowid DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [WorkerEvent.from_row(r) for r in rows]

    def snapshot(self, session_id: str | None = None) -> dict:
        session_id = session_id or self.latest_session_id()
        if not session_id:
            return {"session": None, "projects": [], "workers": [], "overall": {},
                    "attention": [], "latest_events": []}
        with self._lock:
            srow = self.conn.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            prows = self.conn.execute(
                "SELECT * FROM projects WHERE session_id=? ORDER BY project_id",
                (session_id,)).fetchall()
            wrows = self.conn.execute(
                "SELECT * FROM workers WHERE session_id=? ORDER BY worker_id",
                (session_id,)).fetchall()
            trows = self.conn.execute(
                "SELECT * FROM tasks WHERE session_id=? ORDER BY project_id, task_id",
                (session_id,)).fetchall()
            events = self.list_events(session_id, limit=8)
            total_events = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE session_id=?", (session_id,)).fetchone()[0]
            controls = self.conn.execute(
                "SELECT * FROM controls WHERE session_id=? ORDER BY id DESC LIMIT 5",
                (session_id,)).fetchall()

        tasks: dict[str, list[dict]] = {}
        for t in trows:
            tasks.setdefault(t["project_id"], []).append({
                "id": t["task_id"], "name": t["name"], "weight": t["weight"],
                "status": t["status"],
                "evidence": json.loads(t["evidence_json"] or "{}"),
            })

        def progress(items: list[dict]) -> dict:
            total = sum(float(i["weight"]) for i in items)
            done = sum(float(i["weight"]) for i in items if i["status"] == "completed")
            return {"progress": round(done / total * 100, 1) if total else 0.0,
                    "tasks_total": len(items),
                    "tasks_completed": sum(1 for i in items if i["status"] == "completed")}

        projects = []
        for p in prows:
            ptasks = tasks.get(p["project_id"], [])
            evs = [t["evidence"] for t in ptasks]
            projects.append({
                "project_id": p["project_id"], "name": p["name"], "status": p["status"],
                "current_task": p["current_task"], "updated_at": p["updated_at"],
                **progress(ptasks),
                "verified": any(e.get("verified") for e in evs),
                "committed": any(e.get("committed") for e in evs),
                "commit": next((e.get("commit") for e in evs if e.get("commit")), None),
            })

        workers = []
        attention = []
        for w in wrows:
            health = classify(w["last_event_at"], w["last_heartbeat_at"], w["status"])
            workers.append({
                "worker_id": w["worker_id"], "project_id": w["project_id"],
                "status": w["status"], "task": w["task"],
                "last_event_at": w["last_event_at"], "health": health,
            })
            if health["level"] in ("stalled", "investigate") or w["status"] in ("blocked", "failed"):
                attention.append({
                    "level": "critical" if w["status"] in ("blocked", "failed") else "warning",
                    "project": w["project_id"], "worker": w["worker_id"],
                    "reason": (f"status={w['status']}" if w["status"] in ("blocked", "failed")
                               else f"no meaningful event for {health['age_seconds']}s"),
                    "action": health["action"],
                })

        all_tasks = [t for v in tasks.values() for t in v]
        overall = progress(all_tasks)
        overall.update({
            "events": total_events,
            "workers_total": len(workers),
            "workers_active": sum(1 for w in workers if w["status"] == "running"),
            "projects_total": len(projects),
            "verified": sum(1 for p in projects if p["verified"]),
            "committed": sum(1 for p in projects if p["committed"]),
        })
        return {
            "session": dict(srow) if srow else {"id": session_id},
            "projects": projects, "workers": workers, "overall": overall,
            "attention": attention,
            "latest_events": [e.model_dump(mode="json") for e in events],
            "controls": [dict(c) for c in controls],
        }

    def replay(self, session_id: str) -> dict:
        events = list(reversed(self.list_events(session_id, limit=100000)))
        timeline = []
        seen: dict[str, str] = {}
        for e in events:
            if e.project_id:
                seen[e.project_id] = e.status
            timeline.append({
                "t": e.timestamp.isoformat(), "event": e.event,
                "project": e.project_id, "worker": e.worker_id,
                "status": e.status, "message": e.message, "task": e.task,
                "evidence_level": e.evidence.level if e.evidence else None,
            })
        return {"session_id": session_id, "event_count": len(timeline),
                "project_status_at_end": seen, "timeline": timeline}
