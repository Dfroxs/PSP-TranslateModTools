"""Patch fftpack.bin dengan file-file yang sudah dimodifikasi.

Strategi: substitusi byte-level pada offset yang sudah dipetakan di
`fftpack_event_map.json`. Hanya bekerja kalau file modifikasi SAMA UKURAN
dengan original (Phase 5 menjamin ini untuk TEST.EVT).

Pakai:
    python tools/repack_fftpack.py \\
        --fftpack <fftpack.bin> \\
        --map <fftpack_event_map.json> \\
        --substitute TEST.EVT:<modified.evt> \\
        --substitute WORLD.LZW:<modified.lzw> \\
        --output <modified_fftpack.bin>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def patch_fftpack(
    fftpack_data: bytes,
    file_map: dict[str, dict],
    substitutions: dict[str, Path],
) -> tuple[bytes, dict]:
    """Apply substitutions to fftpack data."""
    out = bytearray(fftpack_data)
    stats = {
        'requested': len(substitutions),
        'applied': 0,
        'failed': 0,
        'details': [],
    }

    for fname, new_path in substitutions.items():
        if fname not in file_map:
            stats['failed'] += 1
            stats['details'].append({
                'file': fname,
                'status': 'not_in_map',
            })
            continue

        info = file_map[fname]
        offset = info.get('offset')
        orig_size = info.get('size')
        if offset is None or offset < 0:
            stats['failed'] += 1
            stats['details'].append({
                'file': fname,
                'status': 'no_offset',
            })
            continue

        new_data = new_path.read_bytes()
        if len(new_data) != orig_size:
            stats['failed'] += 1
            stats['details'].append({
                'file': fname,
                'status': 'size_mismatch',
                'orig_size': orig_size,
                'new_size': len(new_data),
            })
            continue

        # Substitute
        out[offset:offset + len(new_data)] = new_data
        stats['applied'] += 1
        stats['details'].append({
            'file': fname,
            'status': 'applied',
            'offset': offset,
            'size': len(new_data),
        })

    return bytes(out), stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--fftpack', type=Path, required=True, help='Original fftpack.bin')
    ap.add_argument('--map', type=Path, required=True, help='fftpack_event_map.json')
    ap.add_argument('--substitute', action='append', default=[],
                    help='FILENAME:path/to/new_file (can repeat)')
    ap.add_argument('--output', type=Path, required=True, help='Output modified fftpack.bin')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    map_data = json.loads(args.map.read_text())
    file_map = map_data['files']

    # Parse substitutions
    substitutions: dict[str, Path] = {}
    for spec in args.substitute:
        if ':' not in spec:
            print(f'error: invalid substitution {spec!r}, expected FILENAME:PATH', file=sys.stderr)
            return 1
        fname, path = spec.split(':', 1)
        substitutions[fname] = Path(path)

    if not substitutions:
        print('warning: no substitutions specified — output will be identical to input',
              file=sys.stderr)

    print(f'Loading fftpack.bin ({args.fftpack})...', file=sys.stderr)
    fftpack_data = args.fftpack.read_bytes()
    print(f'  Size: {len(fftpack_data):,} bytes', file=sys.stderr)

    patched, stats = patch_fftpack(fftpack_data, file_map, substitutions)

    print(f'\n=== Patch stats ===', file=sys.stderr)
    print(f'  Requested : {stats["requested"]}', file=sys.stderr)
    print(f'  Applied   : {stats["applied"]}', file=sys.stderr)
    print(f'  Failed    : {stats["failed"]}', file=sys.stderr)

    for detail in stats['details']:
        marker = '✅' if detail['status'] == 'applied' else '❌'
        print(f'  {marker} {detail["file"]:20s}: {detail["status"]}', file=sys.stderr)
        if detail['status'] == 'applied':
            print(f'      @0x{detail["offset"]:08x}  ({detail["size"]:,} bytes)', file=sys.stderr)
        elif detail['status'] == 'size_mismatch':
            print(f'      orig={detail["orig_size"]:,}, new={detail["new_size"]:,}', file=sys.stderr)

    if not args.dry_run:
        args.output.write_bytes(patched)
        print(f'\nOutput: {args.output} ({len(patched):,} bytes)', file=sys.stderr)
        assert len(patched) == len(fftpack_data), 'size mismatch in output!'

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
