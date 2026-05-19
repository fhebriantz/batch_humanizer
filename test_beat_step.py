"""Test beat_step_zoom dengan video yang punya banyak beats."""

import subprocess
import sys
import tempfile
import json
from pathlib import Path

import humanizer as _hum


def gen_beat_video(out: Path, duration=12, bpm=120):
    period = 60.0 / bpm
    audio_expr = f"sin(2*PI*880*t)*exp(-mod(t,{period})*30)"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=864x1536:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"aevalsrc=exprs='{audio_expr}':duration={duration}:sample_rate=44100",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def probe(p: Path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(p)],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        src = tmpdir / "in.mp4"
        dst = tmpdir / "out.mp4"
        print("Generating 12s @ 120 BPM (~24 beats expected, 6 groups of 4)...")
        gen_beat_video(src, 12, 120)
        _hum.OUTPUT_DIR = tmpdir

        # Test: beat_zoom + beat_step_zoom bareng
        features = {
            "crop": "none", "mirror": False, "grain": False, "jitter": False,
            "color_jitter": False, "resize": False, "scrub": False,
            "beat_zoom": True, "random_crop": True,
        }
        print(f"\n{'='*60}")
        print(f"  TEST: beat_zoom + beat_step_zoom")
        print(f"{'='*60}")
        try:
            _hum.process_video(src, dst, features)
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            return 1

        info = probe(dst)
        dur = float(info["format"]["duration"])
        print(f"\n  → duration {dur:.2f}s, size {dst.stat().st_size:,}")
        if abs(dur - 12.0) > 0.5:
            print(f"  ✗ duration drift {abs(dur-12.0):.2f}s")
            return 1
        print(f"  ✓ duration preserved")
        return 0


if __name__ == "__main__":
    sys.exit(main())
