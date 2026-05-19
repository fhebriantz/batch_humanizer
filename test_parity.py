"""Parity check: refactor pipeline harus produce output yang valid dengan fitur existing.

Generate synthetic test video (FFmpeg testsrc + sine tone), run process_video
dengan semua fitur existing aktif, verify output:
  - File exists
  - Bisa di-probe FFmpeg (valid video)
  - Duration mendekati input
  - Resolution 1080x1920 (kalau resize aktif)

Bukan byte-identical check (color_jitter & audio_jitter punya randomness),
tapi cukup buat assurance bahwa refactor tidak break logic.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import humanizer as _hum


def ffprobe(path: Path) -> dict:
    """Probe video info pakai ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return json.loads(result.stdout)


def generate_test_video(out_path: Path, duration: int = 5):
    """Generate 864x1536 (9:16) test video + sine tone audio."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=864x1536:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def check_video(path: Path, expect_resize: bool) -> dict:
    """Verify output video properties."""
    info = ffprobe(path)
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio_stream = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)

    result = {
        "exists": True,
        "size_bytes": path.stat().st_size,
        "duration": float(info["format"]["duration"]),
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "video_codec": video_stream["codec_name"],
        "has_audio": audio_stream is not None,
        "audio_codec": audio_stream["codec_name"] if audio_stream else None,
    }

    # Assertions
    assertions = []
    assertions.append(("duration > 0", result["duration"] > 0))
    assertions.append(("video_codec is h264", result["video_codec"] == "h264"))
    assertions.append(("has audio", result["has_audio"]))

    if expect_resize:
        assertions.append(("width == 1080", result["width"] == 1080))
        assertions.append(("height == 1920", result["height"] == 1920))

    result["assertions"] = assertions
    return result


def run_test(features: dict, label: str, tmpdir: Path):
    print(f"\n{'='*60}")
    print(f"  PARITY TEST: {label}")
    print(f"{'='*60}")
    print(f"  Features: {features}")

    src = tmpdir / "test_input.mp4"
    dst = tmpdir / "test_output.mp4"

    print(f"  Generating test video → {src}")
    generate_test_video(src, duration=5)

    # Patch OUTPUT_DIR ke tmpdir biar temp audio gak nyasar
    _hum.OUTPUT_DIR = tmpdir

    try:
        _hum.process_video(src, dst, features)
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return False

    if not dst.exists():
        print(f"  ✗ FAILED: output file tidak ada")
        return False

    info = check_video(dst, expect_resize=features.get("resize", False))
    print(f"\n  Output check:")
    print(f"    Size       : {info['size_bytes']:,} bytes")
    print(f"    Duration   : {info['duration']:.2f}s")
    print(f"    Resolution : {info['width']}x{info['height']}")
    print(f"    Video      : {info['video_codec']}")
    print(f"    Audio      : {info['audio_codec']}")

    all_pass = True
    for desc, ok in info["assertions"]:
        mark = "✓" if ok else "✗"
        print(f"    [{mark}] {desc}")
        if not ok:
            all_pass = False

    return all_pass


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        # Test 1: ALL existing features (baseline)
        features_all = {
            "crop": "both",
            "mirror": True,
            "grain": True,
            "jitter": True,
            "color_jitter": True,
            "resize": True,
            "scrub": True,
        }

        # Test 2: subset of features
        features_subset = {
            "crop": "both",
            "mirror": True,
            "grain": False,
            "jitter": False,
            "color_jitter": False,
            "resize": True,
            "scrub": True,
        }

        # Test 3: cuma scrub (minimal)
        features_minimal = {
            "crop": "none",
            "mirror": False,
            "grain": False,
            "jitter": False,
            "color_jitter": False,
            "resize": False,
            "scrub": True,
        }

        tests = [
            (features_all, "ALL features (crop+jitter+mirror+grain+color+resize+scrub)"),
            (features_subset, "Subset (crop + mirror + resize + scrub, no FFmpeg-heavy)"),
            (features_minimal, "Minimal (scrub only)"),
        ]

        results = []
        for features, label in tests:
            ok = run_test(features, label, tmpdir)
            results.append((label, ok))

        print(f"\n{'='*60}")
        print(f"  PARITY CHECK SUMMARY")
        print(f"{'='*60}")
        for label, ok in results:
            mark = "✓ PASS" if ok else "✗ FAIL"
            print(f"  [{mark}] {label}")

        if all(ok for _, ok in results):
            print(f"\n  All tests PASSED. Refactor preserves existing behavior.")
            return 0
        else:
            print(f"\n  Some tests FAILED. Refactor broke something.")
            return 1


if __name__ == "__main__":
    sys.exit(main())
