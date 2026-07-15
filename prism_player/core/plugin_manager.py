"""Small, isolated Python plugin runtime for Comet V2.

Plugins are trusted local extensions.  They receive a deliberately narrow API
instead of the MainWindow object, and every registration is owned by one plugin
so disabling it can remove all of its effects deterministically.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from config.settings import app_data_dir


_PLUGIN_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,79}$")


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str
    entry: str
    root: Path


@dataclass
class PluginMenuItem:
    owner: str
    item_id: str
    title: str
    callback: Callable[..., Any]
    location: str = "plugin"
    enabled: Callable[[], bool] | bool = True


@dataclass
class PluginSidebarItem:
    owner: str
    item_id: str
    title: str
    factory: Callable[[], Any]


@dataclass
class PluginOverlayItem:
    owner: str
    item_id: str
    html: str
    style: str = ""
    position: str = "top-left"
    visible: bool = True


@dataclass
class PluginInputHandler:
    owner: str
    item_id: str
    callback: Callable[[dict[str, Any]], Any]
    priority: int = 0
    phase: str = "before"


@dataclass(frozen=True)
class PluginLogEntry:
    timestamp: float
    owner: str
    level: str
    message: str


@dataclass
class PluginRecord:
    manifest: PluginManifest
    enabled: bool = False
    module: ModuleType | None = None
    instance: Any = None
    error: str = ""
    menu_items: list[PluginMenuItem] = field(default_factory=list)
    sidebar_items: list[PluginSidebarItem] = field(default_factory=list)
    overlay_items: list[PluginOverlayItem] = field(default_factory=list)
    input_handlers: list[PluginInputHandler] = field(default_factory=list)
    preferences: PluginPreferences | None = None
    preference_schema: list[dict[str, Any]] = field(default_factory=list)
    observers: list[QTimer] = field(default_factory=list)
    processes: list[QProcess] = field(default_factory=list)
    is_user_script: bool = False


class PluginEventBus:
    """Synchronous event bus with owner-scoped cleanup and fault isolation."""

    def __init__(self, report_error: Callable[[str, BaseException], None]) -> None:
        self._listeners: dict[str, list[tuple[str, Callable[..., Any]]]] = {}
        self._report_error = report_error

    def on(self, owner: str, event: str, callback: Callable[..., Any]) -> None:
        if not callable(callback):
            raise TypeError("event callback must be callable")
        pair = (owner, callback)
        listeners = self._listeners.setdefault(str(event), [])
        if pair not in listeners:
            listeners.append(pair)

    def off(self, owner: str, event: str, callback: Callable[..., Any] | None = None) -> None:
        listeners = self._listeners.get(str(event), [])
        self._listeners[str(event)] = [
            pair for pair in listeners if pair[0] != owner or (callback is not None and pair[1] is not callback)
        ]

    def remove_owner(self, owner: str) -> None:
        for event in tuple(self._listeners):
            self._listeners[event] = [pair for pair in self._listeners[event] if pair[0] != owner]
            if not self._listeners[event]:
                self._listeners.pop(event, None)

    def emit(self, event: str, data: Any = None) -> None:
        for owner, callback in tuple(self._listeners.get(str(event), ())):
            try:
                callback(data)
            except Exception as exc:  # a plugin must never break playback
                self._report_error(owner, exc)


class PluginPreferences:
    def __init__(self, path: Path, define_callback: Callable[[list[dict[str, Any]]], None] | None = None) -> None:
        self.path = path
        self._define_callback = define_callback

    def all(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.all().get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self.all()
        data[str(key)] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def define(self, fields: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> None:
        """Declare fields for an automatically generated in-app settings page."""
        if isinstance(fields, dict):
            source = [dict(spec, key=key) for key, spec in fields.items() if isinstance(spec, dict)]
        elif isinstance(fields, list):
            source = [dict(spec) for spec in fields if isinstance(spec, dict)]
        else:
            raise TypeError("preference schema must be a list or mapping")
        normalized: list[dict[str, Any]] = []
        for field in source:
            key = str(field.get("key") or "").strip()
            kind = str(field.get("type") or "text").lower()
            if not key or kind not in {"text", "check", "int", "float", "choose"}:
                raise ValueError("preference fields need a key and a supported type")
            entry = {
                "key": key,
                "label": str(field.get("label") or key.replace("_", " ").title()),
                "type": kind,
                "default": field.get("default"),
            }
            if kind == "choose":
                options = field.get("options", [])
                if not isinstance(options, list) or not options:
                    raise ValueError(f"choose preference {key} needs options")
                entry["options"] = [str(value) for value in options]
            for limit in ("min", "max", "step"):
                if limit in field:
                    entry[limit] = field[limit]
            normalized.append(entry)
            if self.get(key, None) is None and "default" in entry:
                self.set(key, entry["default"])
        if self._define_callback is not None:
            self._define_callback(normalized)


class _EventAPI:
    def __init__(self, manager: "PluginManager", owner: str) -> None:
        self.manager, self.owner = manager, owner

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        self.manager.events.on(self.owner, event, callback)

    def off(self, event: str, callback: Callable[..., Any] | None = None) -> None:
        self.manager.events.off(self.owner, event, callback)

    def observe_property(
        self, name: str, callback: Callable[[Any], Any], interval_ms: int = 250
    ) -> str:
        return self.manager.observe_property(self.owner, name, callback, interval_ms)


class _MenuAPI:
    def __init__(self, manager: "PluginManager", owner: str) -> None:
        self.manager, self.owner = manager, owner

    def add(
        self,
        title: str,
        callback: Callable[..., Any],
        *,
        item_id: str | None = None,
        location: str = "plugin",
        enabled: Callable[[], bool] | bool = True,
    ) -> str:
        if location not in {"plugin", "context", "playlist_context"}:
            raise ValueError("location must be plugin, context, or playlist_context")
        record = self.manager.records[self.owner]
        generated = item_id or f"menu-{len(record.menu_items) + 1}"
        record.menu_items.append(PluginMenuItem(self.owner, generated, str(title), callback, location, enabled))
        return generated


class _SidebarAPI:
    def __init__(self, manager: "PluginManager", owner: str) -> None:
        self.manager, self.owner = manager, owner

    def register(self, title: str, factory: Callable[[], Any], *, item_id: str | None = None) -> str:
        if not callable(factory):
            raise TypeError("sidebar factory must be callable")
        record = self.manager.records[self.owner]
        generated = item_id or f"sidebar-{len(record.sidebar_items) + 1}"
        record.sidebar_items.append(PluginSidebarItem(self.owner, generated, str(title), factory))
        return generated


class _OverlayAPI:
    def __init__(self, manager: "PluginManager", owner: str) -> None:
        self.manager, self.owner = manager, owner

    def show(
        self,
        html: str,
        *,
        item_id: str | None = None,
        style: str = "",
        position: str = "top-left",
    ) -> str:
        if position not in {"top-left", "top", "top-right", "center", "bottom-left", "bottom", "bottom-right"}:
            raise ValueError("unsupported overlay position")
        record = self.manager.records[self.owner]
        generated = item_id or f"overlay-{len(record.overlay_items) + 1}"
        existing = next((item for item in record.overlay_items if item.item_id == generated), None)
        if existing is None:
            record.overlay_items.append(PluginOverlayItem(self.owner, generated, str(html), str(style), position, True))
        else:
            existing.html, existing.style, existing.position, existing.visible = str(html), str(style), position, True
        self.manager.overlayChanged.emit()
        return generated

    def update(self, item_id: str, **changes: Any) -> None:
        record = self.manager.records[self.owner]
        item = next((entry for entry in record.overlay_items if entry.item_id == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if "html" in changes:
            item.html = str(changes["html"])
        if "style" in changes:
            item.style = str(changes["style"])
        if "position" in changes:
            position = str(changes["position"])
            if position not in {"top-left", "top", "top-right", "center", "bottom-left", "bottom", "bottom-right"}:
                raise ValueError("unsupported overlay position")
            item.position = position
        if "visible" in changes:
            item.visible = bool(changes["visible"])
        self.manager.overlayChanged.emit()

    def hide(self, item_id: str) -> None:
        self.update(item_id, visible=False)

    def remove(self, item_id: str) -> None:
        record = self.manager.records[self.owner]
        record.overlay_items[:] = [item for item in record.overlay_items if item.item_id != item_id]
        self.manager.overlayChanged.emit()


class _InputAPI:
    def __init__(self, manager: "PluginManager", owner: str) -> None:
        self.manager, self.owner = manager, owner

    def register(
        self,
        callback: Callable[[dict[str, Any]], Any],
        *,
        priority: int = 0,
        phase: str = "before",
        item_id: str | None = None,
    ) -> str:
        if not callable(callback):
            raise TypeError("input callback must be callable")
        if phase not in {"before", "after"}:
            raise ValueError("phase must be before or after")
        record = self.manager.records[self.owner]
        generated = item_id or f"input-{len(record.input_handlers) + 1}"
        record.input_handlers.append(
            PluginInputHandler(self.owner, generated, callback, max(-1000, min(1000, int(priority))), phase)
        )
        return generated

    def remove(self, item_id: str) -> None:
        record = self.manager.records[self.owner]
        record.input_handlers[:] = [item for item in record.input_handlers if item.item_id != item_id]


class _FilesAPI:
    MAX_FILE_SIZE = 16 * 1024 * 1024

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, relative: str) -> Path:
        if not relative or Path(relative).is_absolute():
            raise ValueError("plugin data paths must be relative")
        path = (self.root / relative).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("plugin data path escapes its sandbox")
        return path

    def read_text(self, relative: str, encoding: str = "utf-8") -> str:
        path = self._path(relative)
        if path.stat().st_size > self.MAX_FILE_SIZE:
            raise ValueError("plugin data file is too large")
        return path.read_text(encoding=encoding)

    def write_text(self, relative: str, value: str, encoding: str = "utf-8") -> None:
        data = str(value).encode(encoding)
        if len(data) > self.MAX_FILE_SIZE:
            raise ValueError("plugin data file is too large")
        self.write_bytes(relative, data)

    def read_bytes(self, relative: str) -> bytes:
        path = self._path(relative)
        if path.stat().st_size > self.MAX_FILE_SIZE:
            raise ValueError("plugin data file is too large")
        return path.read_bytes()

    def write_bytes(self, relative: str, value: bytes) -> None:
        data = bytes(value)
        if len(data) > self.MAX_FILE_SIZE:
            raise ValueError("plugin data file is too large")
        path = self._path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def list(self, relative: str = ".") -> list[str]:
        path = self._path(relative)
        if not path.exists():
            return []
        return [str(child.relative_to(self.root)).replace("\\", "/") for child in sorted(path.iterdir())]

    def delete(self, relative: str) -> None:
        path = self._path(relative)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


class _ProcessAPI:
    def __init__(self, manager: "PluginManager", owner: str, plugin_root: Path, data_root: Path) -> None:
        self.manager, self.owner = manager, owner
        self.plugin_root = plugin_root.resolve()
        self.data_root = data_root.resolve()

    def _command(self, executable: str, args: list[str] | tuple[str, ...], cwd: str) -> tuple[str, list[str], Path]:
        resolved = shutil.which(str(executable)) or str(Path(executable).expanduser())
        if not Path(resolved).is_file():
            raise FileNotFoundError(executable)
        arguments = [str(value) for value in args]
        if len(arguments) > 256 or any(len(value) > 8192 for value in arguments):
            raise ValueError("external process arguments exceed the safe limit")
        working = self.plugin_root if cwd == "plugin" else self.data_root if cwd == "data" else None
        if working is None:
            raise ValueError("cwd must be plugin or data")
        working.mkdir(parents=True, exist_ok=True)
        return resolved, arguments, working

    def run(
        self,
        executable: str,
        args: list[str] | tuple[str, ...] = (),
        *,
        timeout: float = 30.0,
        cwd: str = "plugin",
    ) -> dict[str, Any]:
        resolved, arguments, working = self._command(executable, args, cwd)
        creation_flags = 0x08000000 if os.name == "nt" else 0
        completed = subprocess.run(
            [resolved, *arguments],
            cwd=working,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.1, min(120.0, float(timeout))),
            shell=False,
            creationflags=creation_flags,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-1_000_000:],
            "stderr": completed.stderr[-1_000_000:],
        }

    def start(
        self,
        executable: str,
        args: list[str] | tuple[str, ...] = (),
        *,
        on_finished: Callable[[dict[str, Any]], Any] | None = None,
        timeout: float = 30.0,
        cwd: str = "plugin",
    ) -> str:
        """Start a managed non-blocking process and report completion on Qt's UI thread."""
        resolved, arguments, working = self._command(executable, args, cwd)
        record = self.manager.records[self.owner]
        process = QProcess(self.manager)
        process.setProgram(resolved)
        process.setArguments(arguments)
        process.setWorkingDirectory(str(working))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        record.processes.append(process)
        process_id = f"process-{len(record.processes)}"
        watchdog = QTimer(process)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(process.kill)

        def finished(exit_code: int, _status: object) -> None:
            watchdog.stop()
            result = {
                "returncode": int(exit_code),
                "stdout": bytes(process.readAllStandardOutput()).decode("utf-8", "replace")[-1_000_000:],
                "stderr": bytes(process.readAllStandardError()).decode("utf-8", "replace")[-1_000_000:],
            }
            if process in record.processes:
                record.processes.remove(process)
            if callable(on_finished):
                try:
                    on_finished(result)
                except Exception as exc:
                    self.manager._plugin_exception(self.owner, exc)
            process.deleteLater()

        process.finished.connect(finished)
        process.start()
        watchdog.start(round(max(0.1, min(120.0, float(timeout))) * 1000))
        return process_id


