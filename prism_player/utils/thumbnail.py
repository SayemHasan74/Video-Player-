"""Rotation-aware incremental ffmpeg thumbnails with validated disk caching."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from config.settings import app_data_dir
from core.media_probe import probe_media


CACHE_VERSION = 2
BATCH_SIZE = 4


def _source_identity(source: Path | str) -> dict[str, Any]:
    path = Path(source)
    resolved = str(path.resolve())
    stat = path.stat()
    return {
        "source": resolved,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def probe_rotation(source: Path | str) -> int:
    """Return the display rotation declared by the first video stream."""
    payload = probe_media(str(source))
    for stream in payload.get("streams", []) if isinstance(payload, dict) else []:
        if not isinstance(stream, dict) or stream.get("codec_type") != "video":
            continue
        candidates: list[object] = []
        tags = stream.get("tags")
        if isinstance(tags, dict):
            candidates.append(tags.get("rotate"))
        side_data = stream.get("side_data_list")
        if isinstance(side_data, list):
            candidates.extend(
                entry.get("rotation") for entry in side_data if isinstance(entry, dict)
            )
        for raw in candidates:
            try:
                rotation = int(round(float(raw))) % 360
            except (TypeError, ValueError):
                continue
            return min(
                (0, 90, 180, 270),
                key=lambda value: min(abs(value - rotation), 360 - abs(value - rotation)),
            )
    return 0


def thumbnail_cache_dir(source: Path | str, rotation: int | None = None) -> Path:
    path = Path(source)
    try:
        identity = _source_identity(path)
        effective_rotation = probe_rotation(path) if rotation is None else int(rotation) % 360
        key = f"{identity['source']}|{identity['size']}|{identity['mtime_ns']}|{effective_rotation}"
    except OSError:
        key = str(path)
    target = app_data_dir() / "thumbnails" / hashlib.sha256(key.encode("utf-8")).hexdigest()
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.utime(target, None)
    except OSError:
        pass
    return target


def expected_manifest(source: Path | str, duration: float, samples: int, rotation: int) -> dict[str, Any]:
    identity = _source_identity(source)
    return {
        "version": CACHE_VERSION,
        **identity,
        "duration": round(float(duration), 3),
        "samples": int(samples),
        "rotation": int(rotation) % 360,
    }


def validate_thumbnail_manifest(path: Path, expected: dict[str, Any]) -> dict[str, Any] | None:
    """Return a valid manifest, treating malformed/foreign data as a cache miss."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        for key, value in expected.items():
            if payload.get(key) != value:
                return None
        if not isinstance(payload.get("complete", False), bool):
            return None
        generated = payload.get("generated", [])
        if not isinstance(generated, list) or any(not isinstance(name, str) for name in generated):
            return None
        return payload
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _purge_cache_entry(cache: Path) -> None:
    for child in cache.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            pass


