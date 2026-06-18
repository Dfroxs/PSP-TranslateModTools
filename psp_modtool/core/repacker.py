"""Repack folder hasil modding menjadi file ISO PSP."""

import json
from pathlib import Path

from . import iso9660
from ..utils import logger as log
from ..utils.constants import (
    SECTOR_SIZE, SYSTEM_AREA_SIZE,
    ROOT_DIR_SECTOR, FIRST_FILE_SECTOR,
)


def repack_iso(folder, output_iso) -> bool:
    """
    Bangun ISO 9660 baru dari folder hasil extract+modding.
    Kompatibel dengan emulator PPSSPP.
    """
    log.header("REPACK ISO")
    folder = Path(folder)
    output_iso = Path(output_iso)

    if not folder.exists():
        log.err(f"Folder tidak ditemukan: {folder}")
        return False

    volume_name = _read_volume_name(folder)
    files = _collect_files(folder)
    log.info(f"Total file untuk repack: {len(files)}")
    if not files:
        log.err("Tidak ada file untuk dipack.")
        return False

    log.step(1, "Menghitung layout ISO...")
    layout, total_sectors = _compute_layout(files)

    mb = total_sectors * SECTOR_SIZE / 1024 / 1024
    log.step(2, f"Menulis ISO ({total_sectors} sektor = {mb:.1f} MB)...")
    _write_iso(output_iso, folder, volume_name, layout, total_sectors)

    size = output_iso.stat().st_size
    log.ok(f"\nISO dibuat: {output_iso}")
    log.ok(f"Ukuran: {size:,} bytes ({size / 1024 / 1024:.2f} MB)")
    log.info("Test dengan PPSSPP emulator!")
    return True


def _read_volume_name(folder: Path) -> str:
    """Ambil volume name dari _meta.json, fallback ke 'PSPGAME'."""
    meta_path = folder / '_meta.json'
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        name = meta.get('volume_name', 'PSPGAME')
        log.info(f"Game: {name}")
        return name
    return 'PSPGAME'


def _collect_files(folder: Path) -> list:
    """Kumpulkan semua file game (skip file internal & backup)."""
    return [
        p for p in sorted(folder.rglob('*'))
        if p.is_file()
        and not p.name.startswith('_')
        and p.suffix != '.bak'
    ]


def _compute_layout(files: list):
    """
    Hitung LBA untuk tiap file.
    Return (list entry {abspath, name, lba, size}, total_sectors).
    """
    layout = []
    lba = FIRST_FILE_SECTOR
    for path in files:
        size = path.stat().st_size
        sectors = max((size + SECTOR_SIZE - 1) // SECTOR_SIZE, 1)
        layout.append({
            'abspath': path,
            'name': path.name,
            'lba': lba,
            'size': size,
        })
        lba += sectors
    return layout, lba + 1


def _write_iso(output_iso: Path, folder: Path, volume_name: str,
               layout: list, total_sectors: int):
    """Tulis byte ISO lengkap ke file."""
    with open(output_iso, 'wb') as out:
        _write_system_area(out, folder)
        out.write(iso9660.build_pvd(
            volume_name, total_sectors, ROOT_DIR_SECTOR, SECTOR_SIZE
        ))
        out.write(iso9660.build_vdst())
        out.write(_build_root_directory(layout))
        _write_file_data(out, layout)


def _write_system_area(out, folder: Path):
    """Tulis system area (16 sektor pertama)."""
    sa_path = folder / '_system_area.bin'
    if sa_path.exists():
        sa = sa_path.read_bytes()[:SYSTEM_AREA_SIZE]
        out.write(sa.ljust(SYSTEM_AREA_SIZE, b'\x00'))
    else:
        out.write(b'\x00' * SYSTEM_AREA_SIZE)


def _build_root_directory(layout: list) -> bytes:
    """Bangun sektor root directory dengan entry '.' '..' dan semua file."""
    buf = bytearray(SECTOR_SIZE)
    off = 0

    # Entry "." dan ".."
    off += iso9660.write_dir_record(
        buf, off, ROOT_DIR_SECTOR, SECTOR_SIZE, is_dir=True, name=b'\x00')
    off += iso9660.write_dir_record(
        buf, off, ROOT_DIR_SECTOR, SECTOR_SIZE, is_dir=True, name=b'\x01')

    # Entry tiap file
    for fe in layout:
        name = fe['name'].upper().encode('ascii', errors='replace') + b';1'
        written = iso9660.write_dir_record(
            buf, off, fe['lba'], fe['size'], is_dir=False, name=name)
        if written == 0:
            log.warn("Root directory penuh (1 sektor); sebagian file dilewati.")
            break
        off += written

    return bytes(buf)


def _write_file_data(out, layout: list):
    """Tulis data tiap file pada posisi LBA-nya (dengan padding)."""
    for fe in layout:
        target = fe['lba'] * SECTOR_SIZE
        if out.tell() < target:
            out.write(b'\x00' * (target - out.tell()))

        data = fe['abspath'].read_bytes()
        sectors = (len(data) + SECTOR_SIZE - 1) // SECTOR_SIZE
        out.write(data.ljust(sectors * SECTOR_SIZE, b'\x00'))
        log.item(f"{fe['name']} ({fe['size']:,} bytes)")