class _LoggingAPI:
    def __init__(self, manager: "PluginManager", owner: str) -> None:
        self.manager, self.owner = manager, owner

    def debug(self, message: object) -> None: self.manager.log(self.owner, "debug", message)
    def info(self, message: object) -> None: self.manager.log(self.owner, "info", message)
    def warning(self, message: object) -> None: self.manager.log(self.owner, "warning", message)
    def error(self, message: object) -> None: self.manager.log(self.owner, "error", message)


class _PlaylistAPI:
    def __init__(self, manager: "PluginManager", owner: str) -> None:
        self.manager, self.owner = manager, owner

    def items(self) -> list[dict[str, Any]]:
        return self.manager.host.plugin_playlist_items()

    def add(self, source: str, *, play: bool = False) -> None:
        self.manager.host.plugin_playlist_add(source, play=play)

    def remove(self, index: int) -> None:
        self.manager.host.plugin_playlist_remove(index)

    def play(self, index: int) -> None:
        self.manager.host.plugin_playlist_play(index)

    def add_context_item(self, title: str, callback: Callable[..., Any], *, item_id: str | None = None) -> str:
        return _MenuAPI(self.manager, self.owner).add(
            title, callback, item_id=item_id, location="playlist_context"
        )


class _CoreAPI:
    def __init__(self, manager: "PluginManager") -> None:
        self.manager = manager

    def status(self) -> dict[str, Any]:
        return self.manager.host.plugin_player_status()

    def play_pause(self) -> None:
        self.manager.host.player.play_pause()

    def pause(self, paused: bool = True) -> None:
        self.manager.host.player.set_paused(bool(paused))

    def seek(self, seconds: float) -> None:
        self.manager.host.player.seek_absolute(float(seconds))

    def get_property(self, name: str) -> Any:
        return self.manager.host.player.get_property(str(name))

    def set_property(self, name: str, value: Any) -> None:
        self.manager.host.player.set_property(str(name), value)

    def osd(self, message: str, level: str = "info") -> None:
        self.manager.host.osd.show_message(str(message), str(level))


