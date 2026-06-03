# mpv-2.dll Setup

Prism Player uses `python-mpv`, which needs the Windows `mpv-2.dll` library.

1. Go to https://sourceforge.net/projects/mpv-player-windows/files/libmpv/
2. Download the latest `mpv-dev-x86_64` zip.
3. Extract the zip and find `mpv-2.dll`. If the file is named `libmpv-2.dll`, rename it to `mpv-2.dll`.
4. Place `mpv-2.dll` in the same directory as `prism_player/main.py`, beside the workspace-root `main.py`, or in a folder on `PATH`.
5. From this folder, run:

```powershell
python main.py
```

You can also place `mpv-2.dll` in a directory listed on your Windows `PATH`.
