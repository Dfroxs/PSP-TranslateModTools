"""Split TEST_EVT_dialog_only.txt jadi workspace JSON chunks per ~100 blocks.

Tiap workspace chunk kompatibel sebagai input untuk `translate_gemini.py`.

Pakai:
    python tools/translation_workspace.py <dialog_only.txt> <workspace_dir>
    python tools/translation_workspace.py tools/TEST_EVT_dialog_only.txt workspace/

Format output (per chunk):
    workspace/chapter_01.json
    workspace/chapter_02.json
    ...

Tiap file punya struktur:
    {
        "metadata": {
            "source": "TEST_EVT_dialog_only.txt",
            "chunk_index": 1,
            "block_range": [0, 100],
            "total_blocks": 100
        },
        "blocks": [
            {"id": 0, "en": "...", "speaker": "Knight", "id_auto": null,
             "id_final": null, "status": "pending", "flags": []},
            ...
        ]
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CHUNK_SIZE_DEFAULT = 100

# Regex untuk extract speaker dari awal block (mis. "<SPEAKER>Knight<f8><e3>...")
SPEAKER_RE = re.compile(r'^<SPEAKER>([^<]+)<')


def parse_dialog_file(path: Path) -> list[str]:
    """Split file ke dialog blocks. Block dipisah oleh blank line(s).

    Header line (mis. "=== Decode @0x000000 ...") di-skip.
    """
    text = path.read_text(encoding='utf-8', errors='replace')
    # Split di blank line(s)
    raw_blocks = re.split(r'\n\s*\n', text)
    blocks = []
    for raw in raw_blocks:
        b = raw.strip()
        if not b:
            continue
        # Skip header decoration lines
        if b.startswith('===') and b.endswith('==='):
            continue
        # Skip jika cuma single header-like
        if b.startswith('=== Decode'):
            continue
        blocks.append(b)
    return blocks


def detect_speaker(block: str) -> str | None:
    """Extract speaker name dari block, kalau ada."""
    m = SPEAKER_RE.match(block)
    if m:
        return m.group(1).strip()
    return None


def chunk_blocks(blocks: list[str], chunk_size: int) -> list[list[tuple[int, str]]]:
    """Bagi blocks ke list of (global_id, text). Tiap chunk = list of tuples."""
    chunks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for i, blk in enumerate(blocks):
        current.append((i, blk))
        if len(current) >= chunk_size:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def build_workspace_chunk(chunk_idx: int, items: list[tuple[int, str]],
                         source_name: str) -> dict:
    """Bikin dict workspace untuk satu chunk."""
    first_id = items[0][0]
    last_id = items[-1][0]
    block_entries = []
    for gid, text in items:
        block_entries.append({
            'id': gid,
            'en': text,
            'speaker': detect_speaker(text),
            'id_auto': None,
            'id_final': None,
            'status': 'pending',
            'flags': [],
        })
    return {
        'metadata': {
            'source': source_name,
            'chunk_index': chunk_idx,
            'block_range': [first_id, last_id + 1],  # half-open [start, end)
            'total_blocks': len(items),
        },
        'blocks': block_entries,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='Split dialog into workspace chunks.')
    ap.add_argument('input', type=Path, help='Input dialog file (TEST_EVT_dialog_only.txt)')
    ap.add_argument('outdir', type=Path, help='Output workspace directory')
    ap.add_argument('--chunk-size', type=int, default=CHUNK_SIZE_DEFAULT,
                    help=f'Blocks per chunk (default {CHUNK_SIZE_DEFAULT})')
    ap.add_argument('--prefix', default='chapter',
                    help='Filename prefix (default "chapter")')
    args = ap.parse_args()

    if not args.input.is_file():
        print(f'ERROR: input file not found: {args.input}', file=sys.stderr)
        return 1

    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f'Reading {args.input}...')
    blocks = parse_dialog_file(args.input)
    print(f'Parsed {len(blocks)} dialog blocks.')

    chunks = chunk_blocks(blocks, args.chunk_size)
    print(f'Splitting into {len(chunks)} chunks of ~{args.chunk_size} blocks each.')

    width = max(2, len(str(len(chunks))))
    for idx, items in enumerate(chunks, start=1):
        ws = build_workspace_chunk(idx, items, args.input.name)
        fname = f'{args.prefix}_{idx:0{width}d}.json'
        out_path = args.outdir / fname
        out_path.write_text(json.dumps(ws, ensure_ascii=False, indent=2),
                            encoding='utf-8')

    # Top-level index file
    index = {
        'source': args.input.name,
        'total_blocks': len(blocks),
        'total_chunks': len(chunks),
        'chunk_size': args.chunk_size,
        'chunks': [
            {
                'file': f'{args.prefix}_{idx:0{width}d}.json',
                'block_range': [items[0][0], items[-1][0] + 1],
                'count': len(items),
            }
            for idx, items in enumerate(chunks, start=1)
        ],
    }
    (args.outdir / 'index.json').write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'Done. Wrote {len(chunks)} chunk files + index.json to {args.outdir}/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
