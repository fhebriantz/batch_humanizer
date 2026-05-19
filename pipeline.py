"""Modular processing pipeline.

Tiap effect dibungkus jadi Stage. Pipeline jalanin stage per layer:
  - moviepy        : frame-level Python ops (jitter, crop)
  - ffmpeg_filter  : digabung jadi satu pass FFmpeg (mirror, grain, color, resize, beat zoom)
  - ffmpeg_stream  : stream copy ops (metadata scrub)

Effect existing dibungkus tanpa modifikasi logic — lihat stages_existing.py.
Enhancement baru ditaruh di stages_enhancement.py.
"""

from pathlib import Path


# ============================================================
# STAGE BASE
# ============================================================

class Stage:
    """Base class untuk satu effect.

    Subclass override method sesuai layer-nya:
      - layer="moviepy"        → override apply_moviepy()
      - layer="ffmpeg_filter"  → override ffmpeg_filter()
      - layer="ffmpeg_stream"  → override ffmpeg_stream()
    """

    name: str = ""
    layer: str = ""  # "moviepy" | "ffmpeg_filter" | "ffmpeg_stream"

    def is_enabled(self, features: dict) -> bool:
        """Cek apakah stage ini aktif. Default: lihat features[name]."""
        return bool(features.get(self.name, False))

    def apply_moviepy(self, clip, features: dict, ctx: dict):
        """Untuk layer moviepy. Return clip yang sudah diproses."""
        return clip

    def ffmpeg_filter(self, features: dict, ctx: dict):
        """Untuk layer ffmpeg_filter. Return string filter atau None."""
        return None

    def ffmpeg_stream(self, video_path: Path, features: dict, ctx: dict):
        """Untuk layer ffmpeg_stream. Modifikasi file in-place."""
        return None


# ============================================================
# PIPELINE
# ============================================================

class Pipeline:
    """Orchestrator yang jalanin stages per layer."""

    LAYERS = ("moviepy", "ffmpeg_filter", "ffmpeg_stream")

    def __init__(self):
        self.stages: list[Stage] = []

    def register(self, stage: Stage):
        """Tambah stage ke pipeline."""
        if stage.layer not in self.LAYERS:
            raise ValueError(f"Invalid layer '{stage.layer}' di stage '{stage.name}'")
        self.stages.append(stage)

    def by_layer(self, layer: str) -> list[Stage]:
        """Ambil semua stage di layer tertentu, urut sesuai register order."""
        return [s for s in self.stages if s.layer == layer]

    def active_by_layer(self, layer: str, features: dict) -> list[Stage]:
        """Stage di layer yang aktif (is_enabled=True)."""
        return [s for s in self.by_layer(layer) if s.is_enabled(features)]

    def has_active(self, layer: str, features: dict) -> bool:
        return bool(self.active_by_layer(layer, features))
