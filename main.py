"""Convenience wrapper to run Prism Player from the workspace root."""

from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    """Execute the Prism Player app entry point."""
    runpy.run_path(str(Path(__file__).resolve().parent / "prism_player" / "main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
