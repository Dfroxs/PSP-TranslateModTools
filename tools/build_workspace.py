"""Build translation workspace dari events_parsed.json.

Berbeda dengan translation_workspace.py yang baca dialog_only.txt (filtered),
tool ini baca events_parsed.json langsung supaya block IDs SINKRON dengan
repack_evt.py.

Hanya bubble dengan kind='text' yang masuk workspace. Bubble bytecode/empty
di-skip (tidak perlu ditranslate).

Output workspace JSON per chunk + index.json + skip-stats.

Pakai:
    python tools/build_workspace.py <events_parsed.json> <workspace_dir> \
        [--chunk-size 100] [--filter-quality]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SPEAKER_RE = re.compile(r'^<SPEAKER>([^<]+)<')
SPEAKER_INLINE_RE = re.compile(r'<SPEAKER>([A-Za-z][A-Za-z0-9 .\'<>]{0,40}?)<f8><e3>')


def _extract_speaker_from_text(text: str) -> str | None:
    """Coba ekstrak speaker name dari awal text content."""
    if not text:
        return None
    m = SPEAKER_INLINE_RE.search(text)
    if m:
        name = m.group(1).strip()
        return name if name else None
    # Fallback: simple "<SPEAKER>NAME<" pattern at start
    m = SPEAKER_RE.match(text)
    if m:
        return m.group(1).strip()
    return None


def extract_dialog_blocks(events_parsed: dict, filter_quality: bool = False) -> list[dict]:
    """Ekstrak semua text bubbles dengan stable block_id.

    Speaker logic:
      - Pertama coba bubble['speaker'] (kalau parser sudah extract)
      - Kalau text starts dengan <SPEAKER>X<f8><e3>, extract X
      - Kalau previous bubble di event sama adalah kind='speaker', pakai namanya
    """
    blocks = []
    block_id = 0

    for event in events_parsed.get('events', []):
        event_id = event.get('event_id')
        last_speaker_in_event = None
        for bubble in event.get('bubbles', []):
            kind = bubble.get('kind')

            if kind == 'speaker':
                last_speaker_in_event = bubble.get('speaker') or _extract_speaker_from_text(
                    bubble.get('text', ''))
                continue

            if kind != 'text':
                continue

            text = bubble.get('text', '')
            # Only set speaker if explicit, OR if last_speaker is recent AND
            # text doesn't look like new utterance (no leading <SPEAKER>)
            speaker = bubble.get('speaker') or _extract_speaker_from_text(text)
            # Don't auto-propagate last_speaker_in_event (too noisy — same speaker
            # tag can apply to many subsequent bubbles, but it's hard to know cutoff)
            # Translator can re-derive from context if needed.
            byte_range = bubble.get('raw_byte_range', [None, None])

            # Apply quality filter (skip mostly-unmapped bubbles — likely bytecode region)
            if filter_quality:
                total = len(text)
                if total == 0:
                    block_id += 1
                    continue
                unmapped = len(re.findall(r'<[0-9a-f]{2}>', text))
                letters = sum(c.isalpha() for c in text)
                # Skip if mostly control codes / no readable text
                if letters < 5 or unmapped * 4 / total > 0.5:
                    block_id += 1
                    continue

            blocks.append({
                'id': block_id,
                'event_id': event_id,
                'en': text,
                'speaker': speaker,
                'byte_range': byte_range,
                'byte_length': byte_range[1] - byte_range[0] if byte_range[0] else 0,
                'id_auto': None,
                'id_final': None,
                'status': 'pending',
                'flags': [],
            })
            block_id += 1

    return blocks


def chunk_blocks(blocks: list[dict], chunk_size: int) -> list[list[dict]]:
    chunks = []
    for i in range(0, len(blocks), chunk_size):
        chunks.append(blocks[i:i + chunk_size])
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('events_parsed', type=Path)
    ap.add_argument('outdir', type=Path)
    ap.add_argument('--chunk-size', type=int, default=100)
    ap.add_argument('--prefix', default='chapter')
    ap.add_argument('--filter-quality', action='store_true',
                    help='Skip bubbles yang mostly bytecode (kurang readable)')
    args = ap.parse_args()

    events_parsed = json.loads(args.events_parsed.read_text())
    args.outdir.mkdir(parents=True, exist_ok=True)

    all_blocks = extract_dialog_blocks(events_parsed, args.filter_quality)
    print(f'Extracted {len(all_blocks)} dialog blocks', file=sys.stderr)
    print(f'Filtering: {"ON" if args.filter_quality else "OFF"} (kept readable only)',
          file=sys.stderr)

    chunks = chunk_blocks(all_blocks, args.chunk_size)
    print(f'Splitting into {len(chunks)} chunks of {args.chunk_size} blocks',
          file=sys.stderr)

    width = max(2, len(str(len(chunks))))
    for idx, chunk in enumerate(chunks, start=1):
        ws = {
            'metadata': {
                'source': str(args.events_parsed.name),
                'chunk_index': idx,
                'block_range': [chunk[0]['id'], chunk[-1]['id'] + 1],
                'total_blocks': len(chunk),
            },
            'blocks': chunk,
        }
        fname = f'{args.prefix}_{idx:0{width}d}.json'
        (args.outdir / fname).write_text(
            json.dumps(ws, ensure_ascii=False, indent=2)
        )

    # Index
    index = {
        'source': str(args.events_parsed.name),
        'total_blocks': len(all_blocks),
        'total_chunks': len(chunks),
        'chunk_size': args.chunk_size,
        'filter_quality': args.filter_quality,
        'chunks': [
            {
                'file': f'{args.prefix}_{idx:0{width}d}.json',
                'block_range': [chunk[0]['id'], chunk[-1]['id'] + 1],
                'count': len(chunk),
                'speakers': sorted(set(b['speaker'] for b in chunk if b['speaker'])),
            }
            for idx, chunk in enumerate(chunks, start=1)
        ],
    }
    (args.outdir / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2))

    print(f'\n✅ Wrote {len(chunks)} workspace files + index.json to {args.outdir}/',
          file=sys.stderr)
    print(f'\nWorkflow:', file=sys.stderr)
    print(f'  1. Edit setiap chapter_*.json — fill id_final per block', file=sys.stderr)
    print(f'  2. Atau pakai Gemini: python tools/translate_gemini.py <chunk> <out>',
          file=sys.stderr)
    print(f'  3. Apply: python tools/translate_pipeline.py --translations <merged> ...',
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
