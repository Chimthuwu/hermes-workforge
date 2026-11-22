"""Rich terminal Mission Control for HERMES WORKFORGE."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import time
from typing import Any

import httpx
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .models import SCHEMA_VERSION
from .storage import DEFAULT_DB

console = Console()
VIEWS = ["overview", "workers", "activity", "attention"]
STATUS_COLOR = {
    "running": "bold green", "completed": "bold cyan", "blocked": "bold yellow",
    "failed": "bold red", "queued": "dim",
}
HEALTH_COLOR = {
    "healthy": "green", "idle": "yellow", "investigate": "bold yellow",
    "stalled": "bold red", "blocked": "bold yellow", "finished": "dim",
}


def _get(url: str, path: str, timeout: float = 2.0) -> Any:
    return httpx.get(f"{url.rstrip('/')}{path}", timeout=timeout).json()


def _bar(pct: float, width: int = 24) -> str:
    filled = max(0, min(width, int(pct / 100 * width)))
    return "[cyan]" + "█" * filled + "[/cyan][dim]" + "░" * (width - filled) + "[/dim]"


def _status(value: str) -> str:
    color = STATUS_COLOR.get(value, "white")
    return f"[{color}]{value.upper()}[/{color}]"


def _header(snap: dict[str, Any]) -> Panel:
    o = snap.get("overall", {})
    s = snap.get("session") or {}
    body = Text.from_markup(
        f"[bold bright_white]SESSION[/] {s.get('id', '-')}   "
        f"[bold bright_white]PROJECTS[/] {o.get('projects_total', 0)}   "
        f"[bold bright_white]WORKERS[/] {o.get('workers_active', 0)}/{o.get('workers_total', 0)}   "
        f"[bold bright_white]TASKS[/] {o.get('tasks_completed', 0)}/{o.get('tasks_total', 0)}   "
        f"[bold bright_white]EVENTS[/] {o.get('events', 0)}\n"
        f"[dim]Progress (completed task weight)[/dim] {_bar(o.get('progress', 0))} "
        f"[bold cyan]{o.get('progress', 0)}%[/bold cyan]"
    )
    return Panel(body, title="[bold bright_blue]HERMES // WORKFORGE[/bold bright_blue]",
                 border_style="bright_blue", padding=(0, 1))


def _project_table(snap: dict[str, Any]) -> Table:
    t = Table(title="PROJECTS", box=None, expand=True, pad_edge=False)
    for c in ("PROJECT", "STATUS", "PROGRESS", "TASKS", "EVIDENCE", "ACTIVITY"):
        t.add_column(c, no_wrap=(c != "ACTIVITY"))
    for p in snap.get("projects", []):
        evidence = []
        if p.get("verified"):
            evidence.append("[green]V[/green]")
        if p.get("committed"):
            evidence.append("[cyan]C[/cyan]")
        if not evidence:
            evidence.append("[dim]-[/dim]")
        t.add_row(
            p["project_id"], _status(p["status"]),
            f"{p['progress']:>5.1f}%  {_bar(p['progress'], 8)}",
            f"{p['tasks_completed']}/{p['tasks_total']}",
            " ".join(evidence),
            (p.get("current_task") or "-")[:44],
        )
    if not snap.get("projects"):
        t.add_row("[dim]no projects yet[/dim]", "", "", "", "", "")
    return t


def _worker_table(snap: dict[str, Any]) -> Table:
    t = Table(title="WORKERS", box=None, expand=True, pad_edge=False)
    for c in ("WORKER", "PROJECT", "STATUS", "HEALTH", "TASK"):
        t.add_column(c, no_wrap=(c != "TASK"))
    for w in snap.get("workers", []):
        h = w.get("health", {})
        hc = HEALTH_COLOR.get(h.get("level"), "white")
        age = h.get("age_seconds", 0)
        t.add_row(
            w["worker_id"], w["project_id"], _status(w["status"]),
            f"[{hc}]{h.get('label', '?')}[/{hc}] [dim]{age}s[/dim]",
            (w.get("task") or "-")[:40],
        )
    if not snap.get("workers"):
        t.add_row("[dim]no workers yet[/dim]", "", "", "", "")
    return t


def _attention_panel(snap: dict[str, Any]) -> Panel:
    lines = []
    for a in snap.get("attention", [])[:5]:
        color = "bold red" if a["level"] == "critical" else "bold yellow"
        lines.append(
            f"[{color}]{a['level'].upper()}[/{color}] {a['project']}/{a['worker']} - {a['reason']}"
        )
    for c in snap.get("controls", [])[:3]:
        lines.append(f"[dim]CONTROL {c['action']} -> {c['target']} ({c['status']})[/dim]")
    if not lines:
        lines.append("[green]All clear. No blockers, no stalled workers.[/green]")
    return Panel("\n".join(lines), title="ATTENTION", border_style="yellow")


def _event_table(events: list[dict[str, Any]]) -> Table:
    t = Table(title="LIVE EVENT STREAM", box=None, expand=True, pad_edge=False)
    for c in ("TIME", "PROJECT", "EVENT", "STATUS", "MESSAGE"):
        t.add_column(c, no_wrap=(c != "MESSAGE"))
    for e in events[:16]:
        ts = str(e.get("timestamp", ""))[11:19]
        msg = e.get("message") or e.get("task") or "-"
        t.add_row(ts, e.get("project_id", ""), e.get("event", ""),
                  _status(e.get("status", "running")), str(msg)[:60])
    if not events:
        t.add_row("[dim]waiting for first event...[/dim]", "", "", "", "")
    return t


def build(snap: dict[str, Any], view: str = "overview",
          events: list[dict[str, Any]] | None = None) -> Layout:
    events = events or []
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=5),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["header"].update(_header(snap))
    if view == "activity":
        layout["body"].update(Panel(_event_table(events), border_style="bright_black"))
    elif view == "attention":
        layout["body"].update(Panel(_attention_panel(snap), border_style="yellow"))
    elif view == "workers":
        layout["body"].update(Panel(_worker_table(snap), border_style="bright_blue"))
    else:
        body = Layout()
        body.split_row(Layout(_project_table(snap), name="projects", ratio=3),
                       Layout(name="side", ratio=2))
        side = Layout()
        side.split_column(Layout(Panel(_worker_table(snap), border_style="bright_blue"),
                                 ratio=2),
                          Layout(_attention_panel(snap), ratio=1))
        body["side"].update(side)
        layout["body"].update(body)
    labels = "  ".join(
        f"[cyan]{i}[/cyan]:{v.upper()}" if v == view else f"[dim]{i}:{v.upper()}[/dim]"
        for i, v in enumerate(VIEWS, 1)
    )
    layout["footer"].update(Panel(
        f"{labels}   [dim]|[/dim] [red]Q[/red]:quit  [dim]|[/dim] schema v{SCHEMA_VERSION}",
        border_style="dim", padding=(0, 1)))
    return layout


def _key_reader(state: dict[str, Any]) -> None:
    def handle(ch: str) -> None:
        if ch in ("q", "Q"):
            state["quit"] = True
        elif ch in ("1", "2", "3", "4"):
            state["view"] = VIEWS[int(ch) - 1]
            state["refresh"] = True
        elif ch in ("r", "R"):
            state["refresh"] = True

    if sys.platform == "win32":
        try:
            import msvcrt
            while not state["quit"]:
                if msvcrt.kbhit():
                    handle(msvcrt.getwch())
                else:
                    time.sleep(0.1)
        except Exception:
            pass
    else:
        try:
            import select
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setraw(fd)
            try:
                while not state["quit"]:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        handle(sys.stdin.read(1))
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass


def cmd_monitor(args: argparse.Namespace) -> int:
    url = args.url
    view = args.view if args.view in VIEWS else "overview"
    state = {"view": view, "quit": False, "refresh": False}
    if args.keys:
        threading.Thread(target=_key_reader, args=(state,), daemon=True).start()
    session_path = "latest" if not args.session else args.session
    screen = sys.stdout.isatty()
    try:
        with Live(console=console, refresh_per_second=4, screen=screen) as live:
            while not state["quit"]:
                try:
                    snap = _get(url, f"/api/sessions/{session_path}")
                    events = _get(url, "/api/sessions/" +
                                  (snap.get("session", {}).get("id") or "latest") +
                                  "/events?limit=16")
                    live.update(build(snap, state["view"], events))
                except Exception as exc:
                    live.update(Panel(
                        f"[bold red]Collector unreachable[/bold red] at {url}\n"
                        f"[dim]{exc}[/dim]\n\nStart it with: [cyan]workforge serve[/cyan]",
                        border_style="red"))
                state["refresh"] = False
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    try:
        path = "latest" if not args.session else args.session
        snap = _get(args.url, f"/api/sessions/{path}")
        events = _get(args.url, "/api/sessions/" +
                      (snap.get("session", {}).get("id") or "latest") + "/events?limit=16")
        console.print(build(snap, "overview", events))
    except Exception as exc:
        console.print(f"[red]Could not reach {args.url}: {exc}[/red]")
        return 1
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    try:
        data = _get(args.url, f"/api/sessions/{args.session}/replay")
    except Exception as exc:
        console.print(f"[red]Replay failed: {exc}[/red]")
        return 1
    t = Table(title=f"SESSION REPLAY - {data['session_id']} "
                    f"({data['event_count']} events)", box=None)
    for c in ("#", "TIME", "PROJECT", "EVENT", "STATUS", "MESSAGE", "EVIDENCE"):
        t.add_column(c, no_wrap=(c not in ("MESSAGE",)))
    for i, e in enumerate(data["timeline"][:args.limit], 1):
        t.add_row(str(i), str(e["t"])[11:19], e["project"], e["event"],
                  _status(e["status"]), str(e["message"] or e["task"] or "-")[:52],
                  e["evidence_level"] or "-")
    console.print(Panel(t, border_style="magenta"))
    return 0


def cmd_discord(args: argparse.Namespace) -> int:
    from .adapters.discord import MissionControlBot

    if not args.dry_run and not os.environ.get("WORKFORCE_DISCORD_TOKEN"):
        console.print("[red]WORKFORCE_DISCORD_TOKEN is not set.[/red] "
                      "Set it in the bot's environment, or use [cyan]--dry-run[/cyan] "
                      "to verify with no credentials. Never paste a token in chat.")
        return 1
    bot = MissionControlBot(
        url=args.url, channel_id=args.channel_id, session_id=args.session,
        batch_seconds=args.batch, dry_run=args.dry_run)
    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    import importlib.metadata as md
    console.print("[bold bright_blue]HERMES WORKFORGE // DOCTOR[/bold bright_blue]")
    console.print(f"  version       : {__version__}")
    console.print(f"  schema        : v{SCHEMA_VERSION}")
    console.print(f"  python        : {sys.version.split()[0]}")
    for pkg in ("fastapi", "pydantic", "rich", "httpx", "websockets", "uvicorn"):
        try:
            console.print(f"  {pkg:<14}: {md.version(pkg)}")
        except Exception:
            console.print(f"  {pkg:<14}: [red]MISSING[/red]")
    console.print(f"  database      : {os.environ.get('WORKFORCE_DB', DEFAULT_DB)}")
    try:
        h = _get(args.url, "/api/health")
        console.print(f"  collector     : [green]online[/green] ({h['db']})")
    except Exception as exc:
        console.print(f"  collector     : [yellow]offline[/yellow] ({exc})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="workforge",
        description="HERMES WORKFORGE - cross-platform observability for autonomous AI work",
    )
    p.add_argument("--version", action="version", version=f"workforge {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="start the local event collector")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--db", default=None)
    s.set_defaults(func=lambda a: __import__("workforce.server", fromlist=["serve"])
                   .serve(a.host, a.port, a.db))

    s = sub.add_parser("monitor", help="live terminal mission control")
    s.add_argument("--session", default=None)
    s.add_argument("--url", default="http://127.0.0.1:8765")
    s.add_argument("--interval", type=float, default=1.5)
    s.add_argument("--view", default="overview", choices=VIEWS)
    s.add_argument("--no-keys", dest="keys", action="store_false")
    s.set_defaults(keys=True, func=cmd_monitor)

    s = sub.add_parser("snapshot", help="one-shot dashboard")
    s.add_argument("--session", default=None)
    s.add_argument("--url", default="http://127.0.0.1:8765")
    s.set_defaults(func=cmd_snapshot)

    s = sub.add_parser("replay", help="scrub a completed session's event timeline")
    s.add_argument("session")
    s.add_argument("--url", default="http://127.0.0.1:8765")
    s.add_argument("--limit", type=int, default=80)
    s.set_defaults(func=cmd_replay)

    s = sub.add_parser("discord", help="run the Discord adapter for the existing bot")
    s.add_argument("--url", default="http://127.0.0.1:8765")
    s.add_argument("--channel-id", default=None,
                   help="Discord channel ID (or WORKFORCE_DISCORD_CHANNEL_ID)")
    s.add_argument("--session", default=None)
    s.add_argument("--batch", type=float, default=2.0, help="embed edit debounce in seconds")
    s.add_argument("--dry-run", action="store_true",
                   help="verify the full adapter with no token and no second bot")
    s.set_defaults(func=cmd_discord)

    s = sub.add_parser("doctor", help="check install and collector connectivity")
    s.add_argument("--url", default="http://127.0.0.1:8765")
    s.set_defaults(func=cmd_doctor)

    args = p.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
