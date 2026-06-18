"""Pipeline interaktif: jalankan seluruh alur extract -> repack."""

import shutil
from pathlib import Path

from .extractor import extract_iso
from .scanner import scan_folder
from .translator import apply_translations
from .repacker import repack_iso
from ..utils import logger as log
from ..utils.logger import C


def run_all(iso_path, work_folder) -> bool:
    """Jalankan full pipeline secara interaktif dengan jeda untuk editing."""
    log.header("PSP MOD TOOL - FULL PIPELINE")
    work = Path(work_folder)
    extract_dir = work / 'extracted'
    scan_json = work / 'strings.json'
    edited_json = work / 'strings_edited.json'
    output_iso = work / (Path(iso_path).stem + '_modded.iso')

    print(f"""
  ISO Input  : {iso_path}
  Work Folder: {work}
  Output ISO : {output_iso}
""")

    # 1. Extract
    log.step(1, "Extract ISO")
    if not _maybe_extract(iso_path, extract_dir):
        return False

    # 2. Scan
    log.step(2, "Scan teks")
    if not scan_folder(str(extract_dir), str(scan_json)):
        return False

    # 3. Edit (manual oleh pengguna)
    log.step(3, "Edit terjemahan")
    shutil.copy2(scan_json, edited_json)
    _print_edit_instructions(edited_json)
    input("  Tekan ENTER setelah selesai mengisi terjemahan...")

    # 4. Apply
    log.step(4, "Apply terjemahan")
    if not apply_translations(str(extract_dir), str(edited_json)):
        return False

    # 5. Repack
    log.step(5, "Repack ISO")
    if not repack_iso(str(extract_dir), str(output_iso)):
        return False

    _print_done(output_iso)
    return True


def _maybe_extract(iso_path, extract_dir: Path) -> bool:
    """Extract ISO, tanya dulu bila folder sudah ada."""
    if extract_dir.exists():
        ans = input(
            f"  Folder '{extract_dir}' sudah ada. Extract ulang? [y/N]: "
        ).strip().lower()
        if ans != 'y':
            log.info("Lewati extract, gunakan folder yang ada.")
            return True
        shutil.rmtree(extract_dir)
    return extract_iso(iso_path, str(extract_dir))


def _print_edit_instructions(edited_json: Path):
    print(f"""
  {C.YELLOW}File terjemahan disalin ke:{C.RESET}
    {edited_json}

  {C.BOLD}Cara mengisi:{C.RESET}
    1. Buka {C.CYAN}strings_edited.json{C.RESET} di text editor
    2. Cari field {C.CYAN}"translation": ""{C.RESET}
    3. Isi terjemahan bahasa Indonesia, lalu simpan

  Contoh:
    "original":    "Are you sure you want to exit?",
    "translation": "Apakah kamu yakin ingin keluar?",
""")


def _print_done(output_iso: Path):
    log.header("SELESAI!")
    print(f"""
  {C.GREEN}\u2713 Proses modding selesai!{C.RESET}

  File output: {C.CYAN}{output_iso}{C.RESET}

  {C.BOLD}Cara test:{C.RESET}
    1. Buka PPSSPP emulator
    2. Load: {output_iso.name}
    3. Verifikasi terjemahan

  {C.BOLD}Catatan:{C.RESET}
    \u2022 Backup (.bak) tersimpan di folder extracted/
    \u2022 String biner punya batas panjang (dipotong otomatis)
    \u2022 Game encoding Shift-JIS perlu hex editor manual
""")
