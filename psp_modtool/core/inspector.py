"""
Cek kelayakan ISO PSP untuk diterjemahkan tanpa extract penuh.

Mengukur seberapa banyak teks ASCII "asli" (kata Inggris, frasa
multi-kata) terdapat dalam tiap file. ISO dengan teks ter-encode
custom (mis. tile font, Shift-JIS, kompresi) akan mendapat skor
rendah meski ukurannya besar.
"""

import re
from pathlib import Path

from . import iso9660
from ..utils import logger as log
from ..utils import text_detect as td
from ..utils.constants import SECTOR_SIZE, BINARY_SKIP_EXTENSIONS

# Kata Inggris umum yang sering muncul di teks UI/dialog game.
# Cek whole-word case-insensitive sebagai indikator teks asli.
_COMMON_WORDS = [
    'the', 'you', 'your', 'and', 'for', 'are', 'was', 'this', 'that',
    'with', 'have', 'has', 'will', 'not', 'but', 'can', 'from',
    'save', 'load', 'game', 'start', 'press', 'new', 'continue',
    'exit', 'options', 'item', 'menu', 'level', 'attack', 'magic',
    'player', 'enemy', 'defeat', 'victory', 'use',
]
_COMMON_RE = re.compile(
    r'\b(?:' + '|'.join(_COMMON_WORDS) + r')\b',
    re.IGNORECASE,
)
_ASCII_RUN = re.compile(rb'[\x20-\x7E]{5,}')

# Ukuran membaca file besar — batasi sampling jika > threshold ini.
_MAX_READ = 64 * 1024 * 1024  # 64 MB per file


def inspect_iso(iso_path) -> bool:
    """Cetak laporan kelayakan ISO untuk diterjemahkan."""
    log.header("INFO / KELAYAKAN ISO")
    iso_path = Path(iso_path)

    if not iso_path.exists():
        log.err(f"File tidak ditemukan: {iso_path}")
        return False

    with open(iso_path, 'rb') as f:
        try:
            pvd = iso9660.parse_pvd(f)
        except ValueError as e:
            log.err(str(e))
            return False

        log.ok(f"Volume     : {pvd['volume_name']}")
        log.ok(f"Ukuran ISO : {iso_path.stat().st_size:,} bytes")

        log.step(1, "Memindai direktori...")
        entries = iso9660.parse_directory(
            f, pvd['root_dir_lba'], pvd['root_dir_size'], ''
        )
        log.info(f"Ditemukan {len(entries)} file")

        log.step(2, "Sampling teks ASCII per file...")
        rows = []
        for e in entries:
            ext = Path(e['path']).suffix.lower()
            if ext in BINARY_SKIP_EXTENSIONS:
                continue
            data = _read_file(f, e['lba'], e['size'])
            rows.append(_analyze(e['path'], e['size'], data))

    _print_report(rows)
    return True


def _read_file(f, lba: int, size: int) -> bytes:
    """Baca isi file dari ISO; batasi ke _MAX_READ untuk file raksasa."""
    f.seek(lba * SECTOR_SIZE)
    return f.read(min(size, _MAX_READ))


def _analyze(path: str, size: int, data: bytes) -> dict:
    """Hitung metrik kelayakan teks satu file."""
    runs = _ASCII_RUN.findall(data)
    total_runs = len(runs)

    wordlike = 0
    word_hits = 0
    long_phrases = 0  # string dengan ≥2 kata Inggris umum

    for raw in runs:
        try:
            text = raw.decode('ascii')
        except UnicodeDecodeError:
            continue
        if td.looks_like_game_text(text):
            wordlike += 1
        hits = len(_COMMON_RE.findall(text))
        if hits:
            word_hits += hits
            if hits >= 2:
                long_phrases += 1

    return {
        'path': path,
        'size': size,
        'sampled': len(data) < size,
        'runs': total_runs,
        'wordlike': wordlike,
        'word_hits': word_hits,
        'phrases': long_phrases,
    }


def _verdict(total_hits: int, total_phrases: int) -> tuple[str, str]:
    """Tentukan verdict berdasarkan total kata umum & frasa multi-kata."""
    if total_hits >= 500 and total_phrases >= 50:
        return ("LAYAK", "Banyak teks Inggris polos terdeteksi — kemungkinan "
                "besar bisa diterjemahkan dengan scan + apply.")
    if total_hits >= 50:
        return ("PARSIAL", "Hanya sebagian string sistem/UI yang ASCII. "
                "Dialog gameplay kemungkinan ter-encode custom — "
                "ekspektasikan jangkauan terjemahan terbatas.")
    return ("TIDAK LAYAK", "Hampir tidak ada kata Inggris polos. Teks game "
            "kemungkinan tersimpan dalam format proprietary (tile font, "
            "Shift-JIS, atau terkompresi). Tool ini tidak cukup — perlu "
            "reverse-engineering format spesifik game.")


def _print_report(rows: list):
    log.step(3, "Laporan per file")
    print(f"\n  {'File':<40} {'Size':>12} {'Runs':>8} {'Wordlike':>9} "
          f"{'Words':>7} {'Phrases':>8}")
    print(f"  {'-'*40} {'-'*12} {'-'*8} {'-'*9} {'-'*7} {'-'*8}")

    rows.sort(key=lambda r: r['word_hits'], reverse=True)
    total_hits = total_phrases = total_wordlike = 0
    truncated = False
    for r in rows:
        mark = '*' if r['sampled'] else ' '
        label = (r['path'] + mark)[:40]
        print(f"  {label:<40} {r['size']:>12,} {r['runs']:>8,} "
              f"{r['wordlike']:>9,} {r['word_hits']:>7,} {r['phrases']:>8,}")
        total_hits += r['word_hits']
        total_phrases += r['phrases']
        total_wordlike += r['wordlike']
        truncated = truncated or r['sampled']

    if truncated:
        print(f"\n  * file > {_MAX_READ // (1024*1024)} MB — hanya bagian "
              "awal yang di-sampling")

    print()
    log.info(f"Total wordlike strings : {total_wordlike:,}")
    log.info(f"Total common-word hits : {total_hits:,}")
    log.info(f"Total multi-word phrases: {total_phrases:,}")

    label, explain = _verdict(total_hits, total_phrases)
    print()
    if label == "LAYAK":
        log.ok(f"VERDICT: {label}")
    elif label == "PARSIAL":
        log.warn(f"VERDICT: {label}")
    else:
        log.err(f"VERDICT: {label}")
    print(f"  {explain}")
