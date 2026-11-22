"""Discord adapter tests - no token, no second bot, no discord.py required."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from workforce import server
from workforce.adapters.discord import (
    MissionControlBot, build_embed, detail_text, should_push,
)

SNAP = {
    "session": {"id": "S1"},
    "overall": {"progress": 62.5, "workers_active": 1, "workers_total": 2,
                "tasks_completed": 5, "tasks_total": 8, "events": 21,
                "projects_total": 2},
    "projects": [
        {"project_id": "SydForge", "status": "completed", "progress": 100.0,
         "tasks_completed": 3, "tasks_total": 3, "verified": True,
         "committed": True, "commit": "a82c91f", "current_task": "done"},
        {"project_id": "Fruitbat", "status": "blocked", "progress": 25.0,
         "tasks_completed": 0, "tasks_total": 2, "verified": False,
         "committed": False, "current_task": "awaiting dependency"},
    ],
    "attention": [{"level": "critical", "project": "Fruitbat", "worker": "worker-02",
                   "reason": "status=blocked", "action": "investigate"}],
    "latest_events": [{"timestamp": "2026-11-23T00:28:14Z", "project_id": "Fruitbat",
                       "event": "worker_blocked", "message": "needs a decision"}],
}


class EmbedTests(unittest.TestCase):
    def test_build_embed(self):
        e = build_embed(SNAP)
        self.assertEqual(e["title"], "HERMES // MISSION CONTROL")
        self.assertIn("62.5%", e["description"])
        self.assertIn("SydForge", e["fields"][0]["value"])
        self.assertIn("ATTENTION", e["fields"][1]["name"])
        self.assertEqual(e["color"], 0xEF4444)

    def test_priority_routing(self):
        self.assertTrue(should_push({"event": "worker_blocked", "status": "blocked"}))
        self.assertTrue(should_push({"event": "commit_created", "status": "failed"}))
        self.assertFalse(should_push({"event": "file_modified", "status": "running"}))

    def test_detail_text(self):
        text = detail_text({"timestamp": "2026-11-23T00:28:14Z", "project_id": "P",
                            "worker_id": "W", "event": "test_failed",
                            "message": "2 failed"})
        self.assertIn("00:28:14", text)
        self.assertIn("test_failed", text)
        self.assertIn("2 failed", text)


class AdapterTests(unittest.TestCase):
    def test_dry_run_needs_no_token_and_no_discord_py(self):
        bot = MissionControlBot(dry_run=True)
        self.assertIsNotNone(bot.channel)
        bot.on_event({"event": "worker_blocked", "status": "blocked",
                      "project_id": "Fruitbat"})
        bot.on_event({"event": "file_modified", "status": "running",
                      "project_id": "SydForge"})
        self.assertEqual(bot.stats["events"], 2)
        self.assertEqual([k for k, _ in bot.pending], ["push", "detail"])

        bot._api = lambda *a, **k: (
            [{"platform": "discord", "message_id": "12345"}]
            if "platform-messages" in a[0] else SNAP)
        asyncio.run(bot.update_dashboard("S1", SNAP))
        asyncio.run(bot.notify({"event": "attention_required", "status": "blocked",
                                "message": "needs a decision"}))
        self.assertEqual(bot.stats["edits"], 1)
        self.assertEqual(bot.stats["pushes"], 1)
        self.assertIn("edit", [o["op"] for o in bot.sink])
        self.assertIn("send", [o["op"] for o in bot.sink])


class PlatformMessageApiTests(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".db")
        self.old = os.environ.get("WORKFORCE_DB")
        os.environ["WORKFORCE_DB"] = self.db
        server._store = None
        self.client = TestClient(server.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        server._store = None
        for s in ("", "-wal", "-shm"):
            Path(self.db + s).unlink(missing_ok=True)
        if self.old is None:
            os.environ.pop("WORKFORCE_DB", None)
        else:
            os.environ["WORKFORCE_DB"] = self.old

    def test_remember_dashboard_message(self):
        self.assertEqual(self.client.get("/api/sessions/S1/platform-messages").json(), [])
        r = self.client.put("/api/sessions/S1/platform-messages", json={
            "platform": "discord", "message_id": "12345", "thread_id": "67890"})
        self.assertEqual(r.status_code, 200)
        rec = self.client.get("/api/sessions/S1/platform-messages").json()[0]
        self.assertEqual(rec["message_id"], "12345")
        self.assertEqual(rec["thread_id"], "67890")
        self.client.put("/api/sessions/S1/platform-messages", json={
            "platform": "discord", "message_id": "99999"})
        rec = self.client.get("/api/sessions/S1/platform-messages").json()[0]
        self.assertEqual(rec["message_id"], "99999")  # updated in place, not duplicated


if __name__ == "__main__":
    unittest.main()
