"""Gradio Web UI — Batch Video & Image Humanizer."""

import shutil
import threading
import zipfile
from pathlib import Path

import gradio as gr

import humanizer as _hum

_lock = threading.Lock()
WORK_DIR = Path("/tmp/humanizer_work")


def _reset_work_dir():
    """Hapus dan buat ulang WORK_DIR agar bersih setiap run."""
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True)


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

    with _lock:
        _reset_work_dir()
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

    if len(output_paths) > 1:
        zip_path = WORK_DIR / "humanized_batch.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in output_paths:
                zf.write(p, p.name)
        return str(zip_path), "\n".join(logs)

    return str(output_paths[0]), "\n".join(logs)


with gr.Blocks(title="Batch Video & Image Humanizer", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
        # Batch Video & Image Humanizer
        Upload video/gambar hasil generate AI, pilih fitur, lalu klik **Proses**.
        Jika upload banyak file sekaligus, hasil didownload sebagai ZIP.

        **Format yang didukung:** `.mp4` &nbsp;·&nbsp; `.jpg` &nbsp;·&nbsp; `.jpeg` &nbsp;·&nbsp; `.png`
        """
    )

    with gr.Row():
        with gr.Column(scale=3):
            files_input = gr.Files(
                label="Upload File (bisa banyak sekaligus)",
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

            btn = gr.Button("Proses", variant="primary", size="lg")

        with gr.Column(scale=2):
            output_file = gr.File(label="Download Hasil")
            log_box = gr.Textbox(label="Log Proses", lines=14, interactive=False)

    btn.click(
        fn=run_humanizer,
        inputs=[files_input, crop_mode, mirror, grain, jitter, color_jitter, resize, scrub],
        outputs=[output_file, log_box],
    )


if __name__ == "__main__":
    demo.launch()