def adaptive_sample_count(duration: float, requested: int) -> int:
    """Keep useful coverage while bounding work for multi-hour media."""
    requested = max(10, min(200, int(requested)))
    if duration > 6 * 3600:
        return max(25, requested // 2)
    if duration > 2 * 3600:
        return max(40, round(requested * 0.75))
    return requested


def ffmpeg_executable() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        link = local / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
        if link.exists():
            return str(link)
        packages = local / "Microsoft" / "WinGet" / "Packages"
        match = next(packages.glob("Gyan.FFmpeg*/**/ffmpeg.exe"), None)
        if match:
            return str(match)
    return None


def valid_jpeg(path: Path) -> bool:
    try:
        if path.stat().st_size < 4:
            return False
        with path.open("rb") as handle:
            start = handle.read(2)
            handle.seek(-2, 2)
            end = handle.read(2)
        return start == b"\xff\xd8" and end == b"\xff\xd9"
    except OSError:
        return False


def build_ffmpeg_batch_command(
    ffmpeg: str,
    source: str,
    requests: list[tuple[float, Path]],
) -> list[str]:
    """Build one process containing several independent input-side seeks."""
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for timestamp, _output in requests:
        # ffmpeg autorotation is explicit so display-matrix/tag rotation is
        # applied before the scale filter and represented in the cache manifest.
        command.extend(("-autorotate", "-ss", f"{timestamp:.6f}", "-i", source))
    for input_index, (_timestamp, output) in enumerate(requests):
        command.extend(
            (
                "-map", f"{input_index}:v:0", "-frames:v", "1",
                "-vf", "scale=240:-2", "-q:v", "5", str(output),
            )
        )
    return command


class ThumbnailWorker(QThread):
    thumbnailReady = pyqtSignal(float, str)
    progressChanged = pyqtSignal(int)

    def __init__(
        self,
        source: str,
        duration: float,
        samples: int = 100,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.duration = float(duration)
        self.samples = adaptive_sample_count(duration, samples)
        self.rotation = probe_rotation(source)
        self._cancelled = threading.Event()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def run(self) -> None:
        ffmpeg = ffmpeg_executable()
        if not ffmpeg or self.duration <= 0 or not Path(self.source).exists():
            return
        cache = thumbnail_cache_dir(self.source, self.rotation)
        manifest_path = cache / "manifest.json"
        try:
            expected = expected_manifest(self.source, self.duration, self.samples, self.rotation)
        except OSError:
            return
        manifest = validate_thumbnail_manifest(manifest_path, expected)
        if manifest is None and any(cache.iterdir()):
            _purge_cache_entry(cache)
        payload = {
            **expected,
            "complete": False,
            "generated": [],
        }
        try:
            _write_manifest(manifest_path, payload)
        except OSError:
            return

        requests = [
            (
                index,
                # Never request exactly EOF: many demuxers correctly return no
                # frame there, which used to leave every cache incomplete.
                self.duration * index / max(1, self.samples),
                cache / f"{index:03d}.jpg",
            )
            for index in range(self.samples)
        ]
        try:
            for start in range(0, len(requests), BATCH_SIZE):
                if self._cancelled.is_set():
                    break
                batch = requests[start:start + BATCH_SIZE]
                missing: list[tuple[int, float, Path]] = []
                for index, timestamp, output in batch:
                    if output.exists() and not valid_jpeg(output):
                        output.unlink(missing_ok=True)
                    if not output.exists():
                        missing.append((index, timestamp, output))
                if missing:
                    self._generate_batch(ffmpeg, missing)
                for index, timestamp, output in batch:
                    if self._cancelled.is_set():
                        break
                    if valid_jpeg(output):
                        self.thumbnailReady.emit(timestamp, str(output))
                    self.progressChanged.emit(int((index + 1) * 100 / self.samples))
            generated = [path.name for path in sorted(cache.glob("*.jpg")) if valid_jpeg(path)]
            payload["generated"] = generated
            payload["complete"] = not self._cancelled.is_set() and len(generated) == self.samples
            _write_manifest(manifest_path, payload)
        except OSError:
            pass
        finally:
            for partial in cache.glob("*.part.jpg"):
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass

    def _generate_batch(self, ffmpeg: str, batch: list[tuple[int, float, Path]]) -> None:
        pending = [(timestamp, output.with_suffix(".part.jpg")) for _index, timestamp, output in batch]
        succeeded = self._run_process(build_ffmpeg_batch_command(ffmpeg, self.source, pending), len(batch))
        if not succeeded and len(batch) > 1 and not self._cancelled.is_set():
            for entry in batch:
                self._generate_batch(ffmpeg, [entry])
            return
        for (_index, _timestamp, output), (_time, partial) in zip(batch, pending):
            try:
                if succeeded and valid_jpeg(partial):
                    partial.replace(output)
                else:
                    partial.unlink(missing_ok=True)
            except OSError:
                pass

    def _run_process(self, command: list[str], item_count: int) -> bool:
        if self._cancelled.is_set():
            return False
        creation_flags = 0x08000000 if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            with self._process_lock:
                self._process = process
            try:
                process.communicate(timeout=max(20, item_count * 8))
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            return process.returncode == 0 and not self._cancelled.is_set()
        except OSError:
            return False
        finally:
            with self._process_lock:
                self._process = None


def trim_thumbnail_cache(limit_mb: int) -> None:
    """Evict complete cache entries in least-recently-used order."""
    root = app_data_dir() / "thumbnails"
    if not root.exists():
        return
    entries: list[tuple[float, int, Path]] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            for partial in directory.glob("*.part.jpg"):
                partial.unlink(missing_ok=True)
            files = [path for path in directory.rglob("*") if path.is_file()]
            size = sum(path.stat().st_size for path in files)
            entries.append((directory.stat().st_atime, size, directory))
        except OSError:
            continue
    total = sum(size for _access, size, _directory in entries)
    limit = max(0, int(limit_mb)) * 1024 * 1024
    for _access, size, directory in sorted(entries):
        if total <= limit:
            break
        shutil.rmtree(directory, ignore_errors=True)
        total -= size


def clear_thumbnail_cache() -> None:
    root = app_data_dir() / "thumbnails"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


def cached_thumbnails(sources: list[str]) -> dict[str, str]:
    """Find one validated cached thumbnail per local source in one cache scan."""
    wanted: dict[str, tuple[int, int]] = {}
    canonical: dict[str, str] = {}
    for source in sources:
        try:
            path = Path(source)
            stat = path.stat()
            resolved = str(path.resolve())
            key = resolved.casefold()
            wanted[key] = (int(stat.st_size), int(stat.st_mtime_ns))
            canonical[key] = source
        except OSError:
            continue
    if not wanted:
        return {}
    root = app_data_dir() / "thumbnails"
    if not root.exists():
        return {}
    found: dict[str, str] = {}
    for manifest_path in root.glob("*/manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            source = str(payload.get("source") or "")
            key = source.casefold()
            identity = wanted.get(key)
            if identity is None or identity != (
                int(payload.get("size", -1)), int(payload.get("mtime_ns", -1))
            ):
                continue
            generated = payload.get("generated", [])
            if not isinstance(generated, list) or not generated:
                continue
            # A frame near the middle is more representative than frame zero.
            names = [str(name) for name in generated if isinstance(name, str)]
            candidate = manifest_path.parent / names[len(names) // 2]
            if valid_jpeg(candidate):
                found[canonical[key]] = str(candidate)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return found
