"""
Batch Video & Image Humanizer
Menghapus jejak AI dari video/gambar influencer secara batch.
Fitur: auto-crop watermark, grain, mirror, subtle jitter, metadata scrub, resize.
"""

import argparse
import sys
import json
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
from moviepy import VideoFileClip


# ============================================================
# CONFIG
# ============================================================

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")

# Geometri output
TARGET_W = 1080             # output width standar 9:16
TARGET_H = 1920             # output height standar 9:16
CROP_PERCENT = 0.035        # 3.5% atas & bawah

# Intensitas efek humanizer
GRAIN_INTENSITY = 0.03      # 3% noise
JITTER_SCALE = 1.01         # zoom 1.01x
JITTER_INTERVAL = 0.5       # ganti offset tiap 0.5 detik

# Encoding & bitrate
LIBX264_BITRATE = "8000k"   # bitrate final path CPU
VAAPI_QP = 32               # constant quantizer VA-API (lower = tajam & gede)
NVENC_BITRATE = "8000k"     # bitrate NVENC
QSV_BITRATE = "8000k"       # bitrate QSV
INTERMEDIATE_CRF = "18"     # kualitas MoviePy intermediate (hampir lossless, karena akan di-encode ulang FFmpeg)
FFMPEG_TIMEOUT = 600        # detik — cegah hang selamanya kalau FFmpeg stuck

IPHONE_METADATA = {
    "Make": "Apple",
    "Model": "iPhone 13",
    "Software": "16.6",
    "FNumber": "f/1.8",
    "FocalLength": "5.1 mm",
    "LensModel": "iPhone 13 back dual wide camera 5.1mm f/1.6",
    "ColorSpace": "sRGB",
    "encoder": "Lavf60.16.100",
    "major_brand": "qt  ",
    "minor_version": "0",
    "compatible_brands": "qt  ",
    "com.apple.quicktime.make": "Apple",
    "com.apple.quicktime.model": "iPhone 13",
    "com.apple.quicktime.software": "16.6",
    "com.apple.quicktime.creationdate": "",  # diisi dinamis
}

# Encoder config
# MoviePy selalu pakai libx264 (bundled FFmpeg tidak support GPU encoder)
# GPU encoder hanya untuk FFmpeg CLI post-processing (color jitter, resize)
ACTIVE_ENCODER = {
    "name": "libx264",
    "input_args": [],
    "filter_suffix": "",
    "output_args": ["-preset", "medium", "-b:v", LIBX264_BITRATE],
}

VIDEO_EXTS = {".mp4"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


# ============================================================
# INTERACTIVE PROMPT
# ============================================================

def ask_yn(question: str, default: bool = True) -> bool:
    """Tanya y/n ke user. Default ditandai huruf besar."""
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"  {question} [{hint}]: ").strip().lower()
        if answer == "":
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Ketik y atau n.")


def ask_crop_mode() -> str:
    """Tanya user mau crop mode apa."""
    print("  Pilih mode crop:")
    print("    1. Atas + Bawah (default)")
    print("    2. Atas saja")
    print("    3. Bawah saja")
    while True:
        answer = input("  Pilihan [1]: ").strip()
        if answer in ("", "1"):
            return "both"
        if answer == "2":
            return "top"
        if answer == "3":
            return "bottom"
        print("  Ketik 1, 2, atau 3.")


def ask_anchor_mode() -> str:
    """Tanya user mau anchor zoom di mana (untuk beat step zoom)."""
    print("  Pilih anchor zoom:")
    print("    1. Bottom (default - bagian bawah tidak terpotong)")
    print("    2. Center (atas+bawah terpotong seimbang)")
    print("    3. Top    (bagian atas tidak terpotong)")
    while True:
        answer = input("  Pilihan [1]: ").strip()
        if answer in ("", "1"):
            return "bottom"
        if answer == "2":
            return "center"
        if answer == "3":
            return "top"
        print("  Ketik 1, 2, atau 3.")


