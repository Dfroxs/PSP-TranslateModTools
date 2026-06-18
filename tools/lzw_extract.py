"""Extract entries dari file .LZW FFT WoTL.

Discovery: file .LZW BUKAN compressed (despite naming). Format-nya:
  - 128-byte header (32 × 4-byte LE pointer offsets, relatif ke data section)
  - Data section dimulai @0x80
  - Setiap pointer menunjuk ke awal string (0xFE-terminated)
  - String encoding sama dengan TEST.EVT (pakai char_table.json)

Pengecualian: HELP.LZW dan WLDHELP.LZW punya 0xF0 dominan — mungkin
beneran punya kompresi tambahan. Untuk file ini, decoder mungkin tidak
sempurna sampai compression-nya di-reverse-engineer.

Pakai:
    python tools/lzw_extract.py <file.LZW> <char_table.json> [--output out.json]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


HEADER_SIZE = 0x80  # 128 bytes (32 entries × 4 bytes)


def load_table(path: Path) -> tuple[dict[int, str], dict[bytes, str]]:
    table = json.loads(path.read_text())
    mapping = {int(k): v for k, v in table['mapping'].items()}
    multibyte = {bytes.fromhex(k): v for k, v in table.get('multibyte', {}).items()}
    return mapping, multibyte


def decode_string(data: bytes, mapping: dict[int, str],
                  multibyte: dict[bytes, str]) -> str:
    out = []
    i = 0
    mb_keys = sorted(multibyte.keys(), key=lambda k: -len(k))
    while i < len(data):
        b = data[i]
        if b == 0:
            i += 1
            continue
        matched = False
        for seq in mb_keys:
            if data[i:i + len(seq)] == seq:
                out.append(multibyte[seq])
                i += len(seq)
                matched = True
                break
        if matched:
            continue
        if b in mapping:
            out.append(mapping[b])
        else:
            out.append(f'<{b:02x}>')
        i += 1
    return ''.join(out)


def parse_header(data: bytes, header_size: int = HEADER_SIZE) -> list[int]:
    """Parse header sebagai array of 32-bit LE offsets."""
    n_entries = header_size // 4
    return [
        struct.unpack('<I', data[i * 4:(i + 1) * 4])[0]
        for i in range(n_entries)
    ]


def extract_entries(data: bytes, mapping: dict[int, str],
                    multibyte: dict[bytes, str],
                    header_size: int = HEADER_SIZE) -> list[dict]:
    """Extract semua string dari file .LZW.

    Tiap entry = chunk dari pointer[i] sampai pointer[i+1] (atau EOF).
    Chunk bisa berisi multiple sub-strings dipisah dengan 0xFE.
    """
    pointers = parse_header(data, header_size)
    data_section_start = header_size
    data_section = data[data_section_start:]

    entries = []
    for idx, ptr in enumerate(pointers):
        if ptr >= len(data_section):
            entries.append({
                'index': idx,
                'pointer': ptr,
                'raw_offset': data_section_start + ptr,
                'text': None,
                'error': f'pointer {ptr} > data section size {len(data_section)}',
            })
            continue

        # Chunk dari pointer[i] sampai pointer[i+1] atau EOF
        if idx + 1 < len(pointers) and pointers[idx + 1] > ptr:
            chunk_end = pointers[idx + 1]
        else:
            chunk_end = len(data_section)

        chunk = data_section[ptr:chunk_end]

        # Split berdasarkan 0xFE menjadi sub-strings
        sub_strings = []
        cur_start = 0
        for i, b in enumerate(chunk):
            if b == 0xFE:
                if i > cur_start:
                    sub_strings.append(chunk[cur_start:i])
                cur_start = i + 1
        if cur_start < len(chunk):
            sub_strings.append(chunk[cur_start:])

        decoded_subs = [decode_string(s, mapping, multibyte) for s in sub_strings]
        entries.append({
            'index': idx,
            'pointer': ptr,
            'raw_offset': data_section_start + ptr,
            'chunk_length': len(chunk),
            'sub_strings': decoded_subs,
        })

    return entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('file', type=Path, help='File .LZW input')
    ap.add_argument('table', type=Path, help='Path char_table.json')
    ap.add_argument('--output', type=Path, help='Output JSON file (optional)')
    ap.add_argument('--header-size', type=lambda x: int(x, 0), default=HEADER_SIZE,
                    help='Header size in bytes (default 0x80)')
    ap.add_argument('--limit', type=int, help='Limit jumlah entries yang ditampilkan')
    args = ap.parse_args()

    if not args.file.exists():
        print(f'error: {args.file} tidak ada', file=sys.stderr)
        return 1

    data = args.file.read_bytes()
    mapping, multibyte = load_table(args.table)

    entries = extract_entries(data, mapping, multibyte, args.header_size)

    # Console preview
    print(f'File: {args.file} ({len(data):,} bytes)', file=sys.stderr)
    print(f'Header size: {args.header_size} bytes ({args.header_size // 4} entries)', file=sys.stderr)
    print(f'Data section: {len(data) - args.header_size:,} bytes', file=sys.stderr)
    print(f'Entries extracted: {len(entries)}', file=sys.stderr)
    print(file=sys.stderr)

    # Preview
    shown = args.limit if args.limit else min(20, len(entries))
    print(f'=== First {shown} entries ===')
    for e in entries[:shown]:
        if e.get('sub_strings') is None:
            print(f'[{e["index"]:3d}] ERROR: {e.get("error")}')
            continue
        subs = e['sub_strings']
        n = len(subs)
        if n == 0:
            print(f'[{e["index"]:3d}] @0x{e["raw_offset"]:06x} (chunk={e["chunk_length"]}): <empty>')
        elif n == 1:
            s = subs[0][:80] + '...' if len(subs[0]) > 80 else subs[0]
            print(f'[{e["index"]:3d}] @0x{e["raw_offset"]:06x} (chunk={e["chunk_length"]}): {s!r}')
        else:
            print(f'[{e["index"]:3d}] @0x{e["raw_offset"]:06x} (chunk={e["chunk_length"]}, {n} subs):')
            for i, s in enumerate(subs[:5]):
                ss = s[:70] + '...' if len(s) > 70 else s
                print(f'        [{i}] {ss!r}')
            if n > 5:
                print(f'        ... +{n - 5} more')

    # Save JSON
    if args.output:
        result = {
            'file': str(args.file),
            'file_size': len(data),
            'header_size': args.header_size,
            'num_entries': len(entries),
            'entries': entries,
        }
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f'\nSaved: {args.output}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
