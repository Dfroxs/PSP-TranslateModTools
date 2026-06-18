"""Render FONT.BIN dari FFT WoTL PSP.

Format yang sudah dikonfirmasi via reverse engineering:
  - 10 pixel wide × 14 pixel tall per glyph
  - 2 bits per pixel (4 level grayscale, anti-aliased)
  - MSB first bit order
  - 35 bytes per glyph (10 × 14 × 2 ÷ 8)
  - ~2223 glyphs total dalam 77824 byte file

Pakai:
    python tools/font_render.py <FONT.BIN> <out.pgm> [--cols 32] [--scale 4]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

GLYPH_W = 10
GLYPH_H = 14
BYTES_PER_GLYPH = 35  # 10 * 14 * 2 / 8


def unpack_glyph(gb: bytes) -> list[int]:
    """Unpack 35-byte glyph ke list 140 pixel value (0-3)."""
    pixels = []
    for b in gb:
        pixels.append((b >> 6) & 3)
        pixels.append((b >> 4) & 3)
        pixels.append((b >> 2) & 3)
        pixels.append(b & 3)
    return pixels[:GLYPH_W * GLYPH_H]


def render_all(data: bytes, cols: int, scale: int = 1) -> tuple[int, int, bytes]:
    n_glyphs = len(data) // BYTES_PER_GLYPH
    rows = (n_glyphs + cols - 1) // cols
    base_w = cols * GLYPH_W
    base_h = rows * GLYPH_H

    base = bytearray(base_w * base_h)
    for idx in range(n_glyphs):
        gx = (idx % cols) * GLYPH_W
        gy = (idx // cols) * GLYPH_H
        pixels = unpack_glyph(data[idx * BYTES_PER_GLYPH:(idx + 1) * BYTES_PER_GLYPH])
        for py in range(GLYPH_H):
            dst = (gy + py) * base_w + gx
            for px in range(GLYPH_W):
                base[dst + px] = pixels[py * GLYPH_W + px] * 85  # 0,85,170,255

    if scale == 1:
        return base_w, base_h, bytes(base)

    out_w = base_w * scale
    out_h = base_h * scale
    out = bytearray(out_w * out_h)
    for y in range(out_h):
        src_row = (y // scale) * base_w
        for x in range(out_w):
            out[y * out_w + x] = base[src_row + x // scale]
    return out_w, out_h, bytes(out)


def write_pgm(path: Path, width: int, height: int, pixels: bytes) -> None:
    with path.open('wb') as f:
        f.write(f'P5\n{width} {height}\n255\n'.encode())
        f.write(pixels)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('font', type=Path)
    ap.add_argument('output', type=Path, help='Output .pgm path')
    ap.add_argument('--cols', type=int, default=32,
                    help='Jumlah glyph per baris (default 32)')
    ap.add_argument('--scale', type=int, default=4,
                    help='Faktor scaling (default 4x untuk visibility)')
    args = ap.parse_args()

    data = args.font.read_bytes()
    n = len(data) // BYTES_PER_GLYPH
    print(f'Input: {args.font} ({len(data):,} bytes, {n} glyphs)')

    w, h, px = render_all(data, args.cols, args.scale)
    write_pgm(args.output, w, h, px)
    print(f'Output: {args.output} ({w}x{h})')
    print(f'\nBuka {args.output} di Preview / GIMP.')
    print('Glyph 0-9 = digit "0"-"9", glyph 10-35 = "A"-"Z".')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
