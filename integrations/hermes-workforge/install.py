#!/usr/bin/env python3
"""Install the Workforge unified plugin into a Hermes home.

Files only: nothing in Hermes core is edited, and no running process is
restarted. Enable it with the official CLI afterwards:

    python integrations/hermes-workforge/install.py
    hermes plugins enable hermes-workforge
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

NAME = "hermes-workforge"
SRC = Path(__file__).resolve().parent
FILES = (
    "plugin.yaml",
    "dashboard/manifest.json",
    "dashboard/plugin_api.py",
    "dashboard/dist/index.js",
    "dashboard/dist/style.css",
    "desktop/plugin.js",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        default=os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes"),
        help="Hermes home (defaults to $HERMES_HOME or ~/.hermes)",
    )
    parser.add_argument("--uninstall", action="store_true", help="remove the installed plugin folder")
    args = parser.parse_args()

    target = Path(args.home) / "plugins" / NAME
    if args.uninstall:
        if not target.exists():
            print(f"Nothing to uninstall at {target}")
            return
        shutil.rmtree(target)
        print(f"Removed {target}. Disable it with: hermes plugins disable {NAME}")
        return

    missing = [rel for rel in FILES if not (SRC / rel).is_file()]
    if missing:
        raise SystemExit(f"Refusing partial install; missing source files: {missing}")

    for rel in FILES:
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC / rel, dst)

    print(f"Installed {NAME} -> {target}")
    print(f"Enable it: hermes plugins enable {NAME}")
    print("Then rescan plugins in the dashboard / Desktop (no restart needed).")


if __name__ == "__main__":
    main()
