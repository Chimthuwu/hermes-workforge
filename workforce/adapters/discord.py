"""Discord adapter for the existing Ame bot channel.

One aggregate consumer of the Workforge event stream:
  - a persistent mission-control message, edited in place (message ID stored collector-side)
  - attention-priority pushes for critical events; routine events go to a project thread
  - slash commands that read the same snapshot the CLI sees
  - reconnect + backoff; a Discord outage never affects workers or the collector

Run with a bot token in WORKFORCE_DISCORD_TOKEN and a channel in WORKFORCE_DISCORD_CHANNEL_ID:
    workforge discord --channel-id 123456789

Verify without credentials or a second bot:
    workforge discord --dry-run --seconds 8
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
import websockets

PUSH_EVENTS = {
    "worker_blocked", "worker_failed", "test_failed", "attention_required",
    "approval_required", "push_failed", "task_failed",
}
PUSH_STATUSES = {"blocked", "failed"}
COLORS = {"green": 0x22C55E, "yellow": 0xEAB308, "red": 0xEF4444, "blue": 0x38BDF8}


def should_push(event: dict[str, Any]) -> bool:
    """Critical events and approvals interrupt; everything else stays in the timeline."""
    return event.get("event") in PUSH_EVENTS or event.get("status") in PUSH_STATUSES


def build_embed(snap: dict[str, Any]) -> dict[str, Any]:
    """Build a Discord embed payload from the authoritative collector snapshot."""
    o = snap.get("overall", {})
    s = snap.get("session") or {}
    attention = snap.get("attention", [])
    color = COLORS["red"] if any(a["level"] == "critical" for a in attention) else (
        COLORS["yellow"] if attention else COLORS["green"])
    projects = sorted(snap.get("projects", []), key=lambda p: p["project_id"])
    lines = []
    for p in projects[:10]:
        mark = "🔴" if p["status"] in ("blocked", "failed") else (
            "🟢" if p["status"] == "completed" else "🟡")
        evidence = []
        if p.get("verified"):
            evidence.append("verified")
        if p.get("committed"):
            evidence.append(p.get("commit") or "committed")
        lines.append(
            f"{mark} **{p['project_id']}** — {p['status'].upper()} · {p['progress']:.0f}% · "
            f"{p['tasks_completed']}/{p['tasks_total']} tasks"
            + (f" · {', '.join(evidence)}" if evidence else "")
            + (f"\n   _{(p.get('current_task') or '')[:70]}_" if p.get("current_task") else "")
        )
    fields = [{"name": "PROJECTS", "value": "\n".join(lines) or "_no projects yet_",
               "inline": False}]
    if attention:
        fields.append({
            "name": f"ATTENTION ({len(attention)})",
            "value": "\n".join(
                f"**{a['level'].upper()}** {a['project']}/{a['worker']} — {a['reason']}"
                for a in attention[:5]),
            "inline": False,
        })
    recent = snap.get("latest_events", [])[:4]
    if recent:
        fields.append({
            "name": "LATEST",
            "value": "\n".join(f"`{str(e.get('timestamp', ''))[11:19]}` "
                               f"{e.get('project_id')} — {str(e.get('message') or e.get('event'))[:80]}"
                               for e in recent),
            "inline": False,
        })
    return {
        "title": "HERMES // MISSION CONTROL",
        "color": color,
        "description": (
            f"Session `{s.get('id', '-')}` · workers "
            f"{o.get('workers_active', 0)}/{o.get('workers_total', 0)} · "
            f"tasks {o.get('tasks_completed', 0)}/{o.get('tasks_total', 0)} · "
            f"events {o.get('events', 0)}\n"
            f"**Overall: {o.get('progress', 0):.1f}%** "
            f"(completed task weight)"
        ),
        "fields": fields,
        "footer": {"text": "Workforge · evidence-based progress · observer, not owner"},
    }


def detail_text(event: dict[str, Any]) -> str:
    ts = str(event.get("timestamp", ""))[11:19]
    bits = [f"`{ts}`", f"**{event.get('project_id')}**/{event.get('worker_id')}",
            f"`{event.get('event')}`"]
    if event.get("task"):
        bits.append(f"task: {event['task']}")
    if event.get("message"):
        bits.append(str(event["message"]))
    return " — ".join(bits)


class _FakeMessage:
    def __init__(self, sink: list[dict[str, Any]], mid: str):
        self.id = mid
        self._sink = sink

    async def edit(self, embed: Any = None, **kwargs: Any) -> None:
        self._sink.append({"op": "edit", "embed": _plain(embed)})

    async def create_thread(self, name: str, **kwargs: Any) -> "_FakeMessage":
        self._sink.append({"op": "thread", "name": name})
        return _FakeMessage(self._sink, "thread-" + name)

    async def send(self, content: str | None = None, **kwargs: Any) -> None:
        self._sink.append({"op": "thread_msg", "content": content})


class _FakeChannel:
    def __init__(self, sink: list[dict[str, Any]]):
        self._sink = sink
        self._n = 0

    async def send(self, content: str | None = None, embed: Any = None, **kwargs: Any):
        self._n += 1
        msg = _FakeMessage(self._sink, f"msg-{self._n}")
        self._sink.append({"op": "send", "content": content, "embed": _plain(embed),
                           "id": msg.id})
        return msg

    async def fetch_message(self, message_id: int | str):
        return _FakeMessage(self._sink, str(message_id))


def _plain(embed: Any) -> dict[str, Any] | None:
    if embed is None:
        return None
    if isinstance(embed, dict):
        return embed
    return {"title": getattr(embed, "title", None),
            "description": getattr(embed, "description", None)}


class MissionControlBot:
    def __init__(
        self,
        url: str = "http://127.0.0.1:8765",
        token: str | None = None,
        channel_id: str | None = None,
        session_id: str | None = None,
        batch_seconds: float = 2.0,
        dry_run: bool = False,
    ) -> None:
        self.url = url.rstrip("/")
        self.ws_url = self.url.replace("http://", "ws://").replace("https://", "wss://")
        self.token = token or os.environ.get("WORKFORCE_DISCORD_TOKEN")
        self.channel_id = channel_id or os.environ.get("WORKFORCE_DISCORD_CHANNEL_ID")
        self.session_id = session_id
        self.batch_seconds = batch_seconds
        self.dry_run = dry_run
        self.sink: list[dict[str, Any]] = []
        self.channel: Any = _FakeChannel(self.sink) if dry_run else None
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.dirty = False
        self.threads: dict[str, Any] = {}
        self.dashboard_message: Any = None
        self._resolved: str | None = None
        self.stats = {"events": 0, "edits": 0, "pushes": 0, "threads": 0}
        self.client: Any = None

    # -- collector API ---------------------------------------------------
    def _api(self, path: str, method: str = "get", payload: dict | None = None) -> Any:
        try:
            if method == "put":
                r = httpx.put(f"{self.url}{path}", json=payload, timeout=3)
            elif method == "post":
                r = httpx.post(f"{self.url}{path}", json=payload, timeout=3)
            else:
                r = httpx.get(f"{self.url}{path}", timeout=3)
            return r.json() if r.status_code < 400 else None
        except Exception:
            return None

    def _session(self) -> str:
        """Concrete session ID for REST calls; 'latest' only if none exists yet."""
        if self.session_id:
            return self.session_id
        if self._resolved:
            return self._resolved
        snap = self._api("/api/sessions/latest") or {}
        found = (snap.get("session") or {}).get("id")
        if found:
            self._resolved = found
        return self._resolved or "latest"

    def _stream_session(self) -> str | None:
        """WebSocket subscribe target. None = all sessions (no accidental filter)."""
        if self.session_id:
            return self.session_id
        snap = self._api("/api/sessions/latest") or {}
        return (snap.get("session") or {}).get("id") or None

    # -- event loop ------------------------------------------------------
    async def stream_loop(self) -> None:
        while True:
            try:
                sid = self._stream_session()
                url = f"{self.ws_url}/stream" + (f"?session_id={sid}" if sid else "")
                async with websockets.connect(url) as ws:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        if msg.get("type") == "event":
                            self.on_event(msg)
                        elif msg.get("type") == "ping":
                            continue
            except Exception:
                await asyncio.sleep(5)  # collector outage never stops workers

    def on_event(self, event: dict[str, Any]) -> None:
        self.stats["events"] += 1
        self.pending.append(("push" if should_push(event) else "detail", event))
        self.dirty = True

    async def flush_once(self) -> None:
        """Drain the batch. Also used on shutdown so no event is left behind."""
        if not self.pending:
            return
        batch = self.pending[:]
        self.pending.clear()
        self.dirty = False
        sid = self._session()
        snap = self._api(f"/api/sessions/{sid}") or {}
        await self.update_dashboard(sid, snap)
        for kind, event in batch:
            if kind == "push":
                await self.notify(event)
            else:
                await self.to_thread(event)

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.batch_seconds)
            await self.flush_once()

    async def update_dashboard(self, sid: str, snap: dict[str, Any]) -> None:
        embed = build_embed(snap)
        if self.dry_run:
            embed_obj = embed  # no discord.py needed for verification mode
        else:
            import discord  # optional dependency, only needed for a live run
            embed_obj = discord.Embed.from_dict(embed)

        records = self._api(f"/api/sessions/{sid}/platform-messages") or []
        rec = next((r for r in records if r.get("platform") == "discord"), None)
        if rec and rec.get("message_id"):
            try:
                try:
                    mid: Any = int(rec["message_id"])
                except (TypeError, ValueError):
                    mid = rec["message_id"]  # dry-run fake IDs are strings
                msg = await self.channel.fetch_message(mid)
                await msg.edit(embed=embed_obj)
                self.dashboard_message = msg
                self.stats["edits"] += 1
                return
            except Exception:
                rec = None
        msg = await self.channel.send(embed=embed_obj)
        self.dashboard_message = msg
        self._api(f"/api/sessions/{sid}/platform-messages", "put", {
            "platform": "discord", "message_id": str(msg.id), "thread_id": None})
        self.stats["edits"] += 1

    async def notify(self, event: dict[str, Any]) -> None:
        content = f"🚨 **WORKFORGE ATTENTION** — {detail_text(event)}"
        await self.channel.send(content=content)
        self.stats["pushes"] += 1

    async def to_thread(self, event: dict[str, Any]) -> None:
        project = event.get("project_id") or "general"
        if project not in self.threads:
            if self.dashboard_message is not None:
                try:
                    self.threads[project] = await self.dashboard_message.create_thread(
                        name=f"WF · {project}"[:100])
                except Exception:
                    return
            else:
                return
        try:
            await self.threads[project].send(content=detail_text(event))
            self.stats["threads"] += 1
        except Exception:
            pass

    # -- live bot --------------------------------------------------------
    async def start(self) -> None:
        if self.dry_run:
            await self.dry_run_for(self.batch_seconds * 3)
            return
        if not self.token or not self.channel_id:
            raise RuntimeError(
                "Set WORKFORCE_DISCORD_TOKEN and WORKFORCE_DISCORD_CHANNEL_ID "
                "(or use --channel-id / --dry-run). Never paste a token in chat.")
        import discord

        intents = discord.Intents.default()
        client = discord.Client(intents=intents)
        self.client = client
        tree = discord.app_commands.CommandTree(client)
        self.register_commands(tree)

        @client.event
        async def on_ready() -> None:
            self.channel = (client.get_channel(int(self.channel_id))
                            or await client.fetch_channel(int(self.channel_id)))
            try:
                await tree.sync()  # register slash commands with Discord
            except Exception:
                pass  # transient sync failure must not stop monitoring
            asyncio.create_task(self.stream_loop())
            asyncio.create_task(self.flush_loop())
            print("Workforge Discord adapter connected", flush=True)

        await client.start(self.token)

    def register_commands(self, tree: Any) -> None:
        import discord  # noqa: F401 - required by the command decorators at runtime
        bot = self

        def snap() -> dict[str, Any]:
            return bot._api(f"/api/sessions/{bot._session()}") or {}

        @tree.command(name="mission", description="Current Workforge mission status")
        async def mission(interaction: Any) -> None:
            embed = discord.Embed.from_dict(build_embed(snap()))
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @tree.command(name="workers", description="All running workers")
        async def workers(interaction: Any) -> None:
            rows = [f"{w['worker_id']} · {w['project_id']} · {w['status'].upper()} · "
                    f"{w.get('health', {}).get('label', '?')}"
                    for w in snap().get("workers", [])]
            await interaction.response.send_message(
                "\n".join(rows) or "_no workers_", ephemeral=True)

        @tree.command(name="attention", description="Blocked, failed and stalled workers")
        async def attention(interaction: Any) -> None:
            rows = [f"**{a['level'].upper()}** {a['project']}/{a['worker']} — {a['reason']}"
                    for a in snap().get("attention", [])]
            await interaction.response.send_message(
                "\n".join(rows) or "_all clear_", ephemeral=True)

        @tree.command(name="logs", description="Recent Workforge events")
        async def logs(interaction: Any) -> None:
            sid = bot._session()
            events = bot._api(f"/api/sessions/{sid}/events?limit=10") or []
            await interaction.response.send_message(
                "\n".join(detail_text(e) for e in events) or "_no events_", ephemeral=True)

        @tree.command(name="control", description="Request pause/resume/cancel on a worker")
        async def control(interaction: Any, worker: str, action: str) -> None:
            if action not in ("pause", "resume", "cancel"):
                await interaction.response.send_message(
                    "action must be pause, resume or cancel", ephemeral=True)
                return
            result = bot._api(f"/api/sessions/{bot._session()}/controls", "post", {
                "target": worker, "action": action, "requested_by": "discord"})
            await interaction.response.send_message(
                f"Control request **{action}** for `{worker}`: "
                f"{'sent' if result else 'collector unreachable'}. "
                "The orchestrator decides; no process is killed directly.", ephemeral=True)

    async def dry_run_for(self, seconds: float) -> None:
        """Exercise the full adapter against a live collector, no token needed."""
        asyncio.create_task(self.stream_loop())
        asyncio.create_task(self.flush_loop())
        await asyncio.sleep(seconds)
        await self.flush_once()  # never leave the last batch (often the alerts) unprocessed
        print(json.dumps({
            "mode": "dry-run", "session": self._session(), "stats": self.stats,
            "operations": self.sink[:12],
        }, indent=2, default=str))
