"""Exact regression gates for Section 1 playback/rendering foundation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pefile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "prism_player"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))


class Section1FoundationTests(unittest.TestCase):
    def test_required_files_and_vendored_version_exist(self) -> None:
        for relative in (
            "core/dll_bootstrap.py", "core/mpv_signals.py", "core/mpv_engine.py",
            "core/mpv_properties.py", "core/player_state.py", "ui/mpv_render_window.py",
            "ui/mpv_render_thread.py",
        ):
            self.assertTrue((PACKAGE / relative).is_file(), relative)
        dll = ROOT / "bin/mpv-2.dll"
        self.assertTrue(dll.is_file())
        self.assertIn("v0.41.0-60-g85bf9f4ff", (ROOT / "bin/MPV_VERSION.txt").read_text(encoding="utf-8"))
        pe = pefile.PE(str(dll), fast_load=True)
        self.assertEqual(pe.FILE_HEADER.Machine, 0x8664)
        pe.close()

    def test_manifest_and_gpu_export_build_step_are_mandatory(self) -> None:
        manifest = (ROOT / "packaging/windows.manifest").read_text(encoding="utf-8")
        build = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")
        patcher = (ROOT / "packaging/patch_gpu_exports.py").read_text(encoding="utf-8")
        self.assertIn("PerMonitorV2", manifest)
        self.assertIn("patch_gpu_exports.py", build)
        self.assertIn("NvOptimusEnablement", patcher)
        self.assertIn("AmdPowerXpressRequestHighPerformance", patcher)

    def test_mpv_initialization_flags_are_exact(self) -> None:
        source = (PACKAGE / "core/mpv_engine.py").read_text(encoding="utf-8")
        for text in (
            'input_default_bindings=False', 'input_vo_keyboard=False', 'osc=False',
            'vid="auto"', 'hwdec="no"', 'loglevel=loglevel',
        ):
            self.assertIn(text, source)
        settings = (PACKAGE / "config/settings.py").read_text(encoding="utf-8")
        self.assertIn('"hwdec": "no"', settings)
        self.assertNotIn('"hwdec": "auto-safe"', settings)


if __name__ == "__main__":
    unittest.main()