def interactive_setup(has_video: bool) -> dict:
    """Tanya user fitur apa saja yang mau dijalankan."""
    print("=" * 60)
    print("  PILIH FITUR YANG MAU DIJALANKAN")
    print("=" * 60)

    features = {}

    # Crop
    if ask_yn("Crop watermark (potong 3.5% atas/bawah)?"):
        features["crop"] = ask_crop_mode()
    else:
        features["crop"] = "none"

    # Mirror
    features["mirror"] = ask_yn("Mirror (flip horizontal)?")

    # Grain
    features["grain"] = ask_yn("Grain/noise (overlay 3%)?")

    # Jitter (video only)
    if has_video:
        features["jitter"] = ask_yn("Jitter/zoom subtle (video only)?")
    else:
        features["jitter"] = False

    # Color jitter
    features["color_jitter"] = ask_yn("Color jitter (random brightness/contrast/saturation/gamma)?")

    # Resize
    features["resize"] = ask_yn(f"Resize ke {TARGET_W}x{TARGET_H} (fill & crop)?")

    # Metadata scrub (video only)
    if has_video:
        features["scrub"] = ask_yn("Scrub metadata & inject iPhone 13 (video only)?")
    else:
        features["scrub"] = False

    # Beat zoom punch (video only, retention enhancement)
    if has_video:
        features["beat_zoom"] = ask_yn(
            "Beat zoom punch — subtle zoom sync ke beat lagu (video only)?",
            default=False,
        )
    else:
        features["beat_zoom"] = False

    # Beat step zoom (alternating 1.0/1.20 per 4 beats)
    if has_video:
        features["random_crop"] = ask_yn(
            "Beat step zoom — zoom 1.0x <-> 1.15x ganti tiap 4 beats (video only)?",
            default=False,
        )
        if features["random_crop"]:
            features["random_crop_anchor"] = ask_anchor_mode()
        else:
            features["random_crop_anchor"] = "bottom"
    else:
        features["random_crop"] = False
        features["random_crop_anchor"] = "bottom"

    # GPU
    features["gpu"] = ask_yn("Gunakan GPU encoder (lebih cepat)?", default=False)

    print()
    return features


# ============================================================
# DETECTOR
# ============================================================

def detect_aspect(width: int, height: int) -> str:
    """Deteksi rasio aspek: 9:16, 2:3, atau unknown."""
    ratio = round(width / height, 2)
    if abs(ratio - 9 / 16) < 0.03:
        return "9:16"
    if abs(ratio - 2 / 3) < 0.03:
        return "2:3"
    return f"unknown ({ratio:.2f})"


# ============================================================
# CROP (shared logic)
# ============================================================

def calc_crop(height: int, crop_mode: str) -> tuple:
    """Hitung pixel crop atas dan bawah berdasarkan mode."""
    if crop_mode == "none":
        return 0, 0
    top = int(height * CROP_PERCENT) if crop_mode in ("both", "top") else 0
    bottom = int(height * CROP_PERCENT) if crop_mode in ("both", "bottom") else 0
    return top, bottom


# ============================================================
# VIDEO PROCESSORS
# ============================================================

def crop_watermark(clip, crop_mode: str):
    """Potong video berdasarkan crop_mode."""
    if crop_mode == "none":
        return clip
    orig_w, orig_h = clip.size
    top, bottom = calc_crop(orig_h, crop_mode)
    new_h = orig_h - top - bottom
    return clip.cropped(x1=0, y1=top, x2=orig_w, y2=top + new_h)




def _smoothstep(t):
    """Smoothstep interpolation: percepat di awal, pelan di akhir."""
    return t * t * (3 - 2 * t)


