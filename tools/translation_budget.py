"""Hitung budget byte per bubble — berapa max panjang translation ID yang aman.

Untuk setiap bubble di events_parsed.json:
  - original_bytes: panjang original (encoded EN)
  - safe_bytes: max kalau substitute IN-PLACE (= original_bytes)
  - stretch_bytes: max kalau pakai trailing zero buffer (kalau ada)
  - event_padding_bytes: total zero padding di akhir event (informational)

Output JSON bisa di-feed ke translator (Gemini atau human) sebagai constraint.

Pakai:
    python tools/translation_budget.py <test.evt> <events_parsed.json> <char_table.json> --output budget.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from encode_evt import encode_string, load_table  # noqa: E402


def count_trailing_zeros(data: bytes, start: int, max_check: int = 4096) -> int:
    count = 0
    for i in range(start, min(start + max_check, len(data))):
        if data[i] == 0:
            count += 1
        else:
            break
    return count


def event_trailing_padding(data: bytes, event_offset: int, event_size: int) -> int:
    """Hitung trailing zero padding di akhir event."""
    pad = 0
    end = event_offset + event_size
    for i in range(end - 1, event_offset - 1, -1):
        if data[i] == 0:
            pad += 1
        else:
            break
    return pad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('evt', type=Path)
    ap.add_argument('parsed', type=Path)
    ap.add_argument('table', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()

    data = args.evt.read_bytes()
    parsed = json.loads(args.parsed.read_text())
    events = parsed.get('events', parsed)
    char_to_byte, char_to_multibyte, name_to_bytes = load_table(args.table)

    # Build event padding lookup
    event_paddings: dict[int, int] = {}
    for event in events:
        offset = event.get('offset')
        size = event.get('size')
        if offset is not None and size is not None:
            event_paddings[offset] = event_trailing_padding(data, offset, size)

    budgets = []
    block_id = 0
    for event in events:
        event_offset = event.get('offset', 0)
        event_pad = event_paddings.get(event_offset, 0)
        for bubble in event.get('bubbles', []):
            if bubble.get('kind') != 'text':
                continue
            byte_range = bubble.get('raw_byte_range')
            if not byte_range:
                continue
            start, end = byte_range
            orig_bytes = end - start

            # Trailing zeros immediately after this bubble (= adjacent stretch buffer)
            stretch_buffer = count_trailing_zeros(data, end)

            text = bubble.get('text', '')

            # Verify by encoding the text + appending 0xfe terminator (same as repack)
            encoded = encode_string(text, char_to_byte, char_to_multibyte, name_to_bytes)
            if not encoded.endswith(b'\xfe'):
                encoded = encoded + b'\xfe'

            budgets.append({
                'id': block_id,
                'event_id': event.get('event_id'),
                'event_offset': event_offset,
                'byte_start': start,
                'byte_end': end,
                'original_bytes': orig_bytes,
                'safe_bytes': orig_bytes,  # in-place substitution
                'stretch_bytes': orig_bytes + stretch_buffer,  # with adjacent zero buffer
                'event_padding_bytes': event_pad,  # event-level padding (informational)
                'en_text': text,
                'speaker': bubble.get('speaker'),
                'encoded_check': len(encoded) == orig_bytes,  # sanity: roundtrip works
            })
            block_id += 1

    # Stats
    total = len(budgets)
    sums = {
        'orig': sum(b['original_bytes'] for b in budgets),
        'safe': sum(b['safe_bytes'] for b in budgets),
        'stretch': sum(b['stretch_bytes'] for b in budgets),
        'event_pad': sum(set(b['event_padding_bytes'] for b in budgets)),
    }
    avg_orig = sums['orig'] / total if total else 0
    avg_stretch = sums['stretch'] / total if total else 0
    with_stretch_room = sum(1 for b in budgets if b['stretch_bytes'] > b['safe_bytes'])

    result = {
        'metadata': {
            'source_file': str(args.evt),
            'total_bubbles': total,
            'total_orig_bytes': sums['orig'],
            'total_stretch_bytes': sums['stretch'],
            'avg_orig_bytes': round(avg_orig, 1),
            'avg_stretch_bytes': round(avg_stretch, 1),
            'bubbles_with_stretch_room': with_stretch_room,
            'event_padding_total': sum(event_paddings.values()),
        },
        'budgets': budgets,
    }

    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    print(f'Bubbles processed: {total}', file=sys.stderr)
    print(f'Avg original bytes/bubble: {avg_orig:.1f}', file=sys.stderr)
    print(f'Avg stretch bytes/bubble : {avg_stretch:.1f}', file=sys.stderr)
    print(f'Bubbles with stretch room: {with_stretch_room} ({100*with_stretch_room/total:.1f}%)', file=sys.stderr)
    print(f'Total event padding      : {sum(event_paddings.values()):,} bytes', file=sys.stderr)
    print(f'\nSaved: {args.output}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
