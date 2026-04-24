"""Gradio Web UI — TikTok Downloader + Batch Video & Image Humanizer."""

import shutil
import subprocess
import threading
from pathlib import Path

import gradio as gr

import humanizer as _hum

_dl_lock = threading.Lock()
_proc_lock = threading.Lock()

DOWNLOAD_DIR = Path("/tmp/humanizer_downloads")
WORK_DIR = Path("/tmp/humanizer_work")


def _reset_dir(path: Path):
    """Hapus dan buat ulang direktori — bersihkan file lama tiap run."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


# ============================================================
# SECTION 1 — TikTok Downloader
# ============================================================

def download_videos(urls_text, progress=gr.Progress()):
    urls = [u.strip() for u in urls_text.strip().splitlines() if u.strip()]
    if not urls:
        return None, "Masukkan minimal satu URL, satu per baris."

    with _dl_lock:
        _reset_dir(DOWNLOAD_DIR)
        downloaded = []
        logs = []

        for i, url in enumerate(urls):
            progress((i + 1, len(urls)), desc=f"[{i+1}/{len(urls)}] Downloading...")
            url_dir = DOWNLOAD_DIR / str(i)
            url_dir.mkdir()
            try:
                result = subprocess.run(
                    [
                        "yt-dlp",
                        "--no-playlist",
                        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                        "--merge-output-format", "mp4",
                        "-o", str(url_dir / "%(title).80s.%(ext)s"),
                        url,
                    ],
                    capture_output=True, text=True, timeout=120,
                )
                files = list(url_dir.glob("*.*"))
                if result.returncode != 0 or not files:
                    err = result.stderr.strip().splitlines()
                    logs.append(f"ERR [{i+1}] {url[:60]}: {err[-1] if err else 'unknown'}")
                    continue
                for f in files:
                    downloaded.append(str(f))
                logs.append(f"OK  [{i+1}] {files[0].name}")
            except subprocess.TimeoutExpired:
                logs.append(f"ERR [{i+1}] {url[:60]}: timeout (120s)")
            except Exception as e:
                logs.append(f"ERR [{i+1}] {url[:60]}: {e}")

    if not downloaded:
        return None, "Tidak ada video berhasil didownload.\n\n" + "\n".join(logs)

    return downloaded, "\n".join(logs)


# ============================================================
# SECTION 2 — Humanizer
# ============================================================

def run_humanizer(
    files,
    crop_mode,
    mirror,
    grain,
    jitter,
    color_jitter,
    resize,
    scrub,
    progress=gr.Progress(),
):
    if not files:
        return None, "Upload minimal satu file dulu."

    features = {
        "crop": crop_mode,
        "mirror": mirror,
        "grain": grain,
        "jitter": jitter,
        "color_jitter": color_jitter,
        "resize": resize,
        "scrub": scrub,
    }
    if not any(v and v != "none" for v in features.values()):
        return None, "Pilih minimal satu fitur sebelum proses."

    logs = []
    output_paths = []

    with _proc_lock:
        _reset_dir(WORK_DIR)
        _hum.OUTPUT_DIR = WORK_DIR

        for i, fpath in enumerate(files):
            src = Path(fpath)
            ext = src.suffix.lower()
            dst = WORK_DIR / f"humanized_{src.name}"
            progress((i + 1, len(files)), desc=f"[{i+1}/{len(files)}] {src.name}")
            try:
                if ext in _hum.VIDEO_EXTS:
                    _hum.process_video(src, dst, features)
                elif ext in _hum.IMAGE_EXTS:
                    _hum.process_image(src, dst, features)
                else:
                    logs.append(f"Skip {src.name} — format tidak didukung")
                    continue
                output_paths.append(dst)
                logs.append(f"OK  {src.name}")
            except Exception as e:
                logs.append(f"ERR {src.name}: {e}")

    if not output_paths:
        return None, "Tidak ada file berhasil diproses.\n\n" + "\n".join(logs)

    return [str(p) for p in output_paths], "\n".join(logs)


# ============================================================
# UI
# ============================================================

with gr.Blocks(title="Batch Video & Image Humanizer", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
        # Batch Video & Image Humanizer
        **Format yang didukung:** `.mp4` &nbsp;·&nbsp; `.jpg` &nbsp;·&nbsp; `.jpeg` &nbsp;·&nbsp; `.png`
        """
    )

    # ── Section 1: Downloader ──────────────────────────────
    gr.Markdown("## 1. Download Video Referensi")
    with gr.Row():
        with gr.Column(scale=3):
            urls_input = gr.Textbox(
                label="URL Video (satu URL per baris — support TikTok, YouTube, Instagram, dll)",
                placeholder="https://www.tiktok.com/@user/video/123\nhttps://www.youtube.com/watch?v=xxx",
                lines=4,
            )
            dl_btn = gr.Button("Download", variant="primary")
        with gr.Column(scale=2):
            dl_output = gr.Files(label="Hasil Download")
            dl_log = gr.Textbox(label="Log Download", lines=5, interactive=False)

    gr.Markdown(
        """
        ---
        > **Upload hasil download ke RunningHub** untuk generate video AI, lalu upload hasilnya ke bagian 2.
        ---
        """
    )

    # ── Section 2: Humanizer ──────────────────────────────
    gr.Markdown("## 2. Humanizer — Hapus Fingerprint AI")
    with gr.Row():
        with gr.Column(scale=3):
            files_input = gr.Files(
                label="Upload File Hasil AI (bisa banyak sekaligus)",
                file_count="multiple",
                file_types=[".mp4", ".jpg", ".jpeg", ".png"],
                type="filepath",
            )

            gr.Markdown("### Fitur Humanizer")
            crop_mode = gr.Radio(
                choices=[
                    ("Lewati crop", "none"),
                    ("Atas + Bawah", "both"),
                    ("Atas saja", "top"),
                    ("Bawah saja", "bottom"),
                ],
                value="both",
                label="Crop Watermark",
                info="Potong 3.5% tepi atas/bawah untuk hapus watermark AI",
            )
            with gr.Row():
                mirror = gr.Checkbox(label="Mirror — flip horizontal", value=True)
                grain = gr.Checkbox(label="Grain — noise 5%", value=True)
            with gr.Row():
                jitter = gr.Checkbox(label="Jitter — subtle zoom drift (video only)", value=True)
                color_jitter = gr.Checkbox(label="Color Jitter — brightness/contrast/saturation", value=True)
            with gr.Row():
                resize = gr.Checkbox(label="Resize ke 1080×1920 (fill & crop)", value=False)
                scrub = gr.Checkbox(label="Metadata Scrub — inject iPhone 13 (video only)", value=True)

            proc_btn = gr.Button("Proses", variant="primary", size="lg")

        with gr.Column(scale=2):
            output_files = gr.Files(label="Download Hasil (per file)")
            log_box = gr.Textbox(label="Log Proses", lines=14, interactive=False)

    # ── Event handlers ─────────────────────────────────────
    dl_btn.click(
        fn=download_videos,
        inputs=[urls_input],
        outputs=[dl_output, dl_log],
    )

    proc_btn.click(
        fn=run_humanizer,
        inputs=[files_input, crop_mode, mirror, grain, jitter, color_jitter, resize, scrub],
        outputs=[output_files, log_box],
    )


if __name__ == "__main__":
    import os
    is_hf = bool(os.getenv("SPACE_ID"))
    demo.launch(inbrowser=not is_hf)
