"""HERMES WORKFORGE - dashboard/desktop plugin backend.

A thin, read-mostly proxy to the local Workforge collector (default
http://127.0.0.1:8765). The collector remains the authoritative state owner:
this router never computes progress and never touches a worker process.
Controls are *requests* recorded by the collector's control endpoint.

Configuration: WORKFORCE_URL overrides the collector base URL.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Body, HTTPException

router = APIRouter()

COLLECTOR = os.environ.get("WORKFORCE_URL", "http://127.0.0.1:8765").rstrip("/")
TIMEOUT = 2.0
_ACTIONS = {"pause", "resume", "cancel", "approve"}


def _call(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        COLLECTOR + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise HTTPException(exc.code, exc.read().decode("utf-8", "replace")[:400]) from exc
    except Exception as exc:  # collector down must never take the dashboard down
        raise HTTPException(503, f"Workforge collector unreachable at {COLLECTOR}: {exc}") from exc


def _latest_id() -> str:
    snap = _call("GET", "/api/sessions/latest")
    sid = (snap.get("session") or {}).get("id")
    if not sid:
        raise HTTPException(404, "No Workforge session has reported events yet")
    return sid


@router.get("/status")
def status() -> dict[str, Any]:
    """Reachability probe. Never raises: the UI uses it to show an offline banner."""
    try:
        return {
            "reachable": True,
            "collector": COLLECTOR,
            "health": _call("GET", "/api/health"),
            "sessions": _call("GET", "/api/sessions"),
        }
    except HTTPException as exc:
        return {"reachable": False, "collector": COLLECTOR, "error": str(exc.detail)}


@router.get("/snapshot")
def snapshot(session: str | None = None) -> dict[str, Any]:
    sid = session or _latest_id()
    return _call("GET", f"/api/sessions/{urllib.parse.quote(sid, safe='')}")


@router.get("/events")
def events(limit: int = 60, session: str | None = None) -> list[dict[str, Any]]:
    sid = session or _latest_id()
    limit = max(1, min(int(limit), 500))
    return _call("GET", f"/api/sessions/{urllib.parse.quote(sid, safe='')}/events?limit={limit}")


@router.get("/attention")
def attention() -> list[dict[str, Any]]:
    return _call("GET", "/api/attention")


@router.post("/control")
def control(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Forward a control *request*. The orchestrator decides; this never kills anything."""
    action = str(body.get("action", "")).lower()
    if action not in _ACTIONS:
        raise HTTPException(400, f"action must be one of {sorted(_ACTIONS)}")
    sid = str(body.get("session") or _latest_id())
    target = str(body.get("target") or sid)
    return _call("POST", f"/api/sessions/{urllib.parse.quote(sid, safe='')}/controls", {
        "target": target,
        "action": action,
        "requested_by": str(body.get("requested_by") or "hermes-dashboard"),
    })