def apply_jitter(clip):
    """Smooth drift zoom & pan — seperti goyang tangan pegang kamera."""
    w, h = clip.size
    rng = random.Random(42)
    waypoints = {}

    max_dx = max(int(w * (JITTER_SCALE - 1) / 2), 1)
    max_dy = max(int(h * (JITTER_SCALE - 1) / 2), 1)

    def get_waypoint(key):
        if key not in waypoints:
            dx = rng.randint(-max_dx, max_dx)
            dy = rng.randint(-max_dy, max_dy)
            waypoints[key] = (dx, dy)
        return waypoints[key]

    def get_smooth_offset(t):
        key = int(t / JITTER_INTERVAL)
        frac = (t / JITTER_INTERVAL) - key
        frac = _smoothstep(frac)

        x0, y0 = get_waypoint(key)
        x1, y1 = get_waypoint(key + 1)

        dx = x0 + (x1 - x0) * frac
        dy = y0 + (y1 - y0) * frac
        return dx, dy

    scaled_w = int(w * JITTER_SCALE)
    scaled_h = int(h * JITTER_SCALE)

    def jitter_transform(get_frame, t):
        frame = get_frame(t)
        img = Image.fromarray(frame)
        img_scaled = img.resize((scaled_w, scaled_h), Image.LANCZOS)

        dx, dy = get_smooth_offset(t)
        cx = int((scaled_w - w) / 2 + dx)
        cy = int((scaled_h - h) / 2 + dy)
        cx = max(0, min(cx, scaled_w - w))
        cy = max(0, min(cy, scaled_h - h))

        img_cropped = img_scaled.crop((cx, cy, cx + w, cy + h))
        return np.array(img_cropped)

    return clip.transform(jitter_transform)


# ============================================================
# IMAGE PROCESSORS (PIL)
# ============================================================

def crop_image(img: Image.Image, crop_mode: str) -> Image.Image:
    """Crop gambar berdasarkan mode."""
    if crop_mode == "none":
        return img
    w, h = img.size
    top, bottom = calc_crop(h, crop_mode)
    return img.crop((0, top, w, h - bottom))


def mirror_image(img: Image.Image) -> Image.Image:
    """Flip horizontal gambar."""
    return img.transpose(Image.FLIP_LEFT_RIGHT)


def grain_image(img: Image.Image) -> Image.Image:
    """Tambah grain/noise ke gambar."""
    arr = np.array(img, dtype=np.float32)
    noise = np.random.randint(0, 256, arr.shape, dtype=np.uint8).astype(np.float32)
    blended = arr * (1 - GRAIN_INTENSITY) + noise * GRAIN_INTENSITY
    return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8))


def fill_and_crop_image(img: Image.Image) -> Image.Image:
    """Scale proporsional + center-crop ke TARGET_W x TARGET_H."""
    w, h = img.size
    scale = max(TARGET_W / w, TARGET_H / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - TARGET_W) // 2
    top = (new_h - TARGET_H) // 2
    return img.crop((left, top, left + TARGET_W, top + TARGET_H))


# ============================================================
# COLOR JITTER — IMAGE (PIL)
# ============================================================

def color_jitter_image(img: Image.Image) -> Image.Image:
    """Random color jitter untuk gambar: brightness, contrast, saturation, gamma R/B."""
    from PIL import ImageEnhance

    rng = random.Random()

    # Brightness: -0.02 ~ +0.02 (ImageEnhance 1.0 = original)
    brightness = 1.0 + rng.uniform(-0.02, 0.02)
    img = ImageEnhance.Brightness(img).enhance(brightness)

    # Contrast: 1.0 ~ 1.05
    contrast = rng.uniform(1.0, 1.05)
    img = ImageEnhance.Contrast(img).enhance(contrast)

    # Saturation: 1.0 ~ 1.1
    saturation = rng.uniform(1.0, 1.1)
    img = ImageEnhance.Color(img).enhance(saturation)

    # Gamma Red/Blue: 0.98 ~ 1.02 (warm/cool shift)
    gamma_r = rng.uniform(0.98, 1.02)
    gamma_b = rng.uniform(0.98, 1.02)

    arr = np.array(img, dtype=np.float32) / 255.0
    arr[:, :, 0] = np.power(arr[:, :, 0], 1.0 / gamma_r)  # Red
    arr[:, :, 2] = np.power(arr[:, :, 2], 1.0 / gamma_b)  # Blue
    arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)

    return Image.fromarray(arr)


