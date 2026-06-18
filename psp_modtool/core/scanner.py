"""Scan folder hasil extract untuk menemukan teks yang bisa diterjemahkan."""

import json
import datetime
from pathlib import Path

from ..utils import logger as log
from ..utils import text_detect as td
from ..utils.constants import BINARY_SKIP_EXTENSIONS


def scan_folder(folder, output_json, min_len: int = 5) -> bool:
    """
    Scan semua file game, deteksi string teks, dan tulis ke JSON
    dengan field 'translation' kosong untuk diisi pengguna.
    """
    log.header("SCAN TEKS")
    folder = Path(folder)
    output_json = Path(output_json)

    if not folder.exists():
        log.err(f"Folder tidak ditemukan: {folder}")
        return False

    game_files = [
        p for p in folder.rglob('*')
        if p.is_file() and not p.name.startswith('_')
    ]
    log.info(f"Total file ditemukan: {len(game_files)}")

    result = {
        'scan_date': datetime.datetime.now().isoformat(),
        'source_folder': str(folder.resolve()),
        'files': [],
    }

    log.step(1, "Menganalisis setiap file...")
    for path in sorted(game_files):
        ext = path.suffix.lower()
        if ext in BINARY_SKIP_EXTENSIONS:
            continue

        try:
            raw = path.read_bytes()
        except Exception as e:
            log.warn(f"Tidak bisa baca {path.name}: {e}")
            continue
        if not raw:
            continue

        rel = str(path.relative_to(folder))
        encoding = td.detect_encoding(raw)
        is_text = td.is_plain_text_file(ext)

        if is_text:
            strings = _scan_text_file(raw, encoding, min_len)
        else:
            strings = _scan_binary_file(raw, min_len)

        if strings:
            log.item(f"{rel}: {len(strings)} string")
            result['files'].append({
                'path': rel,
                'encoding': encoding,
                'type': 'text' if is_text else 'binary',
                'strings': strings,
            })

    total = sum(len(f['strings']) for f in result['files'])
    result['summary'] = {
        'total_files_with_text': len(result['files']),
        'total_strings': total,
    }
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    log.ok(f"\nHasil scan: {len(result['files'])} file, {total} string")
    log.ok(f"Tersimpan di: {output_json}")
    log.info("Isi field 'translation' di JSON, lalu jalankan 'apply'.")
    return True


def _scan_text_file(raw: bytes, encoding: str, min_len: int) -> list:
    """Scan file teks murni per-baris."""
    strings = []
    try:
        content = raw.decode(encoding, errors='replace')
    except Exception:
        return strings

    for i, line in enumerate(content.splitlines()):
        line = line.strip()
        if len(line) >= min_len and td.looks_like_game_text(line):
            strings.append({
                'offset': i,
                'type': 'line',
                'original': line,
                'translation': '',
            })
    return strings


def _scan_binary_file(raw: bytes, min_len: int) -> list:
    """Scan file biner untuk string ASCII."""
    strings = []
    for s in td.extract_ascii_strings(raw, min_len=min_len):
        if td.looks_like_game_text(s['text']):
            strings.append({
                'offset': s['offset'],
                'type': 'binary_string',
                'original': s['text'],
                'translation': '',
            })
    return strings
