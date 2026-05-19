"""Test beat_zoom & random_crop: verify keduanya bisa apply tanpa break sync."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import humanizer as _hum


def gen_video(out: Path, duration: int = 8):
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=864x1536:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def probe(p: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(p)],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout)


def run(features: dict, label: str, tmpdir: Path) -> bool:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  features: {features}")
    src = tmpdir / "in.mp4"
    dst = tmpdir / "out.mp4"
    gen_video(src, 8)
    _hum.OUTPUT_DIR = tmpdir

    try:
        _hum.process_video(src, dst, features)
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return False

    info = probe(dst)
    dur = float(info["format"]["duration"])
    print(f"  → duration {dur:.2f}s, size {dst.stat().st_size:,} bytes")
    if abs(dur - 8.0) > 0.5:
        print(f"  ✗ duration drift {abs(dur-8.0):.2f}s")
        return False
    print(f"  ✓ duration preserved")
    return True


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        base = dict(crop="none", mirror=False, grain=False, jitter=False,
                    color_jitter=False, resize=False, scrub=False,
                    beat_zoom=False, random_crop=False)

        results = []

        # Test beat_zoom only
        f = {**base, "beat_zoom": True}
        results.append(("beat_zoom only", run(f, "TEST: beat_zoom only", tmpdir)))

        # Test random crop only
        f = {**base, "random_crop": True}
        results.append(("random_crop only", run(f, "TEST: random_crop only", tmpdir)))

        # Test combined: existing + new enhancements
        f = {**base, "crop": "both", "jitter": True, "mirror": True,
             "color_jitter": True, "beat_zoom": True, "random_crop": True}
        results.append(("ALL enhancements combined", run(f, "TEST: ALL combined", tmpdir)))

        print(f"\n{'='*60}")
        print(f"  SUMMARY")
        print(f"{'='*60}")
        for label, ok in results:
            print(f"  [{'✓ PASS' if ok else '✗ FAIL'}] {label}")

        return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
