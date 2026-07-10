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
- Online subtitle finder that opens targeted subtitle searches and loads downloaded subtitle files
- External subtitle loading
- Fit or cover-screen video mode for fullscreen playback
- A-B loop controls
- Playback speed cycling
- Screenshots saved as `CometPlayer_YYYYMMDD_HHMMSS.png`
- Picture-in-picture shell
- Drag-and-drop files, folders, and URLs
- Always-on-top toggle

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
| Esc | Exit fullscreen |
| P | Toggle playlist |
| T | Toggle always on top |
| S | Save screenshot |
| Ctrl+O | Open media files |
| Ctrl+U | Open URL |
| Period | Next item |
| Comma | Previous item |
