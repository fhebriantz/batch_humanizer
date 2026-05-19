"""Enhancement stages — retention-boost features yang baru.

Beda dengan stages_existing.py:
  - Fitur baru, tidak ada di humanizer.py
  - Default OFF, tidak ubah perilaku existing user
  - Bisa dikembangkan tanpa sentuh existing layer
"""

from pathlib import Path

from pipeline import Stage


# ============================================================
# BEAT-SYNC ZOOM PUNCH
# ============================================================

class BeatZoomPunchStage(Stage):
    """Subtle zoom punch yang sync dengan beat lagu.

    Cara kerja:
      1. Detect beat times pakai librosa dari audio video
      2. Generate FFmpeg zoompan filter dengan Gaussian peak di tiap beat
      3. Filter ini gabung ke single-pass FFmpeg existing — tidak nambah encode

    Constraint design:
      - Peak zoom 1.03x (subtle, di atas jitter 1.01x jadi compound ~1.0403x)
      - Gaussian width tight (~150ms efek per beat, sebagian besar di 1.0-1.015x)
      - Sync-safe: zoom-only, tidak ubah timing (audio tetap, dance tetap on-beat)
      - Jitter existing tidak diganggu (layer berbeda)
    """

    name = "beat_zoom"
    layer = "ffmpeg_filter"

    PEAK_ZOOM_EXTRA = 0.03   # zoom max = 1 + 0.03 = 1.03x
    GAUSSIAN_WIDTH = 150     # bell sharpness — higher = narrower peak (~150ms FWHM)

    def ffmpeg_filter(self, features, ctx):
        beats = self._get_beats(ctx)
        if not beats:
            print("  [beat_zoom] tidak ada beat terdeteksi, skip filter")
            return None

        width = ctx["width"]
        height = ctx["height"]
        fps = ctx.get("fps", 30)
        fps_int = int(round(fps))

        # zoompan tidak punya variable 't' — pakai 'on' (output frame index).
        # Konversi beat times → beat frames, lalu compute gaussian dalam frame domain:
        #   t_relative = (on - beat_frame) / fps
        #   gauss = exp(-WIDTH * t_relative^2) = exp(-(WIDTH/fps^2) * (on - beat_frame)^2)
        w_frame = self.GAUSSIAN_WIDTH / (fps * fps)
        terms = [
            f"exp(-{w_frame:.6f}*pow(on-{b * fps:.1f}\\,2))"
            for b in beats
        ]
        zoom_expr = f"1+{self.PEAK_ZOOM_EXTRA}*({'+'.join(terms)})"

        # zoompan d=1 → tiap input frame = 1 output frame.
        # x,y center crop biar zoom-nya in-place (tidak pan).
        return (
            f"zoompan=z='{zoom_expr}'"
            f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
            f":d=1:s={width}x{height}:fps={fps_int}"
        )

    def _get_beats(self, ctx) -> list:
        """Detect beat times dari audio video. Cached di ctx."""
        if "beats" in ctx:
            return ctx["beats"]

        try:
            import librosa
        except ImportError:
            print("  [beat_zoom] WARN: librosa tidak terinstall, skip")
            ctx["beats"] = []
            return []

        import numpy as np
        input_path = ctx["input_path"]
        try:
            # Load audio dari video (librosa pakai audioread/ffmpeg backend)
            print(f"  [beat_zoom] detecting beats from {Path(input_path).name}...")
            y, sr = librosa.load(str(input_path), sr=22050, mono=True)
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
            # librosa 0.10+: tempo bisa array 1-D, perlu .item() atau index
            tempo_val = float(np.atleast_1d(tempo)[0])
            print(f"  [beat_zoom] tempo ~{tempo_val:.1f} BPM, {len(beat_times)} beats")
            ctx["beats"] = beat_times
            return beat_times
        except Exception as e:
            print(f"  [beat_zoom] WARN: beat detection gagal: {e}")
            ctx["beats"] = []
            return []


# ============================================================
# REGISTRATION
# ============================================================

def register_enhancement(pipeline):
    """Daftar semua enhancement stage ke pipeline."""
    pipeline.register(BeatZoomPunchStage())
