"""Terapkan terjemahan dari JSON ke file game yang sudah diekstrak."""

import json
import shutil
from pathlib import Path

from ..utils import logger as log


def apply_translations(folder, json_path) -> bool:
    """
    Baca JSON terjemahan dan patch file game.
    File teks: replace string. File biner: patch byte pada offset.
    Membuat backup .bak sebelum mengubah file.
    """
    log.header("APPLY TERJEMAHAN")
    folder = Path(folder)
    json_path = Path(json_path)

    if not json_path.exists():
        log.err(f"File JSON tidak ditemukan: {json_path}")
        return False

    data = json.loads(json_path.read_text(encoding='utf-8'))
    files = data.get('files', [])
    log.info(f"Memproses {len(files)} file...")

    applied = skipped = 0
    for entry in files:
        rel = entry['path']
        path = folder / rel
        if not path.exists():
            log.warn(f"File tidak ada: {rel}")
            continue

        to_apply = [
            (s['offset'], s['original'], s['translation'])
            for s in entry['strings']
            if s.get('translation', '').strip()
        ]
        if not to_apply:
            continue

        _backup(path)

        if entry.get('type') == 'text':
            a, s = _apply_text(path, entry.get('encoding', 'utf-8'), to_apply)
        else:
            a, s = _apply_binary(path, to_apply)

        applied += a
        skipped += s
        log.ok(f"{rel}: {a} diterapkan, {s} dilewati")

    log.ok(f"\nSelesai! Total {applied} diterapkan, {skipped} dilewati")
    return True


def _backup(path: Path):
    """Buat backup .bak sekali saja (tidak menimpa backup lama)."""
    bak = path.with_suffix(path.suffix + '.bak')
    if not bak.exists():
        shutil.copy2(path, bak)


def _apply_text(path: Path, encoding: str, to_apply: list):
    """Terapkan replace pada file teks. Return (applied, skipped)."""
    applied = skipped = 0
    try:
        content = path.read_bytes().decode(encoding, errors='replace')
    except Exception as e:
        log.err(f"Gagal baca {path.name}: {e}")
        return 0, len(to_apply)

    for _, original, translation in to_apply:
        if original in content:
            content = content.replace(original, translation, 1)
            applied += 1
        else:
            skipped += 1

    path.write_bytes(content.encode(encoding, errors='replace'))
    return applied, skipped


def _apply_binary(path: Path, to_apply: list):
    """
    Patch byte pada file biner di offset tertentu.
    Terjemahan dipotong/di-pad agar panjang byte tetap sama dengan aslinya.
    Return (applied, skipped).
    """
    applied = skipped = 0
    raw = bytearray(path.read_bytes())

    for offset, original, translation in to_apply:
        orig = original.encode('ascii', errors='replace')
        trans = translation.encode('ascii', errors='replace')
        end = offset + len(orig)

        if len(trans) <= len(orig):
            raw[offset:end] = trans.ljust(len(orig), b'\x00')
        else:
            raw[offset:end] = trans[:len(orig)]
            log.warn(f"  Offset {offset}: terjemahan dipotong (terlalu panjang)")
        applied += 1

    path.write_bytes(bytes(raw))
    return applied, skipped
