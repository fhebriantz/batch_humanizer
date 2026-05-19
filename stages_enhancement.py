"""Enhancement stages — retention-boost features yang baru.

Beda dengan stages_existing.py:
  - Fitur baru, tidak ada di humanizer.py
  - Default OFF, tidak ubah perilaku existing user
  - Bisa dikembangkan tanpa sentuh existing layer
"""

from pathlib import Path

from pipeline import Stage


# ============================================================
# SHARED HELPER: BEAT DETECTION
# ============================================================

def _detect_beats(ctx) -> list:
    """Detect beat times dari audio video. Cached di ctx.

    Dipakai oleh BeatZoomPunchStage dan BeatStepZoomStage.
    Detection cuma run sekali per video walaupun beberapa stage minta.
    """
    if "beats" in ctx:
        return ctx["beats"]

    try:
        import librosa
        import numpy as np
    except ImportError:
        print("  [beat detection] WARN: librosa tidak terinstall, skip")
        ctx["beats"] = []
        return []

    input_path = ctx["input_path"]
    try:
        print(f"  [beat detection] from {Path(input_path).name}...")
        y, sr = librosa.load(str(input_path), sr=22050, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        tempo_val = float(np.atleast_1d(tempo)[0])
        print(f"  [beat detection] tempo ~{tempo_val:.1f} BPM, {len(beat_times)} beats")
        ctx["beats"] = beat_times
        return beat_times
    except Exception as e:
        print(f"  [beat detection] WARN: gagal: {e}")
        ctx["beats"] = []
        return []


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
        beats = _detect_beats(ctx)
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


# ============================================================
# BEAT STEP ZOOM — alternating zoom per 4-beat group
# ============================================================

class BeatStepZoomStage(Stage):
    """Zoom alternates 1.0x ↔ 1.15x setiap 4 beats.

    Spesifikasi:
      - Group 0 (beats 0-3)   : zoom 1.0x
      - Group 1 (beats 4-7)   : zoom 1.15x
      - Group 2 (beats 8-11)  : zoom 1.0x
      - Group 3 (beats 12-15) : zoom 1.15x
      - ... alternating
      - Group terakhir kalau < 4 beats: tetap pakai zoom dari group sebelumnya
        (tidak ganti zoom di sisa akhir video)

    Pakai FFmpeg zoompan dengan tanh-based smooth transition supaya tidak snap.
    Layer ffmpeg_filter → masuk single-pass dengan beat_zoom.

    Feature key tetap 'random_crop' biar backward compat UI/CLI.
    """

    name = "random_crop"      # keep CLI/UI key
    layer = "ffmpeg_filter"

    BEATS_PER_GROUP = 4
    LOW_ZOOM = 1.0
    HIGH_ZOOM = 1.15
    TRANSITION_WIDTH_FRAMES = 4   # tanh width — ~270ms transition @ 30fps

    def ffmpeg_filter(self, features, ctx):
        beats = _detect_beats(ctx)
        if not beats:
            print("  [beat_step_zoom] tidak ada beat terdeteksi, skip filter")
            return None
        if len(beats) < self.BEATS_PER_GROUP:
            print(f"  [beat_step_zoom] beats kurang dari {self.BEATS_PER_GROUP}, skip filter")
            return None

        width = ctx["width"]
        height = ctx["height"]
        fps = ctx.get("fps", 30)
        fps_int = int(round(fps))
        duration = ctx.get("duration", 30)

        # Build chunk schedule: alternating LOW/HIGH per BEATS_PER_GROUP
        # Last incomplete chunk (< BEATS_PER_GROUP): skip (keep previous zoom)
        chunks = []  # list of (start_time, is_high)
        chunk_idx = 0
        for i in range(0, len(beats), self.BEATS_PER_GROUP):
            chunk_beats = beats[i:i + self.BEATS_PER_GROUP]
            # Incomplete tail group: jangan ubah zoom (extend previous group)
            if len(chunk_beats) < self.BEATS_PER_GROUP and len(chunks) > 0:
                break
            if not chunk_beats:
                continue
            is_high = (chunk_idx % 2 == 1)  # group 0 LOW, 1 HIGH, 2 LOW, ...
            chunks.append((chunk_beats[0], is_high))
            chunk_idx += 1

        if not chunks:
            return None

        # Find HIGH intervals: [(start_frame, end_frame), ...]
        high_intervals = []
        for i, (start_t, is_high) in enumerate(chunks):
            if not is_high:
                continue
            # End = start of next chunk, or end of video (+1s buffer)
            end_t = chunks[i + 1][0] if i + 1 < len(chunks) else duration + 1.0
            high_intervals.append((start_t * fps, end_t * fps))

        if not high_intervals:
            print("  [beat_step_zoom] tidak ada group HIGH, skip filter")
            return None

        # FFmpeg expression:
        #   z = LOW + (HIGH - LOW) * sum_of_indicators
        # Indicator per HIGH interval [s, e]:
        #   0.5 * (tanh((on - s) / W) - tanh((on - e) / W))
        # → smooth transition di edges, plateau di tengah
        W = self.TRANSITION_WIDTH_FRAMES
        delta = self.HIGH_ZOOM - self.LOW_ZOOM
        terms = [
            f"0.5*(tanh((on-{s:.1f})/{W})-tanh((on-{e:.1f})/{W}))"
            for s, e in high_intervals
        ]
        indicator_sum = "+".join(terms)
        zoom_expr = f"{self.LOW_ZOOM}+{delta:.3f}*({indicator_sum})"

        # Anchor — horizontal selalu center, vertical sesuai pilihan user
        anchor = features.get("random_crop_anchor", "bottom")
        if anchor == "top":
            y_expr = "0"                # top edge preserved, bottom ke-crop
        elif anchor == "center":
            y_expr = "(ih-ih/zoom)/2"   # center-center, bagian atas+bawah ke-crop seimbang
        else:  # bottom (default)
            y_expr = "ih-ih/zoom"       # bottom edge preserved, top ke-crop

        print(f"  [beat_step_zoom] {len(chunks)} groups, {len(high_intervals)} HIGH, anchor={anchor}")

        return (
            f"zoompan=z='{zoom_expr}'"
            f":x='(iw-iw/zoom)/2':y='{y_expr}'"
            f":d=1:s={width}x{height}:fps={fps_int}"
        )


# ============================================================
# REGISTRATION
# ============================================================

def register_enhancement(pipeline):
    """Daftar semua enhancement stage ke pipeline.

    Semua enhancement di layer ffmpeg_filter — masuk single-pass bareng
    existing FFmpeg filter (mirror, grain, color_jitter, resize).
    Share beat detection via ctx cache — deteksi cuma run 1x per video.
    """
    pipeline.register(BeatZoomPunchStage())
    pipeline.register(BeatStepZoomStage())
