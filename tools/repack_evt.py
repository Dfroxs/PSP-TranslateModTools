"""Repack TEST.EVT dengan translasi ID — substitute bubble text di-place.

Strategi konservatif (Phase 5 dasar):
  - Modifikasi BYTE-LEVEL: replace bubble bytes dengan encoded translation
  - Constraint: translasi ID HARUS ≤ panjang original (truncate kalau lebih)
  - Padding 0x00 kalau translation lebih pendek
  - File size TETAP SAMA (no pointer rewriting needed)
  - Event alignment 0x800 dipertahankan otomatis

Input:
  - TEST.EVT original
  - events_parsed.json (dari evt_parser.py)
  - translations.json (dari Gemini atau manual) — format:
      {
        "blocks": [
          {"id": 0, "en": "...", "id_final": "..."},
          ...
        ]
      }

Output:
  - TEST.EVT modified
  - report.json dengan stats (block translated, skipped, truncated)

Pakai:
    python tools/repack_evt.py <original.evt> <events_parsed.json> \
        <translations.json> <char_table.json> --output modified.evt \
        [--allow-truncate] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from encode_evt import encode_string, load_table as load_encode_table  # noqa: E402


def find_bubble_byte_range(data: bytes, search_start: int, search_end: int,
                            en_decoded: str) -> tuple[int, int] | None:
    """Cari range byte di [search_start, search_end] yang decode jadi en_decoded.

    Sederhana: cari pattern bytes encoded dari en_decoded di range itu.
    """
    # Build minimal expected pattern (handle multi-byte chars + control codes)
    # For simplicity, scan the search range looking for exact byte match
    # of encoded en_decoded.
    # Caller must already have the byte_range info from events_parsed.json.
    pass


def count_trailing_zeros(data: bytes, end_pos: int, max_check: int = 4096) -> int:
    """Hitung berapa byte zero setelah end_pos (used as stretch buffer)."""
    count = 0
    for i in range(end_pos, min(end_pos + max_check, len(data))):
        if data[i] == 0:
            count += 1
        else:
            break
    return count


def repack(
    original_data: bytes,
    events: list[dict],
    translations: dict[int, str],
    char_table_path: Path,
    allow_truncate: bool = False,
    allow_stretch: bool = False,
) -> tuple[bytes, dict]:
    """Repack data dengan substituting translations.

    Args:
        original_data: bytes original file
        events: parsed events
        translations: dict {block_id: id_text}
        char_table_path: path char_table.json
        allow_truncate: kalau translation > original, truncate (else skip)
        allow_stretch: kalau translation > original DAN ada zero buffer setelahnya,
                      extend ke zero buffer. Lebih aman dari truncate.

    Returns:
        (modified_data, stats)
    """
    char_to_byte, char_to_multibyte, name_to_bytes = load_encode_table(char_table_path)
    out = bytearray(original_data)

    stats = {
        'total_translations': len(translations),
        'applied': 0,
        'applied_stretched': 0,
        'skipped_too_long': 0,
        'truncated': 0,
        'not_found': 0,
        'details': [],
    }

    # Build bubble lookup by block_id (only "text" kind bubbles get IDs)
    bubbles_by_id = {}
    block_id = 0
    for event in events:
        for bubble in event.get('bubbles', []):
            if bubble.get('kind') == 'text':
                bubbles_by_id[block_id] = bubble
                block_id += 1

    for tid, id_text in translations.items():
        if tid not in bubbles_by_id:
            stats['not_found'] += 1
            stats['details'].append({
                'id': tid,
                'status': 'not_found',
                'reason': f'block_id {tid} not in parsed bubbles',
            })
            continue

        bubble = bubbles_by_id[tid]
        byte_range = bubble.get('raw_byte_range') or bubble.get('byte_range')
        if byte_range:
            byte_start, byte_end = byte_range
        else:
            byte_start = bubble.get('byte_start')
            byte_end = bubble.get('byte_end')
        if byte_start is None or byte_end is None:
            stats['not_found'] += 1
            continue

        original_length = byte_end - byte_start

        # Encode ID text
        encoded = encode_string(id_text, char_to_byte, char_to_multibyte, name_to_bytes)

        # Bubble text di parsed JSON strip trailing 0xFE terminator. Tapi byte_range
        # INCLUDES 0xFE. Jadi kita harus pastikan encoded ends with 0xFE.
        if not encoded.endswith(b'\xfe'):
            encoded = encoded + b'\xfe'

        if len(encoded) > original_length:
            overflow = len(encoded) - original_length
            # Coba stretch ke trailing zeros
            if allow_stretch:
                buffer = count_trailing_zeros(original_data, byte_end)
                if buffer >= overflow:
                    out[byte_start:byte_start + len(encoded)] = encoded
                    stats['applied_stretched'] += 1
                    stats['details'].append({
                        'id': tid,
                        'status': 'stretched',
                        'original_len': original_length,
                        'encoded_len': len(encoded),
                        'stretched_bytes': overflow,
                        'buffer_available': buffer,
                    })
                    continue

            if allow_truncate:
                encoded = encoded[:original_length]
                stats['truncated'] += 1
                stats['details'].append({
                    'id': tid,
                    'status': 'truncated',
                    'original_len': original_length,
                    'encoded_len': len(encoded) + overflow,
                    'lost_bytes': overflow,
                })
            else:
                buffer = count_trailing_zeros(original_data, byte_end)
                stats['skipped_too_long'] += 1
                stats['details'].append({
                    'id': tid,
                    'status': 'skipped_too_long',
                    'original_len': original_length,
                    'encoded_len': len(encoded),
                    'overflow': overflow,
                    'buffer_available': buffer,
                    'en': bubble.get('text', '')[:60],
                    'id_text': id_text[:60],
                })
                continue

        # Substitute + pad with 0x00
        out[byte_start:byte_start + len(encoded)] = encoded
        if len(encoded) < original_length:
            for i in range(byte_start + len(encoded), byte_end):
                out[i] = 0x00

        stats['applied'] += 1

    return bytes(out), stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('original', type=Path, help='Original TEST.EVT')
    ap.add_argument('events', type=Path, help='events_parsed.json')
    ap.add_argument('translations', type=Path, help='translations.json')
    ap.add_argument('table', type=Path, help='char_table.json')
    ap.add_argument('--output', type=Path, required=True, help='Output modified TEST.EVT')
    ap.add_argument('--report', type=Path, help='Output stats report JSON')
    ap.add_argument('--allow-truncate', action='store_true',
                    help='Truncate translation kalau lebih panjang dari original (LOSSY)')
    ap.add_argument('--allow-stretch', action='store_true',
                    help='Extend ke trailing zero bytes jika tersedia (SAFE)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Compute stats tanpa tulis output')
    args = ap.parse_args()

    original_data = args.original.read_bytes()
    events_data = json.loads(args.events.read_text())

    # Normalize events format (might be {"events": [...]} or just [...])
    if isinstance(events_data, dict):
        events_list = events_data.get('events', events_data.get('parsed', []))
    else:
        events_list = events_data

    trans_data = json.loads(args.translations.read_text())
    blocks = trans_data.get('blocks', trans_data) if isinstance(trans_data, dict) else trans_data

    # Build translations dict
    translations = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        tid = block.get('id')
        # Prefer id_final, fallback id_auto
        id_text = block.get('id_final') or block.get('id_auto')
        if tid is not None and id_text:
            translations[tid] = id_text

    print(f'Original: {len(original_data):,} bytes', file=sys.stderr)
    print(f'Events: {len(events_list)}', file=sys.stderr)
    print(f'Translations: {len(translations)} blocks', file=sys.stderr)

    modified, stats = repack(
        original_data, events_list, translations, args.table,
        allow_truncate=args.allow_truncate,
        allow_stretch=args.allow_stretch,
    )

    print(file=sys.stderr)
    print('=== Repack stats ===', file=sys.stderr)
    print(f'  Applied (in-place) : {stats["applied"]}', file=sys.stderr)
    print(f'  Applied (stretched): {stats["applied_stretched"]}', file=sys.stderr)
    print(f'  Skipped (too long) : {stats["skipped_too_long"]}', file=sys.stderr)
    print(f'  Truncated          : {stats["truncated"]}', file=sys.stderr)
    print(f'  Not found          : {stats["not_found"]}', file=sys.stderr)

    if stats['skipped_too_long'] > 0:
        print(file=sys.stderr)
        print(f'⚠️  {stats["skipped_too_long"]} translations skipped — use --allow-truncate', file=sys.stderr)
        print('   atau perpendek translation ID supaya muat di slot original', file=sys.stderr)

    if not args.dry_run:
        args.output.write_bytes(modified)
        print(f'\nOutput: {args.output} ({len(modified):,} bytes)', file=sys.stderr)
        # Verify integrity
        assert len(modified) == len(original_data), 'output size mismatch!'

    if args.report:
        args.report.write_text(json.dumps(stats, indent=2, ensure_ascii=False))
        print(f'Report: {args.report}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
