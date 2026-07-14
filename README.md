# Comet Player

Comet Player is a dark, modern Windows 11 desktop media player built with PyQt6 and mpv. It is inspired by IINA's clean playback-first feel while keeping a native Windows-style frameless window, overlay controls, playlist panel, URL playback, screenshots, resume history, and keyboard shortcuts.

Screenshot placeholder: add an app screenshot here after launching Comet Player with a local video.

## Download

The ready-to-run Windows build is published on the GitHub Releases page:

https://github.com/SayemHasan74/Video-Player-/releases/tag/v1.0.0

Download `CometPlayer-v1.0.0-portable.zip`, extract it, and run `CometPlayer.exe`.

## Requirements

- Python 3.11+
- `mpv-2.dll` on Windows
- Dependencies from `requirements.txt`

## Installation

```powershell
pip install -r requirements.txt
```

## mpv-2.dll Setup

1. Open https://sourceforge.net/projects/mpv-player-windows/files/libmpv/
2. Download the latest `mpv-dev-x86_64` zip.
3. Extract it and find `mpv-2.dll`. If it is named `libmpv-2.dll`, rename it to `mpv-2.dll`.
4. Place it beside `main.py` inside the `prism_player` folder, beside the workspace-root `main.py`, or put it somewhere on `PATH`.

## Run

From the `prism_player` folder:

```powershell
python main.py
```

From the workspace root, the wrapper also supports:

```powershell
python main.py
```

## Features

- mpv-backed local video and audio playback
- YouTube and URL playback through `yt-dlp`
- Frameless Windows 11-style dark interface
- Overlay seekbar and playback controls
- Playlist panel with add, remove, select, next, previous, shuffle-ready logic
- Resume position history stored in SQLite
- Audio and subtitle track menus
- Reactive Video/Audio/Subtitle quick settings with crop selection, video controls, 10-band EQ, and dual subtitles
- Persistent active/saved filter editor with typed presets and optional shortcuts
- Structured live media inspector with arbitrary mpv property watch
- Searchable playback history with queued background writes
- Recent-media welcome window with file/URL drag-and-drop
- Incremental, validated thumbnail previews with bounded disk caching
- Searchable nine-section preferences and editable named key-binding profiles
- Shared application and right-click action menus
- Online subtitle finder that opens targeted subtitle searches and loads downloaded subtitle files
- External subtitle loading
- Fit or cover-screen video mode for fullscreen playback
- A-B loop controls
- Playback speed cycling
- Screenshots saved as `CometPlayer_YYYYMMDD_HHMMSS.png`
- In-window compact and picture-in-picture modes with exact state restoration
- Drag-and-drop files, folders, and URLs
- Always-on-top toggle
- Local Python plugins with isolated lifecycle, event listeners, preferences, player/playlist APIs, menu actions, and sidebar tabs
- Per-file crop, aspect ratio, and rotation state

## Keyboard Shortcuts

| Shortcut | Action |
| --- | --- |
| Space | Play or pause |
| Left Arrow | Seek backward 5 seconds |
| Right Arrow | Seek forward 5 seconds |
| Up Arrow | Volume up |
| Down Arrow | Volume down |
| M | Mute or unmute |
| F | Toggle fullscreen |
| C | Toggle fit or cover-screen video mode |
| Esc | Pause and minimize to the taskbar |
| Middle mouse button | Toggle compact player mode |
| P | Toggle playlist |
| T | Toggle always on top |
| S | Save screenshot |
| Ctrl+O | Open media files |
| Ctrl+U | Open URL |
| Period | Next item |
| Comma | Previous item |

## Window and rendering architecture

- libmpv renders through `MpvRenderContext` into one Qt-owned `QOpenGLWidget`.
- Title, menu, controls, OSD, and playlist are ordinary child overlays in the same Qt tree.
- `WindowModeController` owns normal, maximized, fullscreen, compact, and PiP transitions.
- `OverlayController` owns chrome animation and overlay geometry.
- `PlayerInputController` owns application shortcuts, middle-click compact mode, and playlist outside-click behavior.
- No native mpv child window, global native mouse hook, or delayed geometry correction is used.

## Plugins

Open **Plugins → Open Plugins Folder** and create one folder per plugin. A minimal plugin contains:

```json
{
  "id": "example.hello",
  "name": "Hello",
  "version": "1.0.0",
  "description": "A small example",
  "entry": "main.py"
}
```

```python
def setup(api):
    api.menu.add("Say hello", lambda: api.core.osd("Hello from a plugin"))
    api.events.on("file.loaded", lambda event: print(event["source"]))
    api.playlist.add_context_item("Inspect row", lambda index, source: print(index, source))
    api.sidebar.register("Hello", lambda: "Plugin sidebar content")
```

Use **Plugins → Manage Plugins** to discover, enable, disable, and reload extensions. Plugins are trusted local Python code; enable only plugins you trust. Each plugin gets its own JSON preference file and all of its registrations are removed when it is disabled.

Run the regression suite from the workspace root:

```powershell
python -m unittest discover -s tests -v
```