# ============================================================
# FFMPEG POST-PROCESSING (satu pass: mirror + grain + color + resize)
# ============================================================

def ffmpeg_post_process(video_path: Path, filter_strings: list):
    """Jalankan single FFmpeg pass dengan filter strings yang sudah di-build.

    Filter strings di-build oleh Stage objects (lihat stages_existing.py /
    stages_enhancement.py). Fungsi ini cuma handle FFmpeg command + execute.
    """
    if not filter_strings:
        return

    tmp_path = video_path.with_suffix(".post.mp4")
    vf = ",".join(filter_strings) + ACTIVE_ENCODER["filter_suffix"]

    # Audio humanize — subtle resample + volume shift untuk ganti audio hash
    # tanpa perubahan yang kedengeran. Pakai random volume supaya tiap run
    # beda dikit (0.97–1.0 range — di bawah 1.0 biar nggak pernah clipping).
    rng = random.Random()
    audio_volume = rng.uniform(0.97, 1.0)
    audio_filter = f"aresample=44100,volume={audio_volume:.4f}"

    cmd = [
        "ffmpeg", "-y",
        *ACTIVE_ENCODER["input_args"],
        "-i", str(video_path),
        "-vf", vf,
        "-af", audio_filter,
        "-c:v", ACTIVE_ENCODER["name"],
        *ACTIVE_ENCODER["output_args"],
        "-c:a", "aac",
        "-b:a", "128k",
        str(tmp_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        if tmp_path.exists():
            tmp_path.unlink()
        raise RuntimeError(f"FFmpeg post-process timeout setelah {FFMPEG_TIMEOUT}s (encoder={ACTIVE_ENCODER['name']})")

    if result.returncode != 0:
        if tmp_path.exists():
            tmp_path.unlink()
        tail = "\n".join(result.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"FFmpeg post-process gagal (encoder={ACTIVE_ENCODER['name']}):\n{tail}")

    video_path.unlink()
    tmp_path.rename(video_path)


# ============================================================
# METADATA SCRUBBER
# ============================================================

def scrub_metadata(video_path: Path):
    """Hapus semua metadata dan injeksi metadata iPhone 13 via FFmpeg."""
    from datetime import datetime, timedelta, timezone

    tmp_path = video_path.with_suffix(".tmp.mp4")

    # Buat creation_time random beberapa jam ke belakang (lebih natural)
    offset_hours = random.randint(1, 48)
    creation_time = (
        datetime.now(timezone.utc) - timedelta(hours=offset_hours)
    ).strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-map_metadata", "-1",
        "-metadata", f"creation_time={creation_time}",
        "-metadata", f"major_brand={IPHONE_METADATA['major_brand']}",
        "-metadata", f"minor_version={IPHONE_METADATA['minor_version']}",
        "-metadata", f"compatible_brands={IPHONE_METADATA['compatible_brands']}",
        "-metadata", f"encoder={IPHONE_METADATA['encoder']}",
        "-metadata", f"com.apple.quicktime.make={IPHONE_METADATA['com.apple.quicktime.make']}",
        "-metadata", f"com.apple.quicktime.model={IPHONE_METADATA['com.apple.quicktime.model']}",
        "-metadata", f"com.apple.quicktime.software={IPHONE_METADATA['com.apple.quicktime.software']}",
        "-metadata", f"com.apple.quicktime.creationdate={creation_time}",
        "-c", "copy",
        str(tmp_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"  [WARN] FFmpeg metadata scrub timeout setelah {FFMPEG_TIMEOUT}s")
        if tmp_path.exists():
            tmp_path.unlink()
        return

    if result.returncode != 0:
        print(f"  [WARN] FFmpeg metadata scrub gagal: {result.stderr[:200]}")
        if tmp_path.exists():
            tmp_path.unlink()
        return

    video_path.unlink()
    tmp_path.rename(video_path)


# ============================================================
# PIPELINE — VIDEO
# ============================================================

def _build_pipeline():
    """Build pipeline dengan semua stage existing + enhancement.

    Lazy import biar humanizer.py tetap bisa di-import oleh stages_existing.py
    tanpa circular import.
    """
    from pipeline import Pipeline
    from stages_existing import register_existing

    pipe = Pipeline()
    register_existing(pipe)

    # Enhancement stages (optional, dipanggil kalau modulnya ada)
    try:
        from stages_enhancement import register_enhancement
        register_enhancement(pipe)
    except ImportError:
        pass

    return pipe


def process_video(input_path: Path, output_path: Path, features: dict):
    """Pipeline lengkap untuk satu video — pakai modular Stage/Pipeline."""
    print(f"\n{'='*60}")
    print(f"  Processing (video): {input_path.name}")
    print(f"{'='*60}")

    clip = VideoFileClip(str(input_path))
    w, h = clip.size
    aspect = detect_aspect(w, h)
    original_audio = clip.audio

    print(f"  Resolution : {w}x{h}")
    print(f"  Aspect     : {aspect}")
    print(f"  Duration   : {clip.duration:.1f}s")
    print(f"  FPS        : {clip.fps}")

    pipe = _build_pipeline()
    ctx = {
        "width": w,
        "height": h,
        "duration": clip.duration,
        "fps": clip.fps,
        "input_path": input_path,
    }

    # Tentukan apakah FFmpeg phase akan jalan — berpengaruh ke kualitas MoviePy intermediate
    will_run_ffmpeg = pipe.has_active("ffmpeg_filter", features)

    # === PHASE 1: MoviePy stages (crop, jitter, ...) ===
    moviepy_stages = pipe.active_by_layer("moviepy", features)

    if moviepy_stages:
        total = len(moviepy_stages)
        for step, stage in enumerate(moviepy_stages, 1):
            if stage.name == "crop":
                mode = features["crop"]
                print(f"  [MoviePy {step}/{total}] Cropping watermark ({mode})...")
                clip = stage.apply_moviepy(clip, features, ctx)
                cw, ch = clip.size
                print(f"         After crop: {cw}x{ch}")
                ctx["width"], ctx["height"] = cw, ch
            elif stage.name == "jitter":
                print(f"  [MoviePy {step}/{total}] Adding subtle jitter (zoom {JITTER_SCALE:.2f}x)...")
                clip = stage.apply_moviepy(clip, features, ctx)
            else:
                print(f"  [MoviePy {step}/{total}] {stage.name}...")
                clip = stage.apply_moviepy(clip, features, ctx)

        # Restore audio & export — samain fps dengan source
        clip = clip.with_audio(original_audio)
        src_fps = clip.fps
        temp_audiofile = str(OUTPUT_DIR / f"temp_audio_{output_path.stem}.m4a")

        # Kalau file ini masih intermediate (bakal di-re-encode FFmpeg),
        # pakai CRF tinggi + preset cepat → minim generation loss & lebih cepat.
        # Kalau final, pakai bitrate target supaya size terkontrol.
        if will_run_ffmpeg:
            print(f"  Exporting via MoviePy @ {src_fps}fps (intermediate, CRF {INTERMEDIATE_CRF})...")
            write_kwargs = {
                "preset": "fast",
                "ffmpeg_params": ["-crf", INTERMEDIATE_CRF],
            }
        else:
            print(f"  Exporting via MoviePy @ {src_fps}fps (final, {LIBX264_BITRATE})...")
            write_kwargs = {
                "preset": "medium",
                "bitrate": LIBX264_BITRATE,
            }

        clip.write_videofile(
            str(output_path),
            fps=src_fps,
            codec="libx264",
            audio_codec="aac",
            logger="bar",
            temp_audiofile=temp_audiofile,
            **write_kwargs,
        )
        clip.close()
    else:
        # Tidak ada MoviePy work, copy file langsung untuk FFmpeg
        clip.close()
        import shutil
        shutil.copy2(str(input_path), str(output_path))

    # === PHASE 2: FFmpeg filter stages (satu pass) ===
    filter_stages = pipe.active_by_layer("ffmpeg_filter", features)
    if filter_stages:
        filter_strings = []
        active_names = []
        for stage in filter_stages:
            f = stage.ffmpeg_filter(features, ctx)
            if f:
                filter_strings.append(f)
                active_names.append(stage.name)

        if filter_strings:
            print(f"  [FFmpeg] {', '.join(active_names)} (satu pass)...")
            ffmpeg_post_process(output_path, filter_strings)
            if features.get("resize"):
                print(f"         Output: {TARGET_W}x{TARGET_H} (9:16, center-aligned)")

    # === PHASE 3: FFmpeg stream stages (scrub, ...) ===
    for stage in pipe.active_by_layer("ffmpeg_stream", features):
        if stage.name == "scrub":
            print("  Scrubbing metadata & injecting iPhone 13 EXIF...")
        else:
            print(f"  [Stream] {stage.name}...")
        stage.ffmpeg_stream(output_path, features, ctx)

    print(f"  DONE: {output_path.name}")


# ============================================================
# PIPELINE — IMAGE
# ============================================================

def process_image(input_path: Path, output_path: Path, features: dict):
    """Pipeline lengkap untuk satu gambar (JPG/PNG)."""
    print(f"\n{'='*60}")
    print(f"  Processing (image): {input_path.name}")
    print(f"{'='*60}")

    img = Image.open(input_path).convert("RGB")
    w, h = img.size
    aspect = detect_aspect(w, h)

    print(f"  Resolution : {w}x{h}")
    print(f"  Aspect     : {aspect}")

    step = 0
    active = []
    if features["crop"] != "none":
        active.append("crop")
    if features["mirror"]:
        active.append("mirror")
    if features["grain"]:
        active.append("grain")
    if features["color_jitter"]:
        active.append("color_jitter")
    if features["resize"]:
        active.append("resize")
    total = len(active)

    if total == 0:
        print("  Tidak ada fitur yang dipilih, skip.")
        return

    # Crop
    if features["crop"] != "none":
        step += 1
        mode = features["crop"]
        img = crop_image(img, mode)
        print(f"  [{step}/{total}] Crop ({mode}): {img.size[0]}x{img.size[1]}")

    # Mirror
    if features["mirror"]:
        step += 1
        img = mirror_image(img)
        print(f"  [{step}/{total}] Mirror: done")

    # Grain
    if features["grain"]:
        step += 1
        img = grain_image(img)
        print(f"  [{step}/{total}] Grain ({GRAIN_INTENSITY:.0%}): done")

    # Color jitter
    if features["color_jitter"]:
        step += 1
        img = color_jitter_image(img)
        print(f"  [{step}/{total}] Color jitter: done")

    # Fill & crop
    if features["resize"]:
        step += 1
        img = fill_and_crop_image(img)
        print(f"  [{step}/{total}] Fill & crop: {TARGET_W}x{TARGET_H} (center-aligned)")

    # Save tanpa metadata
    ext = output_path.suffix.lower()
    if ext == ".png":
        img.save(output_path)
    else:
        img.save(output_path, "JPEG", quality=95)

    print(f"  DONE: {output_path.name}")


# ============================================================
# MAIN
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Batch Video & Image Humanizer — hapus jejak AI secara otomatis.",
        epilog=(
            "Contoh:\n"
            "  python humanizer.py --all                  Jalankan semua fitur\n"
            "  python humanizer.py --mirror --grain       Hanya mirror & grain\n"
            "  python humanizer.py --crop --resize        Crop atas+bawah & resize\n"
            "  python humanizer.py --top-crop --mirror    Crop atas saja & mirror\n"
            "  python humanizer.py                        Mode interaktif (tanya y/n)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--all", action="store_true",
        help="Jalankan semua fitur tanpa tanya",
    )

    crop_group = parser.add_mutually_exclusive_group()
    crop_group.add_argument(
        "--crop", action="store_true",
        help="Crop 3.5%% atas + bawah",
    )
    crop_group.add_argument(
        "--top-crop", action="store_true",
        help="Crop 3.5%% bagian atas saja",
    )
    crop_group.add_argument(
        "--bottom-crop", action="store_true",
        help="Crop 3.5%% bagian bawah saja",
    )
    crop_group.add_argument(
        "--no-watermark", action="store_true",
        help="Lewati crop (eksplisit skip)",
    )

    parser.add_argument("--mirror", action="store_true", help="Flip horizontal")
    parser.add_argument("--grain", action="store_true", help="Tambah grain/noise 3%%")
    parser.add_argument("--jitter", action="store_true", help="Subtle jitter/zoom (video only)")
    parser.add_argument("--color-jitter", action="store_true", help="Random color jitter (brightness/contrast/saturation/gamma)")
    parser.add_argument("--resize", action="store_true", help=f"Fill & crop ke {TARGET_W}x{TARGET_H}")
    parser.add_argument("--scrub", action="store_true", help="Scrub metadata (video only)")
    parser.add_argument("--beat-zoom", action="store_true", help="Subtle zoom punch sync dengan beat lagu (retention boost, video only)")
    parser.add_argument("--random-crop", action="store_true", help="Beat step zoom: 1.0x <-> 1.15x ganti tiap 4 beats (video only)")
    parser.add_argument("--random-crop-anchor", choices=["top", "center", "bottom"], default="bottom",
                        help="Anchor crop untuk beat step zoom (default: bottom)")
    parser.add_argument("--gpu", action="store_true", help="Gunakan GPU encoder (Intel QSV / NVIDIA NVENC)")

    return parser.parse_args()


# Urutan prioritas: nvenc (NVIDIA, paling stabil) → vaapi (Intel/AMD Linux) → qsv (Windows/oneVPL)
GPU_ENCODER_CANDIDATES = [
    {
        "name": "h264_nvenc",
        "input_args": [],
        "filter_suffix": "",
        "output_args": ["-preset", "p4", "-b:v", NVENC_BITRATE],
    },
    {
        "name": "h264_vaapi",
        "input_args": ["-vaapi_device", "/dev/dri/renderD128"],
        "filter_suffix": ",format=nv12,hwupload",
        # Intel VA-API umumnya cuma support CQP rate control, bukan -b:v.
        # Grain noise bikin tiap frame unik (no motion redundancy), jadi QP rendah
        # bakal bikin file balloon ke ratusan MB. Tuning via VAAPI_QP.
        "output_args": ["-rc_mode", "CQP", "-qp", str(VAAPI_QP)],
    },
    {
        "name": "h264_qsv",
        "input_args": ["-init_hw_device", "qsv=hw", "-filter_hw_device", "hw"],
        "filter_suffix": ",hwupload=extra_hw_frames=64,format=qsv",
        "output_args": ["-preset", "fast", "-b:v", QSV_BITRATE],
    },
]


def _encoder_smoke_test(enc: dict) -> bool:
    """Coba encode 1 frame dummy untuk verifikasi encoder benar-benar jalan."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        *enc["input_args"],
        "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1",
        "-vf", f"null{enc['filter_suffix']}" if enc["filter_suffix"] else "null",
        "-c:v", enc["name"],
        *enc["output_args"],
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def detect_gpu_encoder() -> dict | None:
    """Deteksi GPU encoder yang benar-benar bisa dipakai (smoke-tested)."""
    listed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True,
    ).stdout

    for enc in GPU_ENCODER_CANDIDATES:
        if enc["name"] not in listed:
            continue
        if _encoder_smoke_test(enc):
            return enc
        print(f"  [INFO] {enc['name']} terdeteksi tapi gagal smoke-test, coba berikutnya...")
    return None


def enable_gpu():
    """Switch encoder ke GPU jika tersedia."""
    global ACTIVE_ENCODER
    detected = detect_gpu_encoder()
    if detected:
        ACTIVE_ENCODER = detected
        print(f"  GPU encoder aktif: {ACTIVE_ENCODER['name']}")
    else:
        print("  [WARN] Tidak ada GPU encoder yang berfungsi, fallback ke libx264 (CPU)")



def features_from_args(args) -> dict | None:
    """Buat dict features dari CLI args. Return None jika mode interaktif."""
    has_flag = any([
        args.all, args.crop, args.top_crop, args.bottom_crop,
        args.no_watermark, args.mirror, args.grain,
        args.jitter, args.color_jitter, args.resize, args.scrub,
        args.beat_zoom, args.random_crop,
    ])

    if not has_flag:
        return None  # mode interaktif

    if args.all:
        return {
            "crop": "both",
            "mirror": True,
            "grain": True,
            "jitter": True,
            "color_jitter": True,
            "resize": True,
            "scrub": True,
            "beat_zoom": True,
            "random_crop": True,
            "random_crop_anchor": args.random_crop_anchor,
        }

    # Tentukan crop mode
    if args.crop:
        crop = "both"
    elif args.top_crop:
        crop = "top"
    elif args.bottom_crop:
        crop = "bottom"
    else:
        crop = "none"

    return {
        "crop": crop,
        "mirror": args.mirror,
        "grain": args.grain,
        "jitter": args.jitter,
        "color_jitter": args.color_jitter,
        "resize": args.resize,
        "scrub": args.scrub,
        "beat_zoom": args.beat_zoom,
        "random_crop": args.random_crop,
        "random_crop_anchor": args.random_crop_anchor,
    }


def print_features(features: dict):
    """Tampilkan ringkasan fitur yang aktif."""
    labels = {
        "crop": f"Crop ({features['crop']})" if features["crop"] != "none" else None,
        "mirror": "Mirror" if features.get("mirror") else None,
        "grain": "Grain" if features.get("grain") else None,
        "jitter": "Jitter" if features.get("jitter") else None,
        "color_jitter": "Color jitter" if features.get("color_jitter") else None,
        "resize": f"Resize {TARGET_W}x{TARGET_H}" if features.get("resize") else None,
        "scrub": "Metadata scrub" if features.get("scrub") else None,
        "beat_zoom": "Beat zoom punch" if features.get("beat_zoom") else None,
        "random_crop": (
            f"Beat step zoom (anchor {features.get('random_crop_anchor', 'bottom')})"
            if features.get("random_crop") else None
        ),
    }
    active = [v for v in labels.values() if v]
    if active:
        print(f"Fitur aktif: {', '.join(active)}")
    else:
        print("Tidak ada fitur yang dipilih!")


def main():
    args = parse_args()

    if args.gpu:
        enable_gpu()

    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    files = sorted(
        f for f in INPUT_DIR.iterdir()
        if f.suffix.lower() in VIDEO_EXTS | IMAGE_EXTS
    )

    if not files:
        print("Tidak ada file video/gambar di folder input/")
        print("Format yang didukung: .mp4, .jpg, .jpeg, .png")
        print("Letakkan file kamu di folder input/ lalu jalankan ulang.")
        sys.exit(0)

    video_count = sum(1 for f in files if f.suffix.lower() in VIDEO_EXTS)
    image_count = sum(1 for f in files if f.suffix.lower() in IMAGE_EXTS)
    print(f"Ditemukan {len(files)} file ({video_count} video, {image_count} gambar)\n")

    # Tentukan fitur: dari args atau interaktif
    features = features_from_args(args)
    if features is None:
        features = interactive_setup(has_video=video_count > 0)

    # GPU dari interaktif
    if features.pop("gpu", False) and not args.gpu:
        enable_gpu()

    print_features(features)
    print()

    success = 0
    failed = []

    for i, file_path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}]", end="")
        try:
            ext = file_path.suffix.lower()
            output_path = OUTPUT_DIR / f"humanized_{file_path.name}"
            if ext in VIDEO_EXTS:
                process_video(file_path, output_path, features)
            else:
                process_image(file_path, output_path, features)
            success += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((file_path.name, str(e)))

    # Summary
    print(f"\n{'='*60}")
    print(f"  SELESAI")
    print(f"  Berhasil : {success}/{len(files)}")
    if failed:
        print(f"  Gagal    : {len(failed)}")
        for name, err in failed:
            print(f"    - {name}: {err}")
    print(f"  Output   : {OUTPUT_DIR.resolve()}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
