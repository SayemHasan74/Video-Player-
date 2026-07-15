"""Validated libmpv color/HDR pipeline configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VideoPipelineConfig:
    """User-facing output intent translated to safe mpv properties.

    The Qt render API owns the actual swapchain.  SDR/wide-gamut modes
    therefore describe the Qt surface and make mpv convert into that target.
    HDR passthrough is explicit because Windows, the compositor and the GPU
    must all support tagging the surface correctly.
    """

    hwdec: str = "auto-safe"
    hwdec_fallback: bool = True
    color_space: str = "srgb"
    hdr_mode: str = "auto"
    tone_mapping: str = "auto"
    gamut_mapping: str = "auto"
    hdr_peak_detection: str = "auto"
    icc_profile: str = ""

    @classmethod
    def from_settings(cls, settings: Any) -> "VideoPipelineConfig":
        return cls(
            hwdec=str(settings.get("video.hwdec", "auto-safe")),
            hwdec_fallback=bool(settings.get("video.hwdec_fallback", True)),
            color_space=str(settings.get("video.color_space", "srgb")),
            hdr_mode=str(settings.get("video.hdr_mode", "auto")),
            tone_mapping=str(settings.get("video.tone_mapping", "auto")),
            gamut_mapping=str(settings.get("video.gamut_mapping", "auto")),
            hdr_peak_detection=str(settings.get("video.hdr_peak_detection", "auto")),
            icc_profile=str(settings.get("video.icc_profile", "")).strip(),
        ).validated()

    def validated(self) -> "VideoPipelineConfig":
        hwdec = self.hwdec if self.hwdec in {"auto-safe", "auto", "no"} else "auto-safe"
        color_space = self.color_space if self.color_space in {"srgb", "display-p3"} else "srgb"
        hdr_mode = self.hdr_mode if self.hdr_mode in {"auto", "sdr", "passthrough"} else "auto"
        tone_mapping = self.tone_mapping if self.tone_mapping in {
            "auto", "clip", "mobius", "reinhard", "hable", "bt.2390"
        } else "auto"
        gamut_mapping = self.gamut_mapping if self.gamut_mapping in {
            "auto", "clip", "perceptual", "relative", "saturation", "desaturate"
        } else "auto"
        peak = self.hdr_peak_detection if self.hdr_peak_detection in {"auto", "yes", "no"} else "auto"
        profile = self.icc_profile if self.icc_profile and Path(self.icc_profile).is_file() else ""
        return VideoPipelineConfig(
            hwdec=hwdec,
            hwdec_fallback=self.hwdec_fallback,
            color_space=color_space,
            hdr_mode=hdr_mode,
            tone_mapping=tone_mapping,
            gamut_mapping=gamut_mapping,
            hdr_peak_detection=peak,
            icc_profile=profile,
        )

    def mpv_properties(self) -> dict[str, object]:
        if self.hdr_mode == "passthrough":
            target_prim, target_trc, hint, hint_mode = "bt.2020", "pq", "yes", "source"
        else:
            target_prim = "display-p3" if self.color_space == "display-p3" else "bt.709"
            target_trc = "srgb"
            # In render-API mode Qt owns the swapchain.  Converting into the
            # declared Qt surface is the reliable SDR fallback.
            hint, hint_mode = "no", "target"
        properties: dict[str, object] = {
            "hwdec": self.hwdec,
            "target-prim": target_prim,
            "target-trc": target_trc,
            "target-colorspace-hint": hint,
            "target-colorspace-hint-mode": hint_mode,
            "tone-mapping": self.tone_mapping,
            "gamut-mapping-mode": self.gamut_mapping,
            "hdr-compute-peak": self.hdr_peak_detection,
        }
        if self.icc_profile:
            properties["icc-profile"] = self.icc_profile
        return properties
