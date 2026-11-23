"""Static contract tests for the Hermes unified plugin package.

No Hermes install, token or running dashboard required: these guard the pieces
that must line up (plugin id, SDK namespaces, allowed import surface) so a
future edit cannot silently break either interface.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "integrations" / "hermes-workforge"


class HermesIntegrationTests(unittest.TestCase):
    def test_ids_match_everywhere(self) -> None:
        manifest = json.loads((PKG / "dashboard/manifest.json").read_text(encoding="utf-8"))
        yaml_text = (PKG / "plugin.yaml").read_text(encoding="utf-8")
        desktop = (PKG / "desktop/plugin.js").read_text(encoding="utf-8")
        bundle = (PKG / "dashboard/dist/index.js").read_text(encoding="utf-8")
        self.assertEqual(manifest["name"], "hermes-workforge")
        self.assertIn("name: hermes-workforge", yaml_text)
        self.assertIn("const ID = 'hermes-workforge'", desktop)
        self.assertIn("REG.register('hermes-workforge'", bundle)
        self.assertEqual(manifest["api"], "plugin_api.py")
        self.assertEqual(manifest["entry"], "dist/index.js")

    def test_bundle_uses_scoped_backend_and_host_auth(self) -> None:
        bundle = (PKG / "dashboard/dist/index.js").read_text(encoding="utf-8")
        self.assertIn("__HERMES_PLUGIN_SDK__", bundle)
        self.assertIn("__HERMES_PLUGINS__", bundle)
        self.assertIn("/api/plugins/hermes-workforge", bundle)
        self.assertIn("SDK.fetchJSON", bundle)  # never raw fetch with a hand-read token
        self.assertIn("setInterval(load, 3000)", bundle)

    def test_desktop_plugin_stays_inside_sdk_surface(self) -> None:
        desktop = (PKG / "desktop/plugin.js").read_text(encoding="utf-8")
        imports = re.findall(r"import [\s\S]*? from '([^']+)'", desktop)
        self.assertEqual(set(imports), {"@hermes/plugin-sdk", "react", "react/jsx-runtime"})
        for symbol in ("ROUTES_AREA", "SIDEBAR_NAV_AREA", "PALETTE_AREA", "STATUSBAR_AREAS"):
            self.assertIn(symbol, desktop)
        self.assertIn("ctx.rest('/snapshot')", desktop)
        self.assertNotIn("fetch(", desktop)  # backend access only through ctx.rest

    def test_backend_routes_and_control_allowlist(self) -> None:
        api = (PKG / "dashboard/plugin_api.py").read_text(encoding="utf-8")
        for route in ('/status', '/snapshot', '/events', '/attention', '/control'):
            self.assertIn(f'@{("router.get" if route != "/control" else "router.post")}("{route}")', api)
        self.assertIn('_ACTIONS = {"pause", "resume", "cancel", "approve"}', api)
        self.assertIn("WORKFORCE_URL", api)

    def test_installer_copies_all_declared_files(self) -> None:
        install = (PKG / "install.py").read_text(encoding="utf-8")
        for rel in ("plugin.yaml", "dashboard/manifest.json", "dashboard/plugin_api.py",
                    "dashboard/dist/index.js", "dashboard/dist/style.css", "desktop/plugin.js"):
            self.assertIn(f'"{rel}"', install)
            self.assertTrue((PKG / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
