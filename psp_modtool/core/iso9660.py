"""
Helper low-level format ISO 9660.

Berisi fungsi parsing & penulisan struktur dasar ISO yang dipakai
bersama oleh modul extractor dan repacker.
"""

import struct

from ..utils.constants import (
    SECTOR_SIZE, PVD_SECTOR, ISO_MAGIC,
)


def read_sector(f, lba: int) -> bytes:
    """Baca satu sektor (2048 byte) pada LBA tertentu."""
    f.seek(lba * SECTOR_SIZE)
    return f.read(SECTOR_SIZE)


def parse_pvd(f) -> dict:
    """Parse Primary Volume Descriptor. Raise ValueError jika ISO tidak valid."""
    pvd = read_sector(f, PVD_SECTOR)
    if pvd[1:6] != ISO_MAGIC:
        raise ValueError("Bukan ISO valid (magic 'CD001' tidak ditemukan)")

    return {
        'volume_name': pvd[40:72].decode('ascii', errors='replace').strip(),
        'root_dir_lba': struct.unpack_from('<I', pvd, 158)[0],
        'root_dir_size': struct.unpack_from('<I', pvd, 166)[0],
    }


def parse_directory(f, lba: int, size: int, base_path: str) -> list:
    """
    Parse direktori ISO secara rekursif.
    Mengembalikan list dict file: {path, lba, size}.
    """
    entries = []
    sectors = (size + SECTOR_SIZE - 1) // SECTOR_SIZE

    data = b''
    for i in range(sectors):
        f.seek((lba + i) * SECTOR_SIZE)
        data += f.read(SECTOR_SIZE)

    offset = 0
    while offset < len(data):
        rec_len = data[offset]
        if rec_len == 0:
            # Pindah ke awal sektor berikutnya
            offset = ((offset // SECTOR_SIZE) + 1) * SECTOR_SIZE
            if offset >= len(data):
                break
            continue

        entry_lba = struct.unpack_from('<I', data, offset + 2)[0]
        entry_size = struct.unpack_from('<I', data, offset + 10)[0]
        flags = data[offset + 25]
        name_len = data[offset + 32]
        raw_name = data[offset + 33: offset + 33 + name_len]

        try:
            name = raw_name.decode('ascii', errors='replace').split(';')[0]
        except Exception:
            name = raw_name.hex()

        is_dir = bool(flags & 0x02)

        if name not in ('', '\x00', '\x01'):
            full_path = f"{base_path}/{name}" if base_path else name
            if is_dir:
                entries.extend(
                    parse_directory(f, entry_lba, entry_size, full_path)
                )
            else:
                entries.append({
                    'path': full_path,
                    'lba': entry_lba,
                    'size': entry_size,
                })

        offset += rec_len

    return entries


def write_dir_record(buf: bytearray, offset: int, lba: int, size: int,
                     is_dir: bool, name: bytes) -> int:
    """
    Tulis satu directory record ISO 9660 ke buffer pada offset tertentu.
    Mengembalikan panjang record (sudah di-pad ke kelipatan 2).
    """
    name_len = len(name)
    rec_len = 33 + name_len
    if rec_len % 2 == 1:
        rec_len += 1

    if offset + rec_len > len(buf):
        return 0

    buf[offset] = rec_len
    buf[offset + 1] = 0                                  # Extended attr length
    struct.pack_into('<I', buf, offset + 2, lba)        # LBA (LE)
    struct.pack_into('>I', buf, offset + 6, lba)        # LBA (BE)
    struct.pack_into('<I', buf, offset + 10, size)      # Size (LE)
    struct.pack_into('>I', buf, offset + 14, size)      # Size (BE)
    buf[offset + 25] = 0x02 if is_dir else 0x00         # Flags
    struct.pack_into('<H', buf, offset + 28, 1)         # Volume seq (LE)
    struct.pack_into('>H', buf, offset + 30, 1)         # Volume seq (BE)
    buf[offset + 32] = name_len
    buf[offset + 33: offset + 33 + name_len] = name

    return rec_len


def build_pvd(volume_name: str, total_sectors: int,
              root_lba: int, root_size: int) -> bytes:
    """Bangun Primary Volume Descriptor lengkap (1 sektor)."""
    pvd = bytearray(SECTOR_SIZE)
    pvd[0] = 0x01
    pvd[1:6] = ISO_MAGIC
    pvd[6] = 0x01
    pvd[8:40] = b' ' * 32
    pvd[40:72] = volume_name.encode('ascii', errors='replace')[:32].ljust(32)

    struct.pack_into('<I', pvd, 80, total_sectors)
    struct.pack_into('>I', pvd, 84, total_sectors)
    struct.pack_into('<H', pvd, 120, 1)
    struct.pack_into('<H', pvd, 122, 1)
    struct.pack_into('<H', pvd, 128, SECTOR_SIZE)
    struct.pack_into('>H', pvd, 130, SECTOR_SIZE)

    write_dir_record(pvd, 156, root_lba, root_size, is_dir=True, name=b'\x00')
    return bytes(pvd)


def build_vdst() -> bytes:
    """Bangun Volume Descriptor Set Terminator (1 sektor)."""
    vdst = bytearray(SECTOR_SIZE)
    vdst[0] = 0xFF
    vdst[1:6] = ISO_MAGIC
    vdst[6] = 0x01
    return bytes(vdst)
