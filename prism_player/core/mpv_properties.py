"""Central names for every mpv property, option, and command Comet touches."""

from __future__ import annotations


# Timeline and lifecycle
TIME_POS = "time-pos"
DURATION = "duration"
PAUSE = "pause"
PATH = "path"
EOF_REACHED = "eof-reached"
SEEKING = "seeking"
PAUSED_FOR_CACHE = "paused-for-cache"
CACHE_BUFFERING_STATE = "cache-buffering-state"

# Playback
VOLUME = "volume"
MUTE = "mute"
SPEED = "speed"
VID = "vid"
AID = "aid"
SID = "sid"
SECONDARY_SID = "secondary-sid"
PANSCAN = "panscan"
VIDEO_UNSCALED = "video-unscaled"
AB_LOOP_A = "ab-loop-a"
AB_LOOP_B = "ab-loop-b"

# Decoder/output
HWDEC = "hwdec"
KEEPASPECT_WINDOW = "keepaspect-window"
HWDEC_CURRENT = "hwdec-current"
VO = "vo"
GPU_CONTEXT = "gpu-context"
TARGET_PRIM = "target-prim"
TARGET_TRC = "target-trc"
TARGET_COLORSPACE_HINT = "target-colorspace-hint"
TARGET_COLORSPACE_HINT_MODE = "target-colorspace-hint-mode"
TONE_MAPPING = "tone-mapping"
GAMUT_MAPPING_MODE = "gamut-mapping-mode"
HDR_COMPUTE_PEAK = "hdr-compute-peak"
ICC_PROFILE = "icc-profile"
VIDEO_PARAMS = "video-params"
WIDTH = "width"
HEIGHT = "height"

# Tracks, metadata, and filters
TRACK_LIST = "track-list"
CHAPTER_LIST = "chapter-list"
METADATA = "metadata"
VF = "vf"
AF = "af"
VIDEO_ASPECT_OVERRIDE = "video-aspect-override"
VIDEO_ROTATE = "video-rotate"
BRIGHTNESS = "brightness"
CONTRAST = "contrast"
SATURATION = "saturation"
GAMMA = "gamma"
HUE = "hue"

# Audio and subtitles
AUDIO_DELAY = "audio-delay"
SUB_DELAY = "sub-delay"
SECONDARY_SUB_DELAY = "secondary-sub-delay"
SUB_VISIBILITY = "sub-visibility"
SECONDARY_SUB_VISIBILITY = "secondary-sub-visibility"
SUB_FONT = "sub-font"
SUB_FONT_SIZE = "sub-font-size"
SUB_COLOR = "sub-color"
SUB_BORDER_SIZE = "sub-border-size"
SUB_SHADOW_OFFSET = "sub-shadow-offset"
SUB_POS = "sub-pos"
SUB_CODEPAGE = "sub-codepage"
AUDIO_DEVICE = "audio-device"
AUDIO_DEVICE_LIST = "audio-device-list"
ALANG = "alang"
REPLAYGAIN = "replaygain"
REPLAYGAIN_PREAMP = "replaygain-preamp"
REPLAYGAIN_CLIP = "replaygain-clip"
REPLAYGAIN_FALLBACK = "replaygain-fallback"
GAPLESS_AUDIO = "gapless-audio"

# Cache and diagnostics
DEMUXER_CACHE_STATE = "demuxer-cache-state"
DEMUXER_CACHE_DURATION = "demuxer-cache-duration"
CONTAINER_FPS = "container-fps"
DISPLAY_FPS = "display-fps"
FRAME_DROP_COUNT = "frame-drop-count"
AVSYNC = "avsync"

# Network
HTTP_PROXY = "http-proxy"
USER_AGENT = "user-agent"

# Commands
CMD_LOADFILE = "loadfile"
CMD_STOP = "stop"
CMD_SEEK = "seek"
CMD_VIDEO_FILTER = "vf"
CMD_AUDIO_FILTER = "af"
CMD_SUB_ADD = "sub-add"
CMD_SCREENSHOT_TO_FILE = "screenshot-to-file"


OBSERVED_PROPERTIES = (
    TIME_POS, DURATION, PAUSE, PATH, EOF_REACHED, SEEKING, PAUSED_FOR_CACHE,
    CACHE_BUFFERING_STATE,
    VOLUME, MUTE, SPEED, VID, AID, SID, SECONDARY_SID, HWDEC, HWDEC_CURRENT,
    TRACK_LIST, CHAPTER_LIST, METADATA, VIDEO_PARAMS, WIDTH, HEIGHT, VF, AF,
    DEMUXER_CACHE_STATE, AUDIO_DEVICE_LIST, VIDEO_ASPECT_OVERRIDE, VIDEO_ROTATE,
    BRIGHTNESS, CONTRAST, SATURATION, GAMMA, HUE, AUDIO_DELAY, SUB_DELAY,
    SECONDARY_SUB_DELAY, SUB_VISIBILITY, SECONDARY_SUB_VISIBILITY, SUB_FONT,
    SUB_FONT_SIZE, SUB_COLOR, SUB_BORDER_SIZE, SUB_SHADOW_OFFSET, SUB_POS,
    SUB_CODEPAGE, REPLAYGAIN, REPLAYGAIN_PREAMP, REPLAYGAIN_CLIP, GAPLESS_AUDIO,
    AUDIO_DEVICE, ALANG, TARGET_PRIM, TARGET_TRC, TONE_MAPPING,
    GAMUT_MAPPING_MODE, CONTAINER_FPS, DISPLAY_FPS, FRAME_DROP_COUNT, AVSYNC,
    DEMUXER_CACHE_DURATION,
)
