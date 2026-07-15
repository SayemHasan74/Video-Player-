"""Create, validate, build and run Comet Python plugins during development."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


PLUGIN_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,79}$")


def plugin_manifest(folder: Path) -> dict[str, object]:
    path = folder / "plugin.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not PLUGIN_ID.fullmatch(str(payload.get("id", ""))):
        raise ValueError("plugin.json has an invalid id")
    entry = (folder / str(payload.get("entry", "main.py"))).resolve()
    if folder.resolve() not in entry.parents or not entry.is_file():
        raise ValueError("plugin entry must be a file inside the plugin folder")
    return payload


def create_plugin(name: str, plugin_id: str, directory: Path) -> Path:
    if not PLUGIN_ID.fullmatch(plugin_id):
        raise ValueError("plugin id must contain only letters, numbers, dots, dashes or underscores")
    folder = directory / re.sub(r"[^a-zA-Z0-9._-]", "-", plugin_id)
    if folder.exists():
        raise FileExistsError(folder)
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(
        json.dumps(
            {"id": plugin_id, "name": name, "version": "0.1.0", "description": "", "entry": "main.py"},
            indent=2,
        ),
        encoding="utf-8",
    )
    (folder / "main.py").write_text(
        "def setup(api):\n"
        "    api.logging.info('Plugin loaded')\n"
        f"    api.menu.add('Hello from {name}', lambda: api.core.osd('Hello from {name}'))\n",
        encoding="utf-8",
    )
    (folder / "README.md").write_text(f"# {name}\n\nA Comet V2 plugin.\n", encoding="utf-8")
    return folder


def build_plugin(folder: Path, output: Path | None = None) -> Path:
    manifest = plugin_manifest(folder)
    destination = output or folder.parent / f"{manifest['id']}-{manifest.get('version', '0.0.0')}"
    base = str(destination)
    if base.lower().endswith(".zip"):
        base = base[:-4]
    archive = Path(shutil.make_archive(base, "zip", folder.parent, folder.name))
    return archive


def run_plugin(folder: Path) -> int:
    plugin_manifest(folder)
    project = Path(__file__).resolve().parents[1]
    entry = project / "main.py"
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe") if os.name == "nt" else executable
    if pythonw.exists():
        executable = pythonw
    environment = os.environ.copy()
    environment["COMET_PLUGIN_DEV_PATH"] = str(folder.resolve())
    environment["COMET_PLUGIN_DEV_AUTOLOAD"] = "1"
    creation_flags = 0x00000008 if os.name == "nt" else 0
    subprocess.Popen([str(executable), str(entry)], cwd=project, env=environment, creationflags=creation_flags)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Comet V2 plugin development CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create a plugin scaffold")
    create.add_argument("name")
    create.add_argument("--id", dest="plugin_id", default="")
    create.add_argument("--directory", type=Path, default=Path.cwd())
    validate = commands.add_parser("validate", help="validate a plugin package")
    validate.add_argument("folder", type=Path)
    build = commands.add_parser("build", help="build a zip package")
    build.add_argument("folder", type=Path)
    build.add_argument("--output", type=Path)
    run = commands.add_parser("run", help="launch Comet with the plugin loaded from its source folder")
    run.add_argument("folder", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "create":
        plugin_id = args.plugin_id or re.sub(r"[^a-zA-Z0-9._-]", "-", args.name.lower()).strip("-")
        print(create_plugin(args.name, plugin_id, args.directory))
    elif args.command == "validate":
        plugin_manifest(args.folder.resolve())
        print("Plugin is valid")
    elif args.command == "build":
        print(build_plugin(args.folder.resolve(), args.output))
    elif args.command == "run":
        return run_plugin(args.folder.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
