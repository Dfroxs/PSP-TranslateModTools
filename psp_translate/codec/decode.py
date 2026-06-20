"""Decoder TEST.EVT (dan file FFT WoTL serupa) menggunakan char_table.json.

Decoder ini handle:
  - Single-byte chars (digit, A-Z, a-z, punctuation, space)
  - Multi-byte sequences (mis. 0xda 0x74 = ',')
  - Control codes (0xe3 0x08 = speaker tag, 0xfe = end-of-string)
  - Padding bytes (0x00 di-skip)

Pakai:
    python tools/decode_evt.py <file.evt> <char_table.json> [--offset 0x5800] [--length 1024]
    python tools/decode_evt.py <file.evt> <char_table.json> --search "Father"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_table(path: Path) -> tuple[dict[int, str], dict[bytes, str]]:
    table = json.loads(path.read_text())
    mapping = {int(k): v for k, v in table['mapping'].items()}
    multibyte = {}
    for hex_seq, ch in table.get('multibyte', {}).items():
        multibyte[bytes.fromhex(hex_seq)] = ch
    return mapping, multibyte


def decode(data: bytes, mapping: dict[int, str], multibyte: dict[bytes, str],
           skip_padding: bool = True, annotate_unknown: bool = True) -> str:
    out = []
    i = 0
    n = len(data)
    # Sort multibyte keys by length desc supaya yang panjang dicek dulu
    mb_keys = sorted(multibyte.keys(), key=lambda k: -len(k))

    while i < n:
        b = data[i]
        if b == 0 and skip_padding:
            i += 1
            continue

        # Try multibyte sequence
        matched = False
        for seq in mb_keys:
            if data[i:i + len(seq)] == seq:
                out.append(multibyte[seq])
                i += len(seq)
                matched = True
                break
        if matched:
            continue

        # Single byte
        if b in mapping:
            out.append(mapping[b])
        elif annotate_unknown:
            out.append(f'<{b:02x}>')
        else:
            out.append('?')
        i += 1

    return ''.join(out)


def find_text(data: bytes, mapping: dict[int, str], multibyte: dict[bytes, str],
              query: str, context: int = 100) -> list[tuple[int, str]]:
    """Cari string query di decoded data. Return list (offset, context)."""
    # Decode seluruh data dengan tracking offset
    decoded_parts = []  # list of (decoded_char_or_chunk, byte_offset)
    i = 0
    n = len(data)
    mb_keys = sorted(multibyte.keys(), key=lambda k: -len(k))

    while i < n:
        b = data[i]
        if b == 0:
            i += 1
            continue
        matched = False
        for seq in mb_keys:
            if data[i:i + len(seq)] == seq:
                decoded_parts.append((multibyte[seq], i))
                i += len(seq)
                matched = True
                break
        if matched:
            continue
        if b in mapping:
            decoded_parts.append((mapping[b], i))
        else:
            decoded_parts.append((f'<{b:02x}>', i))
        i += 1

    decoded_str = ''.join(p[0] for p in decoded_parts)
    # Build offset map: index in decoded_str → byte offset
    offset_map = []
    for chunk, off in decoded_parts:
        for _ in range(len(chunk)):
            offset_map.append(off)

    results = []
    start = 0
    while True:
        pos = decoded_str.find(query, start)
        if pos == -1:
            break
        byte_off = offset_map[pos] if pos < len(offset_map) else -1
        ctx_start = max(0, pos - context)
        ctx_end = min(len(decoded_str), pos + len(query) + context)
        ctx = decoded_str[ctx_start:ctx_end]
        results.append((byte_off, ctx))
        start = pos + 1
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('file', type=Path)
    ap.add_argument('table', type=Path)
    ap.add_argument('--offset', default='0',
                    help='Byte offset untuk mulai decode (default 0, support hex 0x5800)')
    ap.add_argument('--length', type=int, default=2048,
                    help='Jumlah byte yang di-decode (default 2048)')
    ap.add_argument('--search', help='Cari string di seluruh file')
    ap.add_argument('--full', action='store_true', help='Decode seluruh file')
    ap.add_argument('--no-annotate', action='store_true',
                    help='Tampilkan ? untuk byte tidak dikenal (default: <xx>)')
    args = ap.parse_args()

    mapping, multibyte = load_table(args.table)
    data = args.file.read_bytes()
    print(f'File: {args.file} ({len(data):,} bytes)', file=sys.stderr)
    print(f'Mapping: {len(mapping)} single-byte + {len(multibyte)} multi-byte', file=sys.stderr)
    print(file=sys.stderr)

    if args.search:
        results = find_text(data, mapping, multibyte, args.search)
        print(f'Found {len(results)} occurrences of {args.search!r}')
        for off, ctx in results[:20]:
            print(f'\n@0x{off:06x}:')
            print(ctx)
        if len(results) > 20:
            print(f'\n... {len(results) - 20} more')
        return 0

    if args.full:
        chunk = data
        start = 0
    else:
        start = int(args.offset, 0) if isinstance(args.offset, str) else args.offset
        chunk = data[start:start + args.length]

    result = decode(chunk, mapping, multibyte,
                    annotate_unknown=not args.no_annotate)
    print(f'=== Decode @0x{start:06x} ({len(chunk):,} bytes) ===')
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
