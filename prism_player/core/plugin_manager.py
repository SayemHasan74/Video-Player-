"""Small, isolated Python plugin runtime for Comet V2.

Plugins are trusted local extensions.  They receive a deliberately narrow API
instead of the MainWindow object, and every registration is owned by one plugin
so disabling it can remove all of its effects deterministically.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal

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
class PluginRecord:
    manifest: PluginManifest
    enabled: bool = False
    module: ModuleType | None = None
    instance: Any = None
    error: str = ""
    menu_items: list[PluginMenuItem] = field(default_factory=list)
    sidebar_items: list[PluginSidebarItem] = field(default_factory=list)


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
    def __init__(self, path: Path) -> None:
        self.path = path

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


class _EventAPI:
    def __init__(self, manager: "PluginManager", owner: str) -> None:
        self.manager, self.owner = manager, owner

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        self.manager.events.on(self.owner, event, callback)

    def off(self, event: str, callback: Callable[..., Any] | None = None) -> None:
        self.manager.events.off(self.owner, event, callback)


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

    def __init__(self, host: Any, root: Path | None = None, data_root: Path | None = None) -> None:
        super().__init__(host)
        self.host = host
        self.root = root or app_data_dir() / "plugins"
        self.data_root = data_root or app_data_dir() / "plugin_data"
        self.state_path = self.data_root / "enabled.json"
        self.records: dict[str, PluginRecord] = {}
        self.events = PluginEventBus(self._plugin_exception)
        self.logger = logging.getLogger(__name__)
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)

    def discover(self) -> dict[str, PluginRecord]:
        enabled = self._enabled_state()
        previous = self.records
        discovered: dict[str, PluginRecord] = {}
        for manifest_path in sorted(self.root.glob("*/plugin.json")):
            try:
                manifest = self._read_manifest(manifest_path)
                if manifest.plugin_id in discovered:
                    raise ValueError(f"duplicate plugin id: {manifest.plugin_id}")
                old = previous.get(manifest.plugin_id)
                discovered[manifest.plugin_id] = old or PluginRecord(manifest, enabled.get(manifest.plugin_id, False))
                discovered[manifest.plugin_id].manifest = manifest
            except Exception as exc:
                self.logger.warning("Ignoring plugin manifest %s: %s", manifest_path, exc)
        # Unload plugins whose directories disappeared.
        for plugin_id in set(previous) - set(discovered):
            self._unload_record(previous[plugin_id])
        self.records = discovered
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
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            setup = getattr(module, "setup", None)
            if not callable(setup):
                raise ValueError("entry module must define setup(api)")
            record.module = module
            record.error = ""
            record.instance = setup(self._api_for(record))
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

    def invoke(self, item: PluginMenuItem, *args: Any) -> Any:
        try:
            return item.callback(*args)
        except Exception as exc:
            self._plugin_exception(item.owner, exc)
            return None

    def shutdown(self) -> None:
        self.events.emit("window.closing")
        for record in tuple(self.records.values()):
            self._unload_record(record)

    def _api_for(self, record: PluginRecord) -> Any:
        preferences = PluginPreferences(self.data_root / record.manifest.plugin_id / "preferences.json")
        return SimpleNamespace(
            id=record.manifest.plugin_id,
            core=_CoreAPI(self),
            events=_EventAPI(self, record.manifest.plugin_id),
            menu=_MenuAPI(self, record.manifest.plugin_id),
            playlist=_PlaylistAPI(self, record.manifest.plugin_id),
            sidebar=_SidebarAPI(self, record.manifest.plugin_id),
            preferences=preferences,
        )

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
        if record.module is not None:
            sys.modules.pop(record.module.__name__, None)
        record.instance = None
        record.module = None

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
        self.error.emit(owner, message)