class PluginManager(QObject):
    """Discover and host trusted local plugins for one player window."""

    changed = pyqtSignal()
    error = pyqtSignal(str, str)
    overlayChanged = pyqtSignal()
    preferencesChanged = pyqtSignal(str)
    logChanged = pyqtSignal()

    def __init__(self, host: Any, root: Path | None = None, data_root: Path | None = None) -> None:
        super().__init__(host)
        self.host = host
        self.root = root or app_data_dir() / "plugins"
        self.data_root = data_root or app_data_dir() / "plugin_data"
        self.state_path = self.data_root / "enabled.json"
        self.scripts_root = self.data_root / "user_scripts"
        self.records: dict[str, PluginRecord] = {}
        self.events = PluginEventBus(self._plugin_exception)
        self.logger = logging.getLogger(__name__)
        self.logs: deque[PluginLogEntry] = deque(maxlen=1000)
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.scripts_root.mkdir(parents=True, exist_ok=True)

    def discover(self) -> dict[str, PluginRecord]:
        enabled = self._enabled_state()
        previous = self.records
        discovered: dict[str, PluginRecord] = {}
        manifest_paths = list(self.root.glob("*/plugin.json"))
        development = os.environ.get("COMET_PLUGIN_DEV_PATH", "").strip()
        dev_manifest: Path | None = None
        if development:
            dev_path = Path(development).expanduser()
            dev_manifest = (dev_path / "plugin.json" if dev_path.is_dir() else dev_path).resolve()
            manifest_paths.append(dev_manifest)
        for manifest_path in sorted(set(manifest_paths)):
            try:
                manifest = self._read_manifest(manifest_path)
                if manifest.plugin_id in discovered:
                    raise ValueError(f"duplicate plugin id: {manifest.plugin_id}")
                old = previous.get(manifest.plugin_id)
                discovered[manifest.plugin_id] = old or PluginRecord(manifest, enabled.get(manifest.plugin_id, False))
                discovered[manifest.plugin_id].manifest = manifest
                if (
                    dev_manifest is not None
                    and manifest_path.resolve() == dev_manifest
                    and os.environ.get("COMET_PLUGIN_DEV_AUTOLOAD") == "1"
                ):
                    discovered[manifest.plugin_id].enabled = True
            except Exception as exc:
                self.logger.warning("Ignoring plugin manifest %s: %s", manifest_path, exc)
        # Unload plugins whose directories disappeared.
        scripts = {key: value for key, value in previous.items() if value.is_user_script}
        for plugin_id in set(previous) - set(discovered) - set(scripts):
            self._unload_record(previous[plugin_id])
        self.records = {**discovered, **scripts}
        self.changed.emit()
        return self.records

    def load_enabled(self) -> None:
        self.discover()
        for plugin_id, record in tuple(self.records.items()):
            if record.enabled:
                self.load(plugin_id)

    def load(self, plugin_id: str) -> bool:
        record = self.records[plugin_id]
        if record.module is not None:
            return True
        try:
            entry = (record.manifest.root / record.manifest.entry).resolve()
            if record.manifest.root.resolve() not in entry.parents or not entry.is_file():
                raise ValueError("entry must be a Python file inside the plugin directory")
            module_name = f"comet_plugin_{re.sub('[^a-zA-Z0-9_]', '_', plugin_id)}"
            spec = importlib.util.spec_from_file_location(module_name, entry)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {entry}")
            module = importlib.util.module_from_spec(spec)
            api = self._api_for(record)
            module.api = api
            sys.modules[module_name] = module
            record.module = module
            spec.loader.exec_module(module)
            setup = getattr(module, "setup", None)
            run = getattr(module, "run", None)
            if not callable(setup) and not record.is_user_script:
                raise ValueError("entry module must define setup(api)")
            record.error = ""
            record.instance = setup(api) if callable(setup) else run(api) if callable(run) else module
            record.enabled = True
            self._save_enabled_state()
            self.changed.emit()
            self.events.emit("plugin.loaded", {"id": plugin_id})
            return True
        except Exception as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            self._unload_record(record)
            self._plugin_exception(plugin_id, exc)
            return False

    def unload(self, plugin_id: str) -> None:
        record = self.records[plugin_id]
        self._unload_record(record)
        record.enabled = False
        self._save_enabled_state()
        self.changed.emit()

    def reload(self, plugin_id: str) -> bool:
        record = self.records[plugin_id]
        was_enabled = record.enabled
        self._unload_record(record)
        return self.load(plugin_id) if was_enabled else True

    def reload_all(self) -> None:
        enabled_ids = {plugin_id for plugin_id, record in self.records.items() if record.enabled}
        for record in tuple(self.records.values()):
            self._unload_record(record)
        self.discover()
        for plugin_id in enabled_ids & self.records.keys():
            self.records[plugin_id].enabled = True
            self.load(plugin_id)
        self.changed.emit()

    def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        if enabled:
            self.records[plugin_id].enabled = True
            self._save_enabled_state()
            return self.load(plugin_id)
        self.unload(plugin_id)
        return True

    def menu_items(self, location: str) -> list[PluginMenuItem]:
        return [
            item for record in self.records.values() if record.module is not None
            for item in record.menu_items if item.location == location
        ]

    def sidebar_items(self) -> list[PluginSidebarItem]:
        return [item for record in self.records.values() if record.module is not None for item in record.sidebar_items]

    def overlay_items(self) -> list[PluginOverlayItem]:
        return [
            item for record in self.records.values() if record.module is not None
            for item in record.overlay_items if item.visible
        ]

    def dispatch_input(self, event: dict[str, Any], phase: str = "before") -> bool:
        handlers = sorted(
            (
                item for record in self.records.values() if record.module is not None
                for item in record.input_handlers if item.phase == phase
            ),
            key=lambda item: item.priority,
            reverse=True,
        )
        for item in handlers:
            try:
                if item.callback(dict(event)):
                    return True
            except Exception as exc:
                self._plugin_exception(item.owner, exc)
        return False

    def log(self, owner: str, level: str, message: object) -> None:
        normalized = level.lower() if level.lower() in {"debug", "info", "warning", "error"} else "info"
        entry = PluginLogEntry(time.time(), str(owner), normalized, str(message))
        self.logs.append(entry)
        getattr(self.logger, normalized)("Plugin %s: %s", owner, message)
        self.logChanged.emit()

    def clear_logs(self) -> None:
        self.logs.clear()
        self.logChanged.emit()

    def user_script_names(self) -> list[str]:
        return [path.stem for path in sorted(self.scripts_root.glob("*.py"))]

    def save_user_script(self, name: str, code: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9 _.-]", "_", name).strip(" .")
        if not safe:
            raise ValueError("user script needs a name")
        path = (self.scripts_root / f"{safe}.py").resolve()
        if self.scripts_root.resolve() not in path.parents:
            raise ValueError("invalid user script name")
        path.write_text(str(code), encoding="utf-8")
        return path

    def run_user_script(self, name: str) -> bool:
        path = (self.scripts_root / f"{Path(name).stem}.py").resolve()
        if self.scripts_root.resolve() not in path.parents or not path.is_file():
            raise FileNotFoundError(name)
        slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", path.stem)
        plugin_id = f"user-script.{slug}"
        previous = self.records.get(plugin_id)
        if previous is not None:
            self._unload_record(previous)
        record = PluginRecord(
            PluginManifest(plugin_id, path.stem, "script", "Quick User Script", path.name, path.parent),
            enabled=True,
            is_user_script=True,
        )
        self.records[plugin_id] = record
        return self.load(plugin_id)

    def invoke(self, item: PluginMenuItem, *args: Any) -> Any:
        try:
            return item.callback(*args)
        except Exception as exc:
            self._plugin_exception(item.owner, exc)
            return None

    def observe_property(
        self,
        owner: str,
        name: str,
        callback: Callable[[Any], Any],
        interval_ms: int = 250,
    ) -> str:
        if not callable(callback):
            raise TypeError("property observer callback must be callable")
        property_name = str(name).strip()
        if not property_name:
            raise ValueError("property name is required")
        record = self.records[owner]
        timer = QTimer(self)
        timer.setInterval(max(50, min(5000, int(interval_ms))))
        previous: list[Any] = [object()]

        def poll() -> None:
            try:
                value = self.host.player.get_property(property_name)
                if value != previous[0]:
                    previous[0] = value
                    callback(value)
            except Exception as exc:
                timer.stop()
                self._plugin_exception(owner, exc)

        timer.timeout.connect(poll)
        record.observers.append(timer)
        timer.start()
        poll()
        return f"property-{len(record.observers)}"

    def shutdown(self) -> None:
        self.events.emit("window.closing")
        for record in tuple(self.records.values()):
            self._unload_record(record)

    def _api_for(self, record: PluginRecord) -> Any:
        plugin_data = self.data_root / record.manifest.plugin_id
        preferences = PluginPreferences(
            plugin_data / "preferences.json",
            lambda schema, plugin_id=record.manifest.plugin_id: self._set_preference_schema(plugin_id, schema),
        )
        record.preferences = preferences
        return SimpleNamespace(
            id=record.manifest.plugin_id,
            core=_CoreAPI(self),
            events=_EventAPI(self, record.manifest.plugin_id),
            menu=_MenuAPI(self, record.manifest.plugin_id),
            playlist=_PlaylistAPI(self, record.manifest.plugin_id),
            sidebar=_SidebarAPI(self, record.manifest.plugin_id),
            overlay=_OverlayAPI(self, record.manifest.plugin_id),
            input=_InputAPI(self, record.manifest.plugin_id),
            preferences=preferences,
            files=_FilesAPI(plugin_data / "files"),
            process=_ProcessAPI(self, record.manifest.plugin_id, record.manifest.root, plugin_data / "files"),
            logging=_LoggingAPI(self, record.manifest.plugin_id),
        )

    def _set_preference_schema(self, plugin_id: str, schema: list[dict[str, Any]]) -> None:
        record = self.records.get(plugin_id)
        if record is not None:
            record.preference_schema = schema
            self.preferencesChanged.emit(plugin_id)

    def _unload_record(self, record: PluginRecord) -> None:
        target = record.instance if record.instance is not None else record.module
        shutdown = getattr(target, "shutdown", None) if target is not None else None
        if callable(shutdown):
            try:
                shutdown()
            except Exception as exc:
                self._plugin_exception(record.manifest.plugin_id, exc)
        self.events.remove_owner(record.manifest.plugin_id)
        record.menu_items.clear()
        record.sidebar_items.clear()
        record.overlay_items.clear()
        record.input_handlers.clear()
        for timer in record.observers:
            timer.stop()
            timer.deleteLater()
        record.observers.clear()
        for process in tuple(record.processes):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
        record.processes.clear()
        if record.module is not None:
            sys.modules.pop(record.module.__name__, None)
        record.instance = None
        record.module = None
        self.overlayChanged.emit()

    def _read_manifest(self, path: Path) -> PluginManifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("manifest must be an object")
        plugin_id = str(raw.get("id", ""))
        if not _PLUGIN_ID.fullmatch(plugin_id):
            raise ValueError("invalid plugin id")
        entry = str(raw.get("entry", "main.py"))
        return PluginManifest(
            plugin_id, str(raw.get("name") or plugin_id), str(raw.get("version") or "0.0.0"),
            str(raw.get("description") or ""), entry, path.parent.resolve()
        )

    def _enabled_state(self) -> dict[str, bool]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {}
            return {str(key): bool(value) for key, value in raw.items()} if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_enabled_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {plugin_id: record.enabled for plugin_id, record in self.records.items()}
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def _plugin_exception(self, owner: str, exc: BaseException) -> None:
        message = f"{type(exc).__name__}: {exc}"
        record = self.records.get(owner)
        if record is not None:
            record.error = message
        self.logger.error("Plugin %s failed: %s\n%s", owner, message, traceback.format_exc())
        self.logs.append(PluginLogEntry(time.time(), owner, "error", message))
        self.logChanged.emit()
        self.error.emit(owner, message)
