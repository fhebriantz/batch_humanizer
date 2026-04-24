---
title: Batch Video Image Humanizer
emoji: 🎬
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
---

# Batch Video & Image Humanizer

Script Python untuk automasi editing batch video dan gambar hasil generate AI.
Menghapus jejak AI (watermark, metadata, tekstur mulus) secara otomatis.

Tersedia dalam dua mode: **CLI** (`humanizer.py`) dan **Web UI Gradio** (`app.py`, deploy-ready untuk Hugging Face Spaces).

## Fitur

- **Dynamic Crop** — potong 3.5% atas/bawah untuk hapus watermark (mode: both/top/bottom)
- **Fill & Crop** — scale proporsional & center-crop ke 1080x1920 (tanpa distorsi)
- **Grain/Noise** — FFmpeg noise filter 5%
- **Horizontal Mirror** — FFmpeg hflip
- **Subtle Jitter** — smooth drift zoom 1.01x (video only)
- **Color Jitter** — random brightness/contrast/saturation/gamma
- **Metadata Scrub** — hapus metadata, injeksi metadata iPhone 13 (video only)
- **Audio Jitter** — subtle volume shift + resample 44.1kHz untuk ganti audio fingerprint (video only, otomatis saat post-process FFmpeg aktif)
- **FPS Matching** — output mengikuti FPS source (30→30, 60→60) tanpa frame duplication/dropping
- **GPU Encoding** — auto-detect dengan smoke-test real (NVIDIA NVENC → Intel VAAPI → QSV)
- **Multi-Format** — `.mp4`, `.jpg`, `.jpeg`, `.png`

## Instalasi

### 1. Install Python 3.10+

Download dari https://www.python.org/downloads/ dan centang **"Add Python to PATH"**.

### 2. Install FFmpeg

**Windows (via winget):**
```
winget install Gyan.FFmpeg
```

**Linux:**
```
sudo apt install ffmpeg -y
```

### 3. Install Dependencies

```
pip install -r requirements.txt
```

## Cara Pakai

### CLI

```
python humanizer.py                     # Mode interaktif (tanya y/n per fitur)
python humanizer.py --all               # Semua fitur
python humanizer.py --all --gpu         # Semua fitur + GPU encoder
python humanizer.py --crop --mirror     # Pilih fitur tertentu
```

Hasil ada di folder `output/`.

### Web UI (Gradio)

```
python app.py
```

Buka URL yang muncul di terminal (default `http://127.0.0.1:7860`). Upload file, pilih fitur, klik Proses.

### Daftar Flag

| Flag | Keterangan |
|---|---|
| `--all` | Jalankan semua fitur tanpa tanya |
| `--crop` | Crop 3.5% atas + bawah |
| `--top-crop` | Crop 3.5% atas saja |
| `--bottom-crop` | Crop 3.5% bawah saja |
| `--no-watermark` | Eksplisit skip crop |
| `--mirror` | Flip horizontal (FFmpeg) |
| `--grain` | Tambah grain/noise 5% (FFmpeg) |
| `--jitter` | Subtle jitter/zoom (video only, MoviePy) |
| `--color-jitter` | Random color jitter (FFmpeg) |
| `--resize` | Fill & crop ke 1080x1920 (FFmpeg) |
| `--scrub` | Hapus metadata & inject iPhone 13 (video only) |
| `--gpu` | Gunakan GPU encoder (auto-detect NVENC/VAAPI/QSV, smoke-test) |

Mode interaktif (tanpa flag) akan tanya y/n untuk setiap fitur.

## Deploy ke Hugging Face Spaces

Repo ini sudah siap deploy ke HF Spaces. Cukup push ke remote HF:

```
git remote add hf https://huggingface.co/spaces/<username>/<space-name>
git push hf main
```

File yang relevan untuk HF Spaces:
- `app.py` — entry point Gradio
- `packages.txt` — install FFmpeg lewat apt
- `requirements.txt` — Python dependencies
- `README.md` — YAML frontmatter di atas wajib ada

## Arsitektur Processing

### Video Pipeline

```
Phase 1 — MoviePy (frame-by-frame, hanya yang harus):
  crop → jitter → export
  - Output intermediate CRF 18 (hampir lossless) kalau Phase 2 akan jalan
  - Output final bitrate 8Mbps kalau nggak ada FFmpeg step (hemat size)

Phase 2 — FFmpeg (satu pass, cepat):
  mirror + grain + color jitter + resize + audio jitter (resample + volume)

Phase 3 — FFmpeg (copy stream):
  metadata scrub
```

Phase 1 otomatis pilih mode intermediate vs final untuk hindari double encoding loss saat Phase 2 bakal jalan.

### Image Pipeline (PIL)

```
crop → mirror → grain → color jitter → fill & crop → save
```

## Struktur Folder

```
batch_humanizer/
├── humanizer.py        # CLI humanizer (core logic)
├── app.py              # Gradio web UI
├── packages.txt        # System deps untuk HF Spaces (ffmpeg)
├── requirements.txt    # Python dependencies
├── run.bat             # Windows launcher untuk CLI
├── input/              # Taruh video/gambar mentah di sini
└── output/             # Hasil yang sudah diproses
```

## Konfigurasi

Edit variabel di bagian atas `humanizer.py`:

| Variabel | Default | Keterangan |
|---|---|---|
| `TARGET_W` | `1080` | Lebar output standar 9:16 |
| `TARGET_H` | `1920` | Tinggi output standar 9:16 |
| `CROP_PERCENT` | `0.035` | Persentase crop atas & bawah |
| `GRAIN_INTENSITY` | `0.05` | Intensitas noise overlay |
| `JITTER_SCALE` | `1.01` | Skala zoom untuk jitter |
| `JITTER_INTERVAL` | `0.5` | Interval perubahan jitter (detik) |
| `LIBX264_BITRATE` | `"8000k"` | Bitrate final path CPU (libx264) |
| `VAAPI_QP` | `32` | Constant quantizer VA-API (lower = tajam & besar) |
| `NVENC_BITRATE` | `"8000k"` | Bitrate NVIDIA NVENC |
| `QSV_BITRATE` | `"8000k"` | Bitrate Intel QSV |
| `INTERMEDIATE_CRF` | `"18"` | Kualitas MoviePy intermediate (nearly lossless) |
| `FFMPEG_TIMEOUT` | `600` | Timeout FFmpeg dalam detik (cegah hang) |

FPS output otomatis mengikuti source — tidak ada konstanta.
