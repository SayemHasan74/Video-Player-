# mpv-2.dll Setup

Comet Player uses `python-mpv` with one deliberately vendored x86-64 DLL.

1. Obtain an x86-64 libmpv build from `shinchiro/mpv-winbuild-cmake`.
2. Place it at the fixed path `bin/mpv-2.dll`.
3. Record its exact build identifier and upgrade notes in `bin/MPV_VERSION.txt`.
4. Run the pre-Qt playback test with a real media file:

```powershell
python tools/mpv_sanity_check.py "C:\Media\test-video.mkv"
```

The application never searches or modifies `PATH`. Frozen builds must include
the DLL as `bin/mpv-2.dll` and must be verified on clean Windows 11.
