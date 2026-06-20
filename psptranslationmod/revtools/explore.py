"""Analisis heuristik file biner FFT (atau PSP umum).

Tiga level analisis:
  1. ASCII runs (printable 0x20-0x7E) — sample + count
  2. Byte frequency — top-N byte paling sering
  3. Format hints — header signature, struktur, ratio printable/high-bit

Pakai:
    python tools/explore.py <folder-atau-file> [--min-len N]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

ASCII_RUN = re.compile(rb'[\x20-\x7E]{4,}')


def iter_files(target: Path) -> Iterable[Path]:
    if target.is_file():
        yield target
        return
    for p in sorted(target.rglob('*')):
        if p.is_file():
            yield p


def ascii_runs(data: bytes, min_len: int) -> list[tuple[int, str]]:
    out = []
    for m in ASCII_RUN.finditer(data):
        if len(m.group()) >= min_len:
            out.append((m.start(), m.group().decode('ascii', errors='replace')))
    return out


def byte_stats(data: bytes) -> dict:
    counter = Counter(data)
    total = len(data)
    printable = sum(c for b, c in counter.items() if 0x20 <= b <= 0x7E)
    high_bit = sum(c for b, c in counter.items() if b >= 0x80)
    zero = counter.get(0, 0)
    return {
        'size': total,
        'unique_bytes': len(counter),
        'printable_pct': 100 * printable / total if total else 0,
        'high_bit_pct': 100 * high_bit / total if total else 0,
        'zero_pct': 100 * zero / total if total else 0,
        'top10': counter.most_common(10),
    }


def detect_format(data: bytes, name: str) -> list[str]:
    """Heuristik signature umum."""
    hints = []
    if len(data) < 4:
        return ['empty']
    head = data[:16]

    if head.startswith(b'CD001') or b'CD001' in data[:64]:
        hints.append('ISO 9660 PVD-like')
    if head[:4] in (b'\x1f\x8b\x08\x00', b'\x1f\x8b\x08\x08'):
        hints.append('gzip')
    if head[:4] == b'LZ77' or head[:2] == b'LZ':
        hints.append('possible LZ-something')
    if name.upper().endswith('.LZW'):
        hints.append('LZW-compressed (FFT custom)')
    if name.upper().endswith('.EVT'):
        hints.append('FFT event script + dialog (custom encoding + pointer table)')
    if name.upper().endswith('.MES'):
        hints.append('FFT message file')
    if name.upper().endswith('.OUT'):
        hints.append('FFT compiled section (often code + tables)')
    if name.upper().endswith('.BIN'):
        hints.append('generic binary')
    if all(b == 0 for b in data[:64]):
        hints.append('starts with zero-pad (may be raw image / palette)')
    return hints or ['unknown']


def format_report(path: Path, min_len: int) -> str:
    data = path.read_bytes()
    stats = byte_stats(data)
    hints = detect_format(data, path.name)
    runs = ascii_runs(data, min_len)

    lines = []
    lines.append(f'=== {path.name} ({stats["size"]:,} bytes) ===')
    lines.append(f'  Format hints   : {", ".join(hints)}')
    lines.append(
        f'  Byte stats     : printable={stats["printable_pct"]:.1f}%  '
        f'high-bit(>=0x80)={stats["high_bit_pct"]:.1f}%  '
        f'zero={stats["zero_pct"]:.1f}%  '
        f'unique={stats["unique_bytes"]}'
    )
    top = ', '.join(f'0x{b:02x}({c})' for b, c in stats['top10'])
    lines.append(f'  Top 10 bytes   : {top}')
    lines.append(f'  ASCII runs >= {min_len} chars : {len(runs)}')
    for off, text in runs[:5]:
        shown = text if len(text) <= 70 else text[:67] + '...'
        lines.append(f'    @0x{off:08x}  {shown!r}')
    if len(runs) > 5:
        lines.append(f'    ... {len(runs) - 5} more')
    lines.append('')
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('target', type=Path, help='File atau folder')
    ap.add_argument('--min-len', type=int, default=6,
                    help='Min panjang ASCII run untuk dilaporkan (default 6)')
    args = ap.parse_args()

    if not args.target.exists():
        print(f'error: {args.target} tidak ada', file=sys.stderr)
        return 1

    for f in iter_files(args.target):
        try:
            print(format_report(f, args.min_len))
        except OSError as e:
            print(f'! gagal baca {f}: {e}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
