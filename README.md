---
title: Batch Video Image Humanizer
emoji: 🎬
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
---

# Batch Video & Image Humanizer

Script Python untuk automasi editing batch video dan gambar hasil generate AI.
Menghapus jejak AI (watermark, metadata, tekstur mulus) secara otomatis.

## Fitur

- **Dynamic Crop** — potong 5% atas/bawah untuk hapus watermark (mode: both/top/bottom)
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
- **Google Sheets** — integrasi workflow dengan spreadsheet (default `Daily_Workflow`, override via env var `SPREADSHEET_NAME`)

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

### Standalone (tanpa Google Sheets)

```
python humanizer.py                     # Mode interaktif (tanya y/n per fitur)
python humanizer.py --all               # Semua fitur
python humanizer.py --all --gpu         # Semua fitur + GPU encoder
python humanizer.py --crop --mirror     # Pilih fitur tertentu
```

### Workflow + Google Sheets

```
python workflow.py                      # Mode interaktif
python workflow.py --all --gpu          # Semua fitur + GPU
```

Hasil ada di folder `output/`.

### Daftar Flag

| Flag | Keterangan |
|---|---|
| `--all` | Jalankan semua fitur tanpa tanya |
| `--crop` | Crop 5% atas + 5% bawah |
| `--top-crop` | Crop 5% atas saja |
| `--bottom-crop` | Crop 5% bawah saja |
| `--no-watermark` | Eksplisit skip crop |
| `--mirror` | Flip horizontal (FFmpeg) |
| `--grain` | Tambah grain/noise 5% (FFmpeg) |
| `--jitter` | Subtle jitter/zoom (video only, MoviePy) |
| `--color-jitter` | Random color jitter (FFmpeg) |
| `--resize` | Fill & crop ke 1080x1920 (FFmpeg) |
| `--scrub` | Hapus metadata & inject iPhone 13 (video only) |
| `--gpu` | Gunakan GPU encoder (auto-detect NVENC/VAAPI/QSV, smoke-test) |

Mode interaktif (tanpa flag) akan tanya y/n untuk setiap fitur.

## Workflow Google Sheets

### Persiapan

1. Letakkan `credential.json` (service account) di root folder project
2. Share spreadsheet (default `Daily_Workflow`) ke email service account
3. Kolom spreadsheet: A=No, B=Jam, C=Akun, D=File, E=-, F=Download, G=Humanize, J=Timestamp

**Pakai spreadsheet dengan nama lain?** Set env var sebelum jalankan script:
```
SPREADSHEET_NAME="Nama_Spreadsheet_Lain" python workflow.py
```

### Alur (Update Mode)

1. Baca folder `input/`, extract nama akun dari filename (misal `Akun_01.mp4` → `Akun_01`)
2. Cari baris di Sheets: Kolom C cocok DAN Kolom G masih FALSE (case insensitive)
3. Jika ketemu → proses humanize → update baris (D=filename, F=✓, G=✓, J=timestamp)
4. Jika tidak ketemu → append baris baru → proses → update
5. File yang sudah TRUE otomatis di-skip

Jika internet putus atau API limit, script tetap lanjut proses file berikutnya.

### Penamaan File Output

```
[NamaAkun]_[DDMMYYYY-HHMMSS].[ext]
Contoh: Akun_01_20042026-143025.mp4
```

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
├── humanizer.py        # Script humanizer (standalone)
├── workflow.py         # Script workflow + Google Sheets
├── credential.json     # Service account key (jangan commit!)
├── requirements.txt    # Dependencies
├── input/              # Taruh video/gambar mentah di sini
└── output/             # Hasil yang sudah diproses
```

## Konfigurasi

Edit variabel di bagian atas `humanizer.py`:

| Variabel | Default | Keterangan |
|---|---|---|
| `TARGET_W` | `1080` | Lebar output standar 9:16 |
| `TARGET_H` | `1920` | Tinggi output standar 9:16 |
| `CROP_PERCENT` | `0.05` | Persentase crop atas & bawah |
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
