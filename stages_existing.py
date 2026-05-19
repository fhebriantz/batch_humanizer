"""Wrap effect existing jadi Stage — TANPA modifikasi logic.

Tiap class di sini cuma manggil fungsi yang sudah ada di humanizer.py
atau menghasilkan filter string yang identik dengan ffmpeg_post_process lama.
"""

import random
from pathlib import Path

import humanizer as _hum
from pipeline import Stage


# ============================================================
# LAYER: MOVIEPY
# ============================================================

class CropStage(Stage):
    name = "crop"
    layer = "moviepy"

    def is_enabled(self, features):
        return features.get("crop", "none") != "none"

    def apply_moviepy(self, clip, features, ctx):
        return _hum.crop_watermark(clip, features["crop"])


class JitterStage(Stage):
    name = "jitter"
    layer = "moviepy"

    def apply_moviepy(self, clip, features, ctx):
        return _hum.apply_jitter(clip)


# ============================================================
# LAYER: FFMPEG_FILTER (single pass)
# ============================================================

class MirrorStage(Stage):
    name = "mirror"
    layer = "ffmpeg_filter"

    def ffmpeg_filter(self, features, ctx):
        return "hflip"


class GrainStage(Stage):
    name = "grain"
    layer = "ffmpeg_filter"

    def ffmpeg_filter(self, features, ctx):
        strength = int(_hum.GRAIN_INTENSITY * 255)
        return f"noise=alls={strength}:allf=t"


class ColorJitterStage(Stage):
    name = "color_jitter"
    layer = "ffmpeg_filter"

    def ffmpeg_filter(self, features, ctx):
        rng = random.Random()
        brightness = rng.uniform(-0.02, 0.02)
        contrast = rng.uniform(1.0, 1.05)
        saturation = rng.uniform(1.0, 1.1)
        gamma_r = rng.uniform(0.98, 1.02)
        gamma_b = rng.uniform(0.98, 1.02)
        return (
            f"eq=brightness={brightness:.4f}"
            f":contrast={contrast:.4f}"
            f":saturation={saturation:.4f}"
            f":gamma_r={gamma_r:.4f}"
            f":gamma_b={gamma_b:.4f}"
        )


class ResizeStage(Stage):
    name = "resize"
    layer = "ffmpeg_filter"

    def ffmpeg_filter(self, features, ctx):
        return (
            f"scale={_hum.TARGET_W}:{_hum.TARGET_H}:force_original_aspect_ratio=increase,"
            f"setsar=1,"
            f"crop={_hum.TARGET_W}:{_hum.TARGET_H}"
        )


# ============================================================
# LAYER: FFMPEG_STREAM (copy stream ops)
# ============================================================

class ScrubStage(Stage):
    name = "scrub"
    layer = "ffmpeg_stream"

    def ffmpeg_stream(self, video_path: Path, features, ctx):
        _hum.scrub_metadata(video_path)


# ============================================================
# REGISTRATION
# ============================================================

def register_existing(pipeline):
    """Daftar semua stage existing ke pipeline (urut sesuai pipeline lama)."""
    # MoviePy phase
    pipeline.register(CropStage())
    pipeline.register(JitterStage())
    # FFmpeg filter phase (single pass)
    pipeline.register(MirrorStage())
    pipeline.register(GrainStage())
    pipeline.register(ColorJitterStage())
    pipeline.register(ResizeStage())
    # FFmpeg stream phase
    pipeline.register(ScrubStage())
