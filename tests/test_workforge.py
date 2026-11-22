"""Run with: python -m unittest discover -s tests -v"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from workforce.health import HealthConfig, classify
from workforce.models import SCHEMA_VERSION, Evidence, WorkerEvent, redact
from workforce.storage import Store
from workforce import server


def event(**kwargs):
    base = dict(session_id="S1", project_id="P1", worker_id="W1",
                event="worker_started", status="running")
    base.update(kwargs)
    return WorkerEvent(**base)


class SchemaTests(unittest.TestCase):
    def test_schema_version(self):
        self.assertEqual(event().schema_version, SCHEMA_VERSION)
        self.assertEqual(len(event().event_id), 32)

    def test_redaction(self):
        s = "token sk-abcdefghijklmnopqrstuvwxyz and ghp_abcdefghijklmnopqrstuvwxyz"
        self.assertNotIn("sk-abc", redact(s))
        self.assertIn("[REDACTED]", redact(s))

    def test_event_redacts_fields(self):
        e = event(message="key=sk-abcdefghijklmnopqrstuvwxyz",
                  metadata={"nested": {"password": "hunter22xxxx"}})
        self.assertNotIn("sk-abc", e.message)
        self.assertNotIn("hunter22xxxx", str(e.metadata))
        self.assertIn("[REDACTED]", str(e.metadata))

    def test_evidence_level(self):
        self.assertEqual(Evidence().level, "none")
        self.assertEqual(Evidence(claimed=True, implemented=True).level, "implemented")
        self.assertEqual(Evidence(verified=True, committed=True).level, "committed")
        self.assertEqual(Evidence(pushed=True).level, "pushed")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.store = Store(self.db)

    def tearDown(self):
        self.store.close()
        for suffix in ("", "-wal", "-shm"):
            Path(self.db + suffix).unlink(missing_ok=True)

    def test_dedupe_by_event_id(self):
        e = event()
        self.assertTrue(self.store.insert_event(e))
        self.assertFalse(self.store.insert_event(e))
        self.assertEqual(len(self.store.list_events("S1")), 1)

    def test_weighted_progress_not_elapsed_time(self):
        self.store.insert_event(event(event="task_plan", metadata={"tasks": [
            {"id": "a", "name": "A", "weight": 1, "status": "completed"},
            {"id": "b", "name": "B", "weight": 3, "status": "running"},
        ]}))
        self.store.insert_event(event(event="task_completed", metadata={"task_id": "b"}))
        snap = self.store.snapshot("S1")
        self.assertEqual(snap["overall"]["tasks_total"], 2)
        self.assertEqual(snap["overall"]["tasks_completed"], 2)
        self.assertEqual(snap["overall"]["progress"], 100.0)

    def test_evidence_and_attention(self):
        self.store.insert_event(event(
            event="task_completed", metadata={"task_id": "a"},
            evidence=Evidence(claimed=True, implemented=True, verified=True,
                              committed=True, commit="abc123")))
        self.store.insert_event(event(event="worker_blocked", status="blocked",
                                      message="needs a decision"))
        snap = self.store.snapshot("S1")
        self.assertTrue(snap["projects"][0]["verified"])
        self.assertTrue(snap["projects"][0]["committed"])
        self.assertEqual(snap["attention"][0]["level"], "critical")

    def test_replay_order(self):
        first = event(event="task_plan", metadata={"tasks": []})
        second = event(event="worker_started")
        self.store.insert_event(first)
        self.store.insert_event(second)
        timeline = self.store.replay("S1")["timeline"]
        self.assertEqual(timeline[0]["event"], "task_plan")
        self.assertEqual(len(timeline), 2)

    def test_control_record(self):
        c = self.store.set_control("S1", "worker-01", "pause", "discord")
        self.assertEqual(c["status"], "requested")
        self.assertEqual(len(self.store.snapshot("S1")["controls"]), 1)


class HealthTests(unittest.TestCase):
    def test_levels(self):
        now = datetime.now(timezone.utc)
        recent = now.isoformat()
        old = (now - timedelta(seconds=400)).isoformat()
        self.assertEqual(classify(recent, now=now)["level"], "healthy")
        self.assertEqual(classify(old, now=now)["level"], "stalled")
        self.assertEqual(classify(old, now=now, status="completed")["level"], "finished")
        self.assertEqual(classify(recent, now=now, status="blocked")["level"], "blocked")

    def test_never_auto_kills(self):
        self.assertIn("never auto-kill", classify(None)["action"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.old_db = os.environ.get("WORKFORCE_DB")
        os.environ["WORKFORCE_DB"] = self.db
        server._store = None
        self.client = TestClient(server.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        server._store = None
        for suffix in ("", "-wal", "-shm"):
            Path(self.db + suffix).unlink(missing_ok=True)
        if self.old_db is None:
            os.environ.pop("WORKFORCE_DB", None)
        else:
            os.environ["WORKFORCE_DB"] = self.old_db

    def test_ingest_snapshot_replay(self):
        e = event(event="task_plan", metadata={"tasks": [
            {"id": "a", "name": "A", "weight": 2, "status": "completed"}]})
        r = self.client.post("/events", json=e.model_dump(mode="json"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["accepted"])
        dup = self.client.post("/events", json=e.model_dump(mode="json"))
        self.assertTrue(dup.json()["duplicate"])
        snap = self.client.get("/api/sessions/S1").json()
        self.assertEqual(snap["overall"]["progress"], 100.0)
        self.assertEqual(len(self.client.get("/api/sessions/S1/replay").json()["timeline"]), 1)
        self.assertEqual(self.client.get("/api/health").json()["status"], "online")

    def test_control_endpoint(self):
        r = self.client.post("/api/sessions/S1/controls", json={
            "target": "W1", "action": "pause", "requested_by": "discord"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["action"], "pause")


if __name__ == "__main__":
    unittest.main()
