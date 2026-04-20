"""
Batch Humanizer + Google Sheets Workflow (Update Mode)
Cari baris yang belum diproses di Sheets → humanize → update baris tersebut.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from humanizer import (
    INPUT_DIR,
    OUTPUT_DIR,
    VIDEO_EXTS,
    IMAGE_EXTS,
    process_video,
    process_image,
    interactive_setup,
    parse_args,
    features_from_args,
    print_features,
    enable_gpu,
)


# ============================================================
# CONFIG
# ============================================================

CREDENTIAL_FILE = Path("credential.json")
# Nama spreadsheet bisa di-override via env var SPREADSHEET_NAME
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Daily_Workflow")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COL_AKUN = 3        # Kolom C — Nama Akun
COL_FILENAME = 4    # Kolom D — Nama File Baru
COL_DOWNLOAD = 6    # Kolom F — Status Download (checkbox)
COL_HUMANIZE = 7    # Kolom G — Status Humanize (checkbox)
COL_TIMESTAMP = 10  # Kolom J — Timestamp running


# ============================================================
# GOOGLE SHEETS
# ============================================================

def connect_sheets():
    """Autentikasi dan buka spreadsheet. Return worksheet atau None."""
    if not CREDENTIAL_FILE.exists():
        print(f"  [WARN] File {CREDENTIAL_FILE} tidak ditemukan!")
        print("  Workflow akan jalan TANPA logging ke Google Sheets.")
        return None

    try:
        creds = Credentials.from_service_account_file(
            str(CREDENTIAL_FILE), scopes=SCOPES,
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open(SPREADSHEET_NAME)
        worksheet = spreadsheet.sheet1
        print(f"  Google Sheets '{SPREADSHEET_NAME}' terhubung.")
        return worksheet
    except Exception as e:
        print(f"  [WARN] Gagal konek Google Sheets: {e}")
        print("  Workflow akan jalan TANPA logging ke Google Sheets.")
        return None


def get_all_rows(worksheet) -> list[dict]:
    """Baca semua baris dari Sheets, return list of dict per row.

    Setiap dict berisi: row_num, akun (col C), humanize (col G).
    """
    try:
        records = worksheet.get_all_values()
        rows = []
        for i, row in enumerate(records):
            if i == 0:
                continue  # skip header
            row_num = i + 1  # 1-indexed
            akun = row[COL_AKUN - 1].strip() if len(row) >= COL_AKUN else ""
            humanize_val = row[COL_HUMANIZE - 1].strip().upper() if len(row) >= COL_HUMANIZE else ""
            rows.append({
                "row_num": row_num,
                "akun": akun,
                "humanized": humanize_val == "TRUE",
            })
        return rows
    except Exception as e:
        print(f"  [WARN] Gagal baca data Sheets: {e}")
        return []


def get_next_number(rows: list[dict], worksheet) -> int:
    """Ambil nomor urut terakhir dari Kolom A, return +1."""
    try:
        col_a = worksheet.col_values(1)
        numbers = []
        for val in col_a:
            try:
                numbers.append(int(val))
            except ValueError:
                continue
        return max(numbers) + 1 if numbers else 1
    except Exception as e:
        print(f"  [WARN] Gagal baca nomor urut: {e}")
        return len(rows) + 2  # fallback: jumlah rows + header + 1


def find_pending_row(rows: list[dict], account_name: str) -> int | None:
    """Cari baris yang Kolom C cocok dengan account_name DAN Kolom G masih FALSE/kosong.

    Return row_num (1-indexed) atau None jika tidak ditemukan.
    """
    for row in rows:
        if row["akun"].lower() == account_name.lower() and not row["humanized"]:
            return row["row_num"]
    return None


def _center_cells(worksheet, row: int, col_start: int, col_end: int):
    """Set horizontal alignment center untuk range cell."""
    sheet_id = worksheet._properties["sheetId"]
    body = {
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": col_start - 1,
                        "endColumnIndex": col_end,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "horizontalAlignment": "CENTER",
                        }
                    },
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            }
        ]
    }
    worksheet.spreadsheet.batch_update(body)


def append_new_row(worksheet, sheet_rows: list[dict], account_name: str) -> int | None:
    """Append baris baru ke Sheets. Return row_num atau None jika gagal."""
    try:
        nomor = get_next_number(sheet_rows, worksheet)
        row_data = [
            nomor,          # A: Nomor Urut
            "",             # B: Jam Posting (kosong)
            account_name,   # C: Nama Akun
            "",             # D: Nama File (diisi nanti)
            "",             # E: (Kosong)
        ]
        worksheet.append_row(row_data, value_input_option="USER_ENTERED")
        all_rows = worksheet.col_values(1)
        row_num = len(all_rows)

        # Insert checkbox kosong di F dan G
        _set_checkbox(worksheet, row_num, COL_DOWNLOAD, False)
        _set_checkbox(worksheet, row_num, COL_HUMANIZE, False)

        # Center semua kolom A sampai J
        _center_cells(worksheet, row_num, 1, COL_TIMESTAMP)

        # Update local cache
        sheet_rows.append({
            "row_num": row_num,
            "akun": account_name,
            "humanized": False,
        })

        print(f"  [SHEETS] Baris baru {row_num} ditambahkan: No.{nomor} | {account_name}")
        return row_num
    except Exception as e:
        print(f"  [WARN] Gagal append ke Sheets: {e}")
        return None


def _set_checkbox(worksheet, row: int, col: int, checked: bool = False):
    """Insert checkbox (data validation) di cell tertentu via Sheets API."""
    sheet_id = worksheet._properties["sheetId"]
    body = {
        "requests": [
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": col - 1,
                        "endColumnIndex": col,
                    },
                    "rule": {
                        "condition": {"type": "BOOLEAN"},
                        "showCustomUi": True,
                    },
                }
            }
        ]
    }
    worksheet.spreadsheet.batch_update(body)
    worksheet.update_cell(row, col, checked)


def update_row_done(worksheet, row_num: int, new_filename: str):
    """Update Kolom D, centang Kolom G, dan tulis timestamp di Kolom J."""
    try:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        worksheet.update_cell(row_num, COL_FILENAME, new_filename)
        _set_checkbox(worksheet, row_num, COL_DOWNLOAD, True)
        _set_checkbox(worksheet, row_num, COL_HUMANIZE, True)
        worksheet.update_cell(row_num, COL_TIMESTAMP, timestamp)
        print(f"  [SHEETS] Baris {row_num} diupdate: D={new_filename}, F=✓, G=✓, J={timestamp}")
    except Exception as e:
        print(f"  [WARN] Gagal update Sheets baris {row_num}: {e}")


# ============================================================
# PENAMAAN
# ============================================================

def extract_account_name(filename: str) -> str:
    """Ambil nama akun dari nama file. Misal: Akun_01.mp4 → Akun_01."""
    return Path(filename).stem


def generate_new_filename(account_name: str, ext: str) -> str:
    """Buat nama file baru: [NamaAkun]_[DDMMYYYY-HHMMSS].[ext]."""
    now = datetime.now()
    timestamp = now.strftime("%d%m%Y-%H%M%S")
    return f"{account_name}_{timestamp}{ext}"


# ============================================================
# MAIN WORKFLOW
# ============================================================

def main():
    args = parse_args()

    if args.gpu:
        enable_gpu()

    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Cari semua file yang didukung
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

    # Tentukan fitur humanizer
    features = features_from_args(args)
    if features is None:
        features = interactive_setup(has_video=video_count > 0)

    # GPU dari interaktif
    if features.pop("gpu", False) and not args.gpu:
        enable_gpu()

    print_features(features)
    print()

    # Konek Google Sheets & baca semua baris sekali
    print("Menghubungkan ke Google Sheets...")
    worksheet = connect_sheets()
    print()

    sheet_rows = []
    if worksheet:
        sheet_rows = get_all_rows(worksheet)
        pending = sum(1 for r in sheet_rows if not r["humanized"])
        print(f"  Sheets: {len(sheet_rows)} baris data, {pending} belum diproses\n")

    success = 0
    failed = []

    for i, file_path in enumerate(files):
        ext = file_path.suffix.lower()
        account_name = extract_account_name(file_path.name)
        is_video = ext in VIDEO_EXTS
        tipe = "video" if is_video else "image"

        print(f"\n[{i + 1}/{len(files)}] {file_path.name}")

        # Cari baris pending di Sheets, atau append baru
        row_num = None
        if worksheet:
            row_num = find_pending_row(sheet_rows, account_name)
            if row_num is None:
                print(f"  Tidak ada baris pending untuk '{account_name}', append baris baru...")
                row_num = append_new_row(worksheet, sheet_rows, account_name)

        print(f"  Tipe       : {tipe}")
        print(f"  Akun       : {account_name}")
        if row_num:
            print(f"  Sheets row : {row_num}")

        new_filename = generate_new_filename(account_name, ext)
        output_path = OUTPUT_DIR / new_filename
        print(f"  File baru  : {new_filename}")

        # Proses humanize
        try:
            if is_video:
                process_video(file_path, output_path, features)
            else:
                process_image(file_path, output_path, features)
            success += 1

            # Update Sheets setelah berhasil
            if worksheet and row_num:
                update_row_done(worksheet, row_num, new_filename)
                # Tandai di local cache supaya tidak ke-pick lagi
                for r in sheet_rows:
                    if r["row_num"] == row_num:
                        r["humanized"] = True
                        break

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
    if worksheet:
        print(f"  Sheets   : {SPREADSHEET_NAME} (terupdate)")
    else:
        print(f"  Sheets   : TIDAK TERHUBUNG")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
