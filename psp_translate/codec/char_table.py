"""Build & maintain character table FFT WoTL PSP.

Mapping: glyph index (1 byte) -> karakter Unicode yang dia render.

Format JSON:
    {
      "format": "fft-wotl-psp-v1",
      "font": "FONT.BIN",
      "glyph_size": [10, 14],
      "bpp": 2,
      "bytes_per_glyph": 35,
      "mapping": {
        "0": "0",
        "1": "1",
        ...
        "10": "A",
        ...
      }
    }

Usage:
    python tools/char_table.py init <out.json>
        # Buat JSON awal dengan mapping yang sudah teridentifikasi
    python tools/char_table.py dump <font.bin> <table.json> <out.txt>
        # Dump ASCII art tiap glyph + label dari table
    python tools/char_table.py set <table.json> <index> <char>
        # Tambah / update mapping satu entry
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GLYPH_W = 10
GLYPH_H = 14
BPG = 35  # bytes per glyph


# Mapping awal dari hasil reverse engineering visual.
# Glyph 0-61: digit, huruf besar, huruf kecil. Diidentifikasi dari ASCII art.
INITIAL_MAPPING = {}

# 0-9 = digit
for i in range(10):
    INITIAL_MAPPING[i] = str(i)

# 10-35 = A-Z
for i in range(26):
    INITIAL_MAPPING[10 + i] = chr(ord('A') + i)

# 36-61 = a-z
for i in range(26):
    INITIAL_MAPPING[36 + i] = chr(ord('a') + i)


def unpack_glyph(gb: bytes) -> list[int]:
    out = []
    for b in gb:
        out.append((b >> 6) & 3)
        out.append((b >> 4) & 3)
        out.append((b >> 2) & 3)
        out.append(b & 3)
    return out[:GLYPH_W * GLYPH_H]


def render_ascii(pixels: list[int]) -> list[str]:
    """Render pixel grid jadi ASCII art (4 level: ' .oX')."""
    rows = []
    for r in range(GLYPH_H):
        rows.append(''.join(' .oX'[pixels[r * GLYPH_W + c]] for c in range(GLYPH_W)))
    return rows


def cmd_init(args):
    """Buat JSON awal dengan mapping yang sudah diketahui."""
    table = {
        'format': 'fft-wotl-psp-v1',
        'font': 'FONT.BIN',
        'glyph_size': [GLYPH_W, GLYPH_H],
        'bpp': 2,
        'bytes_per_glyph': BPG,
        'order': 'msb',
        'description': 'Character table untuk FFT WoTL PSP. Key = glyph index (decimal), value = Unicode char.',
        # Note: JSON object keys harus string
        'mapping': {str(k): v for k, v in sorted(INITIAL_MAPPING.items())},
    }
    args.output.write_text(json.dumps(table, indent=2, ensure_ascii=False))
    print(f'Wrote {args.output}')
    print(f'  Total mapped: {len(INITIAL_MAPPING)} glyphs (0-{max(INITIAL_MAPPING)})')
    print(f'  Belum dimapping: glyph {max(INITIAL_MAPPING) + 1} ke atas')


def cmd_dump(args):
    """Dump tiap glyph + mapping (kalau ada) ke text file untuk review."""
    table = json.loads(args.table.read_text())
    mapping = {int(k): v for k, v in table['mapping'].items()}

    data = args.font.read_bytes()
    n_glyphs = len(data) // BPG
    if args.limit:
        n_glyphs = min(n_glyphs, args.limit)

    lines = [f'# Glyph dump dari {args.font.name}',
             f'# Format: {GLYPH_W}x{GLYPH_H} @ 2bpp, {n_glyphs} glyph',
             f'# Mapping dari: {args.table.name}',
             '',
             '# Legend: " " = blank, "." = light, "o" = medium, "X" = dark',
             '']

    for gi in range(n_glyphs):
        gb = data[gi * BPG:(gi + 1) * BPG]
        pix = unpack_glyph(gb)
        ch = mapping.get(gi, '?')
        ch_display = repr(ch) if ch != '?' else '? (UNMAPPED)'
        lines.append(f'--- Glyph #{gi} (0x{gi:02x}) = {ch_display} ---')
        for row in render_ascii(pix):
            lines.append(row)
        lines.append('')

    args.output.write_text('\n'.join(lines))
    print(f'Wrote {args.output}')
    mapped = sum(1 for gi in range(n_glyphs) if gi in mapping)
    print(f'  {mapped}/{n_glyphs} glyph sudah ter-mapping')


def cmd_set(args):
    """Update / tambah satu entry mapping."""
    table = json.loads(args.table.read_text())
    table['mapping'][str(args.index)] = args.char
    args.table.write_text(json.dumps(table, indent=2, ensure_ascii=False))
    print(f'Set glyph {args.index} -> {args.char!r}')


def cmd_stats(args):
    """Tampilkan statistik tabel."""
    table = json.loads(args.table.read_text())
    mapping = {int(k): v for k, v in table['mapping'].items()}
    chars = set(mapping.values())
    print(f'Total entries  : {len(mapping)}')
    print(f'Unique chars   : {len(chars)}')
    print(f'Index range    : {min(mapping)} - {max(mapping)}')
    print(f'Gaps           : ', end='')
    indices = sorted(mapping.keys())
    gaps = []
    for i in range(1, len(indices)):
        if indices[i] - indices[i-1] > 1:
            gaps.append(f'{indices[i-1] + 1}..{indices[i] - 1}')
    print(', '.join(gaps[:10]) + (' ...' if len(gaps) > 10 else '') if gaps else 'none')


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_init = sub.add_parser('init', help='Buat JSON awal')
    p_init.add_argument('output', type=Path)
    p_init.set_defaults(func=cmd_init)

    p_dump = sub.add_parser('dump', help='Dump ASCII art tiap glyph + mapping')
    p_dump.add_argument('font', type=Path)
    p_dump.add_argument('table', type=Path)
    p_dump.add_argument('output', type=Path)
    p_dump.add_argument('--limit', type=int, default=200,
                        help='Max glyph yang di-dump (default 200)')
    p_dump.set_defaults(func=cmd_dump)

    p_set = sub.add_parser('set', help='Set satu entry')
    p_set.add_argument('table', type=Path)
    p_set.add_argument('index', type=int)
    p_set.add_argument('char')
    p_set.set_defaults(func=cmd_set)

    p_stats = sub.add_parser('stats', help='Statistik table')
    p_stats.add_argument('table', type=Path)
    p_stats.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    args.func(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
