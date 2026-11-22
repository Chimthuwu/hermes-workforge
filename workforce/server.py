"""FastAPI collector: one event stream feeding CLI, Discord, Web and Desktop."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .models import SCHEMA_VERSION, WorkerEvent, utcnow
from .storage import DEFAULT_DB, Store

_subscribers: set[asyncio.Queue] = set()
_store: Store | None = None


def get_store() -> Store:
    global _store
    path = os.environ.get("WORKFORCE_DB", DEFAULT_DB)
    if _store is None or _store.path != str(path):
        if _store is not None:
            _store.close()
        _store = Store(path)
    return _store


def broadcast(payload: dict[str, Any]) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(payload)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass


class ControlRequest(BaseModel):
    target: str
    action: str = Field(pattern="^(pause|resume|cancel|approve)$")
    requested_by: str = "api"


class PlanRequest(BaseModel):
    tasks: list[dict[str, Any]]
    project_id: str


class PlatformMessageRequest(BaseModel):
    platform: str = "discord"
    message_id: str
    thread_id: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_store()
    yield
    global _store
    if _store is not None:
        _store.close()
        _store = None


app = FastAPI(
    title="HERMES WORKFORGE",
    description="Shared observability core for autonomous AI work",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:*", "http://localhost:*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/events")
async def receive_event(event: WorkerEvent) -> dict[str, Any]:
    accepted = get_store().insert_event(event)
    payload = event.model_dump(mode="json")
    payload["type"] = "event"
    if accepted:
        broadcast(payload)
    return {"accepted": accepted, "event_id": event.event_id,
            "duplicate": not accepted, "schema_version": SCHEMA_VERSION}


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "online", "service": "hermes-workforge",
            "version": "0.1.0", "schema_version": SCHEMA_VERSION,
            "db": get_store().path, "subscribers": len(_subscribers)}


@app.websocket("/stream")
async def event_stream(ws: WebSocket, session_id: str | None = None) -> None:
    if session_id == "latest":
        session_id = None
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    try:
        history = get_store().list_events(session_id, limit=100)
        await ws.send_json({
            "type": "history",
            "events": [e.model_dump(mode="json") for e in reversed(history)],
            "session_id": session_id,
        })
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15)
                if session_id and msg.get("session_id") != session_id:
                    continue
                await ws.send_json(msg)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping", "timestamp": utcnow().isoformat()})
    except WebSocketDisconnect:
        pass
    finally:
        _subscribers.discard(q)


@app.get("/api/sessions")
async def sessions() -> list[dict[str, Any]]:
    return get_store().list_sessions()


@app.get("/api/sessions/latest")
async def latest_snapshot() -> dict[str, Any]:
    return get_store().snapshot()


@app.get("/api/sessions/{session_id}")
async def snapshot(session_id: str) -> dict[str, Any]:
    return get_store().snapshot(session_id)


@app.get("/api/sessions/{session_id}/events")
async def events(session_id: str, limit: int = 100, since: str | None = None) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in
            get_store().list_events(session_id, limit=limit, since=since)]


@app.get("/api/sessions/{session_id}/replay")
async def replay(session_id: str) -> dict[str, Any]:
    return get_store().replay(session_id)


@app.post("/api/sessions/{session_id}/plan")
async def set_plan(session_id: str, body: PlanRequest) -> dict[str, Any]:
    store = get_store()
    for task in body.tasks:
        store.set_task(session_id, body.project_id, task)
    return {"session_id": session_id, "project_id": body.project_id,
            "tasks": len(body.tasks)}


@app.post("/api/sessions/{session_id}/controls")
async def control(session_id: str, body: ControlRequest) -> dict[str, Any]:
    return get_store().set_control(session_id, body.target, body.action, body.requested_by)


@app.get("/api/sessions/{session_id}/controls")
async def controls(session_id: str) -> dict[str, Any]:
    return get_store().snapshot(session_id).get("controls", [])


@app.get("/api/sessions/{session_id}/platform-messages")
async def platform_messages(session_id: str) -> list[dict[str, Any]]:
    return get_store().get_platform_messages(session_id)


@app.put("/api/sessions/{session_id}/platform-messages")
async def remember_platform_message(session_id: str,
                                    body: PlatformMessageRequest) -> dict[str, Any]:
    get_store().set_platform_message(session_id, body.platform, body.message_id,
                                     body.thread_id)
    return {"session_id": session_id, "platform": body.platform,
            "message_id": body.message_id, "thread_id": body.thread_id}


@app.get("/api/attention")
async def attention() -> list[dict[str, Any]]:
    return get_store().snapshot().get("attention", [])


def serve(host: str = "127.0.0.1", port: int = 8765, db: str | None = None) -> None:
    import uvicorn

    if db:
        os.environ["WORKFORCE_DB"] = db
    Path(os.environ.get("WORKFORCE_DB", DEFAULT_DB)).parent.mkdir(parents=True, exist_ok=True)
    uvicorn.run("workforce.server:app", host=host, port=port, log_level="info")
