"""Fire a realistic multi-project run into a local Workforge collector.

    workforge serve                       # terminal 1
    python examples/demo_session.py       # terminal 2
    workforge monitor                     # terminal 3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workforce.events import EventReporter
from workforce.models import Evidence

SESSION = "DEMO-MULTI-001"

PROJECTS = [
    ("SydForge", "worker-01", True),
    ("Terraria3D", "worker-02", True),
    ("SkinsOS", "worker-03", True),
    ("GameVolley", "worker-04", True),
    ("Fruitbat", "worker-05", False),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--fast", action="store_true", help="no delays")
    args = ap.parse_args()
    delay = 0.0 if args.fast else 0.35

    for project, worker, succeeds in PROJECTS:
        r = EventReporter(endpoint=args.url, session_id=SESSION,
                          project_id=project, worker_id=worker)
        tasks = [
            {"id": "t1", "name": "Inspect existing systems", "weight": 1, "status": "completed"},
            {"id": "t2", "name": "Implement changes", "weight": 3, "status": "running"},
            {"id": "t3", "name": "Verify and commit", "weight": 2, "status": "queued"},
        ]
        r.emit("worker_started", "running", task="Audit current implementation",
               message=f"{project} worker online")
        time.sleep(delay)
        r.emit("task_plan", "running", message="Plan: 3 tasks", metadata={"tasks": tasks})
        time.sleep(delay)
        r.emit("discovery_completed", "running", task="Inspect existing systems",
               message=f"{project}: mapped 4 subsystems")
        time.sleep(delay)
        r.emit("file_modified", "running", task="Implement changes",
               message=f"{project}: 3 files modified",
               metadata={"files": [f"src/{project.lower()}/core.js"]})
        time.sleep(delay)
        r.emit("task_completed", "running", task="Implement changes",
               message=f"{project}: implementation done", metadata={"task_id": "t2"},
               evidence=Evidence(claimed=True, implemented=True, files_changed=3))
        time.sleep(delay)
        r.heartbeat(task="Verify and commit")
        time.sleep(delay)

        if succeeds:
            r.emit("test_passed", "running", task="Verify and commit",
                   message=f"{project}: 18 tests passed",
                   evidence=Evidence(verified=True, tests_passed=18, files_changed=3,
                                     implemented=True, claimed=True))
            time.sleep(delay)
            r.emit("commit_created", "running", task="Verify and commit",
                   message=f"{project}: committed a82c91f",
                   evidence=Evidence(verified=True, committed=True, implemented=True,
                                     claimed=True, tests_passed=18, files_changed=3,
                                     commit="a82c91f"))
            time.sleep(delay)
            r.emit("task_completed", "running", task="Verify and commit",
                   message=f"{project}: task t3 complete", metadata={"task_id": "t3"},
                   evidence=Evidence(verified=True, committed=True, pushed=True,
                                     implemented=True, claimed=True, tests_passed=18,
                                     files_changed=3, commit="a82c91f"))
            time.sleep(delay)
            r.emit("worker_completed", "completed", message=f"{project}: done")
        else:
            r.emit("worker_blocked", "blocked", task="Implement changes",
                   message=f"{project}: awaiting dependency decision")
        time.sleep(delay)

    r = EventReporter(endpoint=args.url, session_id=SESSION,
                      project_id="Fruitbat", worker_id="worker-05")
    r.emit("attention_required", "blocked",
           message="Fruitbat blocked: dependency investigation needed")
    print(f"Demo session {SESSION} emitted. Run: workforge monitor --session {SESSION}")


if __name__ == "__main__":
    main()
