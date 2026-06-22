"""Encoder text → bytes untuk TEST.EVT (inverse decode_evt.py).

Input: decoded text dengan format yang sama seperti output decode_evt.py:
  - Plain chars: "a", "B", "0", ".", "!", " ", dll
  - Single-byte unmapped: `<XX>` dengan XX = 2 hex digit (mis. `<f8>`, `<e0>`)
  - Multi-byte sequences yang punya nama: `<SPEAKER>`, `<PRAYER>`
  - Karakter UTF-8 untuk multi-byte mapping: ",", "—", "ú"
  - Newline literal di string = decoded 0xfe (end-of-string)

Output: bytes yang seharusnya identik dengan original kalau decode→encode roundtrip.

Pakai:
    python tools/encode_evt.py <input.txt> <char_table.json> [--output out.bin]
    # atau lewat library: from encode_evt import encode_string
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Regex untuk parse tokens dalam encoded text:
#  1) <XX> hex placeholder (2 hex chars dalam <>)
#  2) <NAME> named multibyte (SPEAKER, PRAYER, dll)
#  3) single char (default fallback)
TOKEN_RE = re.compile(r'<([0-9a-fA-F]{2})>|<([A-Z_][A-Z_0-9]*)>|(\\n|.)', re.DOTALL)


def load_table(path: Path) -> tuple[dict[str, int], dict[str, bytes], dict[str, bytes]]:
    """Load char_table.json dan build REVERSE mappings.

    Returns:
        char_to_byte: char → int (single-byte mappings)
        char_to_multibyte: char → bytes (multi-byte mappings, e.g. "," → 0xda 0x74)
        name_to_bytes: name → bytes (named multibyte, e.g. "SPEAKER" → 0xe3 0x08)
    """
    table = json.loads(path.read_text())

    char_to_byte: dict[str, int] = {}
    for k, v in table['mapping'].items():
        char_to_byte[v] = int(k)

    char_to_multibyte: dict[str, bytes] = {}
    name_to_bytes: dict[str, bytes] = {}
    for hex_seq, val in table.get('multibyte', {}).items():
        seq_bytes = bytes.fromhex(hex_seq)
        if val.startswith('<') and val.endswith('>'):
            # Named multibyte, e.g. "<SPEAKER>"
            name_to_bytes[val[1:-1]] = seq_bytes
        else:
            # Character multibyte, e.g. "," or "—"
            char_to_multibyte[val] = seq_bytes

    return char_to_byte, char_to_multibyte, name_to_bytes


def encode_string(
    text: str,
    char_to_byte: dict[str, int],
    char_to_multibyte: dict[str, bytes],
    name_to_bytes: dict[str, bytes],
    strict: bool = False,
) -> bytes:
    """Encode decoded-text string back to bytes.

    Args:
        strict: kalau True, raise error untuk char yang tidak bisa di-encode.
                Kalau False, char yang tidak mapping di-skip dengan warning.
    """
    out = bytearray()
    i = 0
    n = len(text)
    warnings = []

    while i < n:
        m = TOKEN_RE.match(text, i)
        if not m:
            i += 1
            continue

        hex_token, name_token, char_token = m.groups()

        if hex_token:
            # <XX> raw byte
            out.append(int(hex_token, 16))
        elif name_token:
            # <NAME> named multibyte
            if name_token in name_to_bytes:
                out.extend(name_to_bytes[name_token])
            else:
                msg = f'Unknown named token <{name_token}> at pos {i}'
                if strict:
                    raise ValueError(msg)
                warnings.append(msg)
        elif char_token:
            # Plain character
            if char_token == '\n':
                # Newline literal → end-of-string 0xfe
                # (decode mapping 254: "\n")
                out.append(0xFE)
            elif char_token in char_to_multibyte:
                out.extend(char_to_multibyte[char_token])
            elif char_token in char_to_byte:
                out.append(char_to_byte[char_token])
            else:
                msg = f'Unknown char {char_token!r} (U+{ord(char_token):04X}) at pos {i}'
                if strict:
                    raise ValueError(msg)
                warnings.append(msg)

        i = m.end()

    if warnings:
        print(f'[warn] {len(warnings)} encoding issues:', file=sys.stderr)
        for w in warnings[:10]:
            print(f'  {w}', file=sys.stderr)
        if len(warnings) > 10:
            print(f'  ... +{len(warnings) - 10} more', file=sys.stderr)

    return bytes(out)


def find_unencodable(
    text: str,
    char_to_byte: dict[str, int],
    char_to_multibyte: dict[str, bytes],
    name_to_bytes: dict[str, bytes],
) -> list[str]:
    """Token yang akan di-DROP DIAM-DIAM oleh encode_string: char tak ter-mapping
    atau named token <NAME> yang tak dikenal. Raw byte `<XX>` selalu valid.

    Meniru tokenisasi encode_string PERSIS supaya tak ada false positive untuk
    `<...>` / multibyte / nama. Return list (boleh berulang) offender yang
    human-readable, mis. ['&', '<FOO>']. List kosong = sepenuhnya encodable.
    """
    bad: list[str] = []
    i, n = 0, len(text)
    while i < n:
        m = TOKEN_RE.match(text, i)
        if not m:
            i += 1
            continue
        hex_token, name_token, char_token = m.groups()
        if name_token and name_token not in name_to_bytes:
            bad.append(f'<{name_token}>')
        elif (char_token and char_token != '\n'
              and char_token not in char_to_multibyte
              and char_token not in char_to_byte):
            bad.append(char_token)
        i = m.end()
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('input', type=Path, help='Input text file (decoded format)')
    ap.add_argument('table', type=Path, help='Path char_table.json')
    ap.add_argument('--output', type=Path, help='Output binary file (default: stdout hex)')
    ap.add_argument('--strict', action='store_true', help='Error pada char tidak ter-encode')
    args = ap.parse_args()

    char_to_byte, char_to_multibyte, name_to_bytes = load_table(args.table)
    text = args.input.read_text()

    encoded = encode_string(text, char_to_byte, char_to_multibyte, name_to_bytes,
                            strict=args.strict)

    if args.output:
        args.output.write_bytes(encoded)
        print(f'Encoded {len(text):,} chars → {len(encoded):,} bytes', file=sys.stderr)
        print(f'Saved: {args.output}', file=sys.stderr)
    else:
        # Hex dump
        for i in range(0, len(encoded), 16):
            chunk = encoded[i:i + 16]
            hex_str = ' '.join(f'{b:02x}' for b in chunk)
            print(f'{i:08x}: {hex_str}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
