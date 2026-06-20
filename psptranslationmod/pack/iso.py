"""Patch ISO PSP dengan file modifikasi (size-preserving).

Strategi: substitusi byte-level pada offset yang sudah dipetakan.
Karena modifikasi mempertahankan ukuran file (Phase 5), kita tidak perlu
rebuild ISO dari scratch. Cukup overwrite bytes di posisi yang sama.

Pakai:
    python tools/patch_iso.py \\
        --iso <original.iso> \\
        --substitute fftpack.bin:<modified_fftpack.bin>:0x02c20000 \\
        --output <modified.iso>

Atau pakai discovery mode (cari offset otomatis berdasarkan content match):
    python tools/patch_iso.py \\
        --iso <original.iso> \\
        --substitute-auto fftpack.bin:<modified_fftpack.bin>:<original_fftpack.bin> \\
        --output <modified.iso>
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def find_offset_in_iso(iso_path: Path, original_file: Path) -> int | None:
    """Cari offset original_file di ISO dengan content matching."""
    orig_data = original_file.read_bytes()
    fp = orig_data[:64]
    fp_size = len(orig_data)

    chunk_size = 16 * 1024 * 1024
    with iso_path.open('rb') as f:
        offset = 0
        last_chunk = b''
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            search_data = last_chunk + data
            idx = search_data.find(fp)
            if idx >= 0:
                iso_offset = offset - len(last_chunk) + idx
                f.seek(iso_offset)
                if f.read(fp_size) == orig_data:
                    return iso_offset
            last_chunk = data[-len(fp):]
            offset += len(data)
    return None


def patch_iso(
    iso_path: Path,
    output_path: Path,
    substitutions: list[tuple[str, Path, int]],
) -> dict:
    """Apply substitutions to ISO. Returns stats dict.

    Args:
        substitutions: list of (label, source_file, offset_in_iso)
    """
    # Copy ISO to output first (preserve original)
    if iso_path != output_path:
        print(f'Copying {iso_path} → {output_path}...', file=sys.stderr)
        shutil.copy2(iso_path, output_path)

    stats = {'applied': 0, 'failed': 0, 'details': []}

    iso_size = output_path.stat().st_size

    with output_path.open('r+b') as f:
        for label, src_file, offset in substitutions:
            new_data = src_file.read_bytes()
            if offset + len(new_data) > iso_size:
                stats['failed'] += 1
                stats['details'].append({
                    'label': label,
                    'status': 'overflow',
                    'offset': offset,
                    'new_size': len(new_data),
                    'iso_size': iso_size,
                })
                continue

            f.seek(offset)
            f.write(new_data)
            stats['applied'] += 1
            stats['details'].append({
                'label': label,
                'status': 'applied',
                'offset': offset,
                'size': len(new_data),
            })

    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', type=Path, required=True, help='Original ISO')
    ap.add_argument('--output', type=Path, required=True, help='Output modified ISO')
    ap.add_argument('--substitute', action='append', default=[],
                    help='LABEL:NEW_FILE:OFFSET (hex like 0x02c20000 atau decimal)')
    ap.add_argument('--substitute-auto', action='append', default=[],
                    help='LABEL:NEW_FILE:ORIG_FILE — auto-find offset via content match')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    substitutions = []

    # Manual substitutions
    for spec in args.substitute:
        parts = spec.split(':')
        if len(parts) != 3:
            print(f'error: invalid --substitute {spec!r}', file=sys.stderr)
            return 1
        label, path, offset_str = parts
        offset = int(offset_str, 0)
        substitutions.append((label, Path(path), offset))

    # Auto-discovery
    for spec in args.substitute_auto:
        parts = spec.split(':')
        if len(parts) != 3:
            print(f'error: invalid --substitute-auto {spec!r}', file=sys.stderr)
            return 1
        label, new_path, orig_path = parts
        print(f'Searching {label} in ISO via content match...', file=sys.stderr)
        offset = find_offset_in_iso(args.iso, Path(orig_path))
        if offset is None:
            print(f'  ❌ Not found', file=sys.stderr)
            continue
        print(f'  ✅ Found @0x{offset:08x}', file=sys.stderr)
        substitutions.append((label, Path(new_path), offset))

    if not substitutions:
        print('error: no substitutions specified', file=sys.stderr)
        return 1

    if args.dry_run:
        print(f'\n[DRY RUN] Would patch:', file=sys.stderr)
        for label, path, offset in substitutions:
            new_size = path.stat().st_size
            print(f'  {label}: {path} ({new_size:,} B) → ISO @0x{offset:08x}', file=sys.stderr)
        return 0

    print(f'\nPatching {args.iso} → {args.output}', file=sys.stderr)
    stats = patch_iso(args.iso, args.output, substitutions)

    print(f'\n=== Patch stats ===', file=sys.stderr)
    print(f'  Applied : {stats["applied"]}', file=sys.stderr)
    print(f'  Failed  : {stats["failed"]}', file=sys.stderr)
    for d in stats['details']:
        marker = '✅' if d['status'] == 'applied' else '❌'
        print(f'  {marker} {d["label"]:30s}: {d["status"]}', file=sys.stderr)
        if d['status'] == 'applied':
            print(f'      @0x{d["offset"]:08x}  ({d["size"]:,} bytes)', file=sys.stderr)

    print(f'\nOutput: {args.output}', file=sys.stderr)
    print(f'Test in PPSSPP to verify game still boots & dialog shows correctly.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
