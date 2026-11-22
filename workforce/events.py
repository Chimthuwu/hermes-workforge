"""Durable event reporter. Reporting must never crash a worker."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import httpx

from .models import Evidence, Status, WorkerEvent

DEFAULT_ENDPOINT = "http://127.0.0.1:8765"


class EventReporter:
    """Write-first, send-second: an event is on disk before any HTTP happens.

    A failed collector never raises into the worker. Pending lines are retried
    on the next emit (or an explicit flush), and the collector dedupes by ID.
    """

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        session_id: str = "session-001",
        project_id: str = "project",
        worker_id: str = "worker-01",
        queue_dir: str | None = None,
        timeout: float = 2.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.session_id = session_id
        self.project_id = project_id
        self.worker_id = worker_id
        self.timeout = timeout
        self.queue_dir = Path(queue_dir or os.environ.get(
            "WORKFORCE_QUEUE", str(Path.home() / ".workforce" / "queue")))
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{session_id}-{project_id}-{worker_id}".replace("/", "_").replace("\\", "_")
        self.queue_file = self.queue_dir / f"{stem}.jsonl"
        self.sent_file = self.queue_dir / f"{stem}.sent"
        self._sent: set[str] = set()
        if self.sent_file.exists():
            try:
                self._sent = set(self.sent_file.read_text(encoding="utf-8").splitlines())
            except OSError:
                self._sent = set()
        self._lock = threading.Lock()

    def emit(
        self,
        event: str,
        status: Status = "running",
        task: str | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
        evidence: Evidence | None = None,
    ) -> WorkerEvent | None:
        try:
            ev = WorkerEvent(
                session_id=self.session_id, project_id=self.project_id,
                worker_id=self.worker_id, event=event, status=status,
                task=task, message=message, metadata=metadata or {},
                evidence=evidence,
            )
            with self._lock:
                with self.queue_file.open("a", encoding="utf-8") as fh:
                    fh.write(ev.json_line() + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            self.flush()
            return ev
        except Exception:
            return None

    def heartbeat(self, task: str | None = None) -> WorkerEvent | None:
        return self.emit("worker_heartbeat", "running", task=task)

    def flush(self) -> int:
        """Send every unsent queued event. Returns how many were delivered."""
        delivered = 0
        try:
            with self._lock:
                lines = self.queue_file.read_text(encoding="utf-8").splitlines()
            pending = []
            for line in lines:
                try:
                    ev = WorkerEvent.from_line(line)
                except Exception:
                    continue
                if ev.event_id not in self._sent:
                    pending.append(ev)
            for ev in pending:
                try:
                    resp = httpx.post(
                        f"{self.endpoint}/events",
                        json=ev.model_dump(mode="json"),
                        timeout=self.timeout,
                    )
                    if resp.status_code >= 400:
                        break
                except httpx.HTTPError:
                    break
                self._sent.add(ev.event_id)
                delivered += 1
                with self._lock:
                    with self.sent_file.open("a", encoding="utf-8") as fh:
                        fh.write(ev.event_id + "\n")
                        fh.flush()
                        os.fsync(fh.fileno())
        except Exception:
            pass
        return delivered

    def pending_count(self) -> int:
        try:
            lines = self.queue_file.read_text(encoding="utf-8").splitlines()
            return sum(1 for l in lines if l and '"event_id"' in l) - len(self._sent)
        except OSError:
            return 0
