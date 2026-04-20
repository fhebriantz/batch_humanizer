# Batch Video & Image Humanizer

Script Python untuk automasi editing batch video dan gambar AI influencer.
Menghapus jejak AI (watermark, metadata, tekstur mulus) secara otomatis.

## Fitur

- **Dynamic Crop** — potong 5% atas/bawah untuk hapus watermark (mode: both/top/bottom)
- **Fill & Crop** — scale proporsional & center-crop ke 1080x1920 (tanpa distorsi)
- **Grain/Noise** — FFmpeg noise filter 5%
- **Horizontal Mirror** — FFmpeg hflip
- **Subtle Jitter** — smooth drift zoom 1.01x (video only)
- **Color Jitter** — random brightness/contrast/saturation/gamma
- **Metadata Scrub** — hapus metadata, injeksi metadata iPhone 13 (video only)
- **GPU Encoding** — auto-detect Intel QSV / NVIDIA NVENC / VAAPI
- **Multi-Format** — `.mp4`, `.jpg`, `.jpeg`, `.png`
- **Google Sheets** — integrasi workflow dengan spreadsheet `Daily_Workflow`

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
| `--gpu` | Gunakan GPU encoder (auto-detect QSV/NVENC/VAAPI) |

Mode interaktif (tanpa flag) akan tanya y/n untuk setiap fitur.

## Workflow Google Sheets

### Persiapan

1. Letakkan `credential.json` (service account) di root folder project
2. Share spreadsheet `Daily_Workflow` ke email service account
3. Kolom spreadsheet: A=No, B=Jam, C=Akun, D=File, E=-, F=Download, G=Humanize, J=Timestamp

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

Phase 2 — FFmpeg (satu pass, cepat):
  mirror + grain + color jitter + resize

Phase 3 — FFmpeg (copy stream):
  metadata scrub
```

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
| `OUTPUT_FPS` | `60` | FPS output video |
