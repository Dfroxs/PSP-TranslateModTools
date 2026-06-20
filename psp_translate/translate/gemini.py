"""Auto-translate FFT WoTL dialog blocks (English -> Indonesian) via Gemini.

Pakai:
    python tools/translate_gemini.py <input.txt|.json> <output.json> \\
        [--start N] [--end M] [--batch 20] [--dry-run] [--model gemini-2.5-flash]

Input:
    - Plain text dialog file (mis. tools/TEST_EVT_dialog_only.txt) — blocks
      dipisah blank line.
    - ATAU JSON workspace file dari `translation_workspace.py`.

Output:
    JSON dengan struktur metadata + list of blocks (lihat README task).

Behavior:
    --dry-run    : tunjukkan prompt yang akan dikirim ke Gemini, jangan call API.
    --start/--end: range block global id [start, end). Default: semua.
    --batch N    : jumlah block per API call (default 15).
    Resume       : kalau output file ada, block yang status="auto" / "approved"
                   di-skip (idempotent re-run).

Validation per block hasil translasi:
    - Semua control code `<XX>` di input harus muncul juga di output (same count).
    - Semua proper noun yang ada di input harus muncul di output.
    Kalau gagal -> flag block dengan status="needs_review".

API key:
    Env var GEMINI_API_KEY. Wajib kalau bukan --dry-run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psp_translate import paths

PROMPT_TEMPLATE_PATH = paths.PROMPT_TEMPLATE

# Regex untuk control code <XX> (hex byte tag, juga <SPEAKER>, <PRAYER>, <e0>...)
CONTROL_CODE_RE = re.compile(r'<[A-Za-z0-9]{1,8}>')

# Proper nouns yang HARUS preserve (sub-set untuk validasi cepat).
# Kalau ada di input, harus juga ada di output id_text.
PROPER_NOUNS = [
    # Characters
    'Ramza', 'Delita', 'Ovelia', 'Agrias', 'Gaffgarion', 'Wiegraf',
    'Cúchulainn', 'Tietra', 'Goltanna', 'Larg', 'Miluda', 'Mustadio',
    'Orran', 'Algus', 'Zalbaag', 'Olan', 'Ladd', 'Govis', 'Milleuda',
    'Alma', 'Dycedarg', 'Barbaneth', 'Elmdore', 'Beoulve', 'Lenarrio',
    # Places
    'Ivalice', 'Lionel', 'Mullonde', 'Orbonne', 'Goug', 'Ziekden',
    'Igros', 'Lesalia', 'Riovanes', 'Limberry', 'Bethla', 'Eagrose',
    'Gariland', 'Gallionne', 'Zeltennia', 'Akademy',
    # Items / spells
    'Excalibur', 'Phoenix Down', 'Elixir', 'Hi-Potion', 'Ether',
    'Holy', 'Ultima', 'Meteor',
    # Game terms
    'Brave', 'Faith', 'Zodiac', 'Aurascite', 'Auracite',
    # Org
    'Corpse Brigade', 'Order',
]


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def parse_text_blocks(path: Path) -> list[dict[str, Any]]:
    """Parse plain text dialog -> list of block dicts (id, en, speaker)."""
    text = path.read_text(encoding='utf-8', errors='replace')
    raw_blocks = re.split(r'\n\s*\n', text)
    out: list[dict[str, Any]] = []
    speaker_re = re.compile(r'^<SPEAKER>([^<]+)<')
    for raw in raw_blocks:
        b = raw.strip()
        if not b:
            continue
        if b.startswith('=== Decode'):
            continue
        m = speaker_re.match(b)
        speaker = m.group(1).strip() if m else None
        out.append({'id': len(out), 'en': b, 'speaker': speaker})
    return out


def parse_workspace_json(path: Path) -> list[dict[str, Any]]:
    """Parse workspace JSON -> list of block dicts."""
    data = json.loads(path.read_text(encoding='utf-8'))
    blocks = data.get('blocks', [])
    out = []
    for b in blocks:
        out.append({
            'id': b['id'],
            'en': b['en'],
            'speaker': b.get('speaker'),
        })
    return out


def load_input(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == '.json':
        return parse_workspace_json(path)
    return parse_text_blocks(path)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def load_system_prompt() -> str:
    """Extract SYSTEM INSTRUCTION block dari prompt template markdown."""
    if not PROMPT_TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f'Prompt template not found: {PROMPT_TEMPLATE_PATH}')
    md = PROMPT_TEMPLATE_PATH.read_text(encoding='utf-8')
    # Cari blok di antara "## SYSTEM INSTRUCTION" sampai "## USER CONTENT"
    m = re.search(r'## SYSTEM INSTRUCTION\s*\n+```\s*\n(.*?)\n```\s*\n+---\s*\n+## USER CONTENT',
                  md, re.DOTALL)
    if not m:
        raise ValueError('Could not extract SYSTEM INSTRUCTION block from template.')
    return m.group(1).strip()


def estimate_byte_length(text: str) -> int:
    """Estimasi byte length untuk encoded text (close enough untuk Gemini constraint).

    Heuristik: every char = 1 byte except:
    - `<XX>` hex tag = 1 byte (collapses to single byte)
    - `<SPEAKER>`, `<PRAYER>`, `<e0>` named tag = 1 byte each
    - Multi-byte chars (`,` `—` `ú`) = 2 bytes
    """
    # Strip <XX> and named tags — each becomes 1 byte
    stripped = re.sub(r'<[0-9a-fA-F]{2}>', '?', text)
    stripped = re.sub(r'<[A-Z_][A-Z_0-9]*>', '?', stripped)
    n = len(stripped)
    # Add 1 byte for each multi-byte char
    for ch in (',', '—', 'ú'):
        n += stripped.count(ch)  # additional byte for these
    return n


# Reverse of the approved abbreviations from the prompt. The model sometimes
# abbreviates even when there is room ("yg"/"kpd" where "yang"/"kepada" fit),
# which reads worse. After translation we expand each abbreviation BACK to its
# full word wherever the full form still fits the byte budget — deterministic,
# budget-safe cleanup. ("tak" is intentionally absent: it is a normal standard
# word, not an ugly contraction, so it is left as-is.)
ABBREV_EXPANSIONS: dict[str, str] = {
    'yg': 'yang', 'dgn': 'dengan', 'utk': 'untuk', 'tdk': 'tidak',
    'sdh': 'sudah', 'krn': 'karena', 'dlm': 'dalam', 'kpd': 'kepada',
    'drpd': 'daripada', 'jg': 'juga', 'blm': 'belum', 'org': 'orang',
    'byk': 'banyak', 'spt': 'seperti', 'sblm': 'sebelum', 'ssdh': 'sesudah',
    'bgmn': 'bagaimana', 'ttg': 'tentang', 'smp': 'sampai',
}


def expand_abbreviations(id_text: str, en: str) -> str:
    """Expand abbreviations back to full words where the byte budget allows.

    Budget basis = `estimate_byte_length(en)`, the same `max_bytes` the model is
    told to fit. Each expansion is applied greedily and ONLY if the result still
    fits, so a genuinely budget-tight line keeps its abbreviations. Control codes
    (`<...>`) are never touched (word-boundary matching on letters only).
    """
    budget = estimate_byte_length(en)
    out = id_text
    for ab, full in ABBREV_EXPANSIONS.items():
        pattern = re.compile(r'(?<![A-Za-z])' + re.escape(ab) + r'(?![A-Za-z])')
        if not pattern.search(out):
            continue
        candidate = pattern.sub(full, out)
        if estimate_byte_length(candidate) <= budget:
            out = candidate
    return out


def build_user_message(batch: list[dict[str, Any]]) -> str:
    """Bikin user message: instruction + JSON array of {id, en, max_bytes, speaker}."""
    items = []
    for b in batch:
        en_bytes = estimate_byte_length(b['en'])
        item = {
            'id': b['id'],
            'en': b['en'],
            'max_bytes': en_bytes,  # CRITICAL: ID translation must NOT exceed this
        }
        if b.get('speaker'):
            item['speaker'] = b['speaker']
        items.append(item)
    js = json.dumps(items, ensure_ascii=False, indent=2)
    return (
        'Translate the following dialog blocks EN→ID. Respond with a JSON array '
        'in the same order, same length. Preserve all control codes and proper '
        'nouns per the rules.\n\n'
        'CRITICAL: Each block has a `max_bytes` field. Your `id_text` must NOT '
        'exceed `max_bytes` (estimate: 1 char ≈ 1 byte). First write the FULL, '
        'natural Indonesian (complete subject/pronoun, full words). ONLY if it '
        'overflows `max_bytes`, shorten using the approved abbreviations '
        '(yang→yg, dengan→dgn, untuk→utk, sudah→sdh, dalam→dlm, karena→krn, '
        'kepada→kpd) — and never in a way that changes the meaning. A line that '
        'already fits MUST stay in full words. Do not abbreviate proper nouns '
        'or control codes.\n\n'
        f'{js}'
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def extract_control_codes(text: str) -> Counter:
    return Counter(CONTROL_CODE_RE.findall(text))


def validate_translation(en: str, id_text: str) -> list[str]:
    """Return list of flag strings. Empty list = OK."""
    flags: list[str] = []

    # Control codes — count must match
    en_codes = extract_control_codes(en)
    id_codes = extract_control_codes(id_text)
    if en_codes != id_codes:
        missing = en_codes - id_codes
        extra = id_codes - en_codes
        if missing:
            flags.append(f'missing_control_codes:{dict(missing)}')
        if extra:
            flags.append(f'extra_control_codes:{dict(extra)}')

    # Proper nouns — every PN present in en must be present in id_text
    for pn in PROPER_NOUNS:
        if pn in en and pn not in id_text:
            flags.append(f'missing_proper_noun:{pn}')

    # Empty translation
    if not id_text.strip():
        flags.append('empty_translation')

    return flags


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

def call_gemini(client, model: str, system_prompt: str, user_msg: str,
                max_output_tokens: int = 8192) -> str:
    """Call Gemini and return raw text response."""
    from google.genai import types as gtypes
    response = client.models.generate_content(
        model=model,
        contents=[user_msg],
        config=gtypes.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_output_tokens,
            temperature=0.2,
            response_mime_type='application/json',
        ),
    )
    return response.text or ''


def parse_gemini_response(raw: str) -> list[dict[str, Any]]:
    """Parse Gemini JSON response. Strip code fences if present."""
    txt = raw.strip()
    if txt.startswith('```'):
        # Strip ```json ... ```
        txt = re.sub(r'^```(?:json)?\s*\n', '', txt)
        txt = re.sub(r'\n```\s*$', '', txt)
    return json.loads(txt)


# ---------------------------------------------------------------------------
# Output management
# ---------------------------------------------------------------------------

def load_existing_output(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        print(f'WARNING: existing output {path} not valid JSON, ignoring.',
              file=sys.stderr)
        return None


def merge_blocks(existing: list[dict] | None,
                 new_input_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge: keep existing translations, add new pending entries."""
    by_id: dict[int, dict[str, Any]] = {}
    if existing:
        for b in existing:
            by_id[b['id']] = b

    out: list[dict[str, Any]] = []
    for b in new_input_blocks:
        bid = b['id']
        if bid in by_id:
            # Keep existing, but refresh `en` & `speaker` in case input changed
            entry = by_id[bid]
            entry['en'] = b['en']
            if b.get('speaker') is not None:
                entry['speaker'] = b['speaker']
            out.append(entry)
        else:
            out.append({
                'id': bid,
                'en': b['en'],
                'id_auto': None,
                'id_final': None,
                'speaker': b.get('speaker'),
                'status': 'pending',
                'flags': [],
            })
    return out


def save_output(path: Path, metadata: dict[str, Any], blocks: list[dict]) -> None:
    payload = {'metadata': metadata, 'blocks': blocks}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding='utf-8')


def looks_like_dialog(en: str) -> bool:
    """True kalau `en` adalah teks dialog asli, bukan bytecode/garbage.

    Beberapa bubble yang ke-parse sebenarnya region bytecode (mis.
    `<f1>20o0072<ff><fc>0<f1>20jm0A020...`) — kalau dikirim ke Gemini, output
    JSON-nya rusak dan menjatuhkan SELURUH batch. Blok seperti ini harus
    di-skip (repack mempertahankan byte asli; lihat invariant di CLAUDE.md).

    Heuristik (di-tune dari chapter_01/02): buang semua tag `<...>`, lalu garbage
    kalau hampir tak ada huruf, didominasi digit, atau tidak punya satu pun
    "kata" (run huruf >= 3).
    """
    text = re.sub(r'<[^<>]+>', '', en)
    letters = sum(c.isalpha() for c in text)
    digits = sum(c.isdigit() for c in text)
    words = re.findall(r'[A-Za-z]{3,}', text)
    if letters < 3:
        return False
    if digits > letters:
        return False
    if not words:
        return False
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description='Translate FFT WoTL dialog EN->ID via Gemini.')
    ap.add_argument('input', type=Path, help='Input dialog file (.txt or workspace .json)')
    ap.add_argument('output', type=Path, help='Output JSON path')
    ap.add_argument('--start', type=int, default=0, help='Start block id (inclusive)')
    ap.add_argument('--end', type=int, default=None, help='End block id (exclusive)')
    ap.add_argument('--batch', type=int, default=15, help='Blocks per API call (default 15)')
    ap.add_argument('--model', default='gemini-2.5-flash', help='Gemini model name')
    ap.add_argument('--dry-run', action='store_true',
                    help='Show prompt without calling API')
    ap.add_argument('--sleep', type=float, default=4.5,
                    help='Sleep seconds between batches (rate limit; default 4.5s ~ 13 RPM)')
    ap.add_argument('--max-output-tokens', type=int, default=8192)
    args = ap.parse_args()

    if not args.input.is_file():
        print(f'ERROR: input file not found: {args.input}', file=sys.stderr)
        return 1

    # Load system prompt
    try:
        system_prompt = load_system_prompt()
    except (FileNotFoundError, ValueError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1

    # Parse input
    all_blocks = load_input(args.input)
    total = len(all_blocks)
    print(f'Loaded {total} blocks from {args.input}.')

    # Apply range. Block ids are GLOBAL (a chapter chunk may span e.g.
    # 299..481), so the default end must be max(id)+1 — not the block COUNT,
    # which would wrongly exclude every block whose id >= count.
    if args.end is not None:
        end = args.end
    else:
        end = (max(b['id'] for b in all_blocks) + 1) if all_blocks else 0
    selected = [b for b in all_blocks if args.start <= b['id'] < end]
    if not selected:
        print(f'No blocks in range [{args.start}, {end}).', file=sys.stderr)
        return 1
    print(f'Processing {len(selected)} blocks in range [{args.start}, {end}).')

    # Resume: load existing output
    existing_payload = load_existing_output(args.output)
    existing_blocks = existing_payload['blocks'] if existing_payload else None
    merged = merge_blocks(existing_blocks, all_blocks)

    by_id_idx: dict[int, int] = {b['id']: i for i, b in enumerate(merged)}

    # Mark non-dialog/garbage blocks as 'skip' so they are never sent to the
    # API (they corrupt the batch's JSON) and never retried on resume. repack
    # leaves their original bytes intact.
    newly_skipped = 0
    for b in selected:
        entry = merged[by_id_idx[b['id']]]
        if entry['status'] in ('auto', 'approved', 'skip'):
            continue
        if not looks_like_dialog(b['en']):
            entry['status'] = 'skip'
            entry['flags'] = ['non_dialog']
            newly_skipped += 1
    if newly_skipped:
        print(f'Skipping {newly_skipped} non-dialog/garbage blocks (kept as-is).')
        save_output(args.output, build_metadata(args, total, merged), merged)

    # Filter to-translate: in range + not yet auto/approved/skip
    to_translate = [
        b for b in selected
        if merged[by_id_idx[b['id']]]['status'] not in ('auto', 'approved', 'skip')
    ]
    skipped = len(selected) - len(to_translate)
    if skipped:
        print(f'Resuming: {skipped} already done/skipped, {len(to_translate)} remaining.')

    if not to_translate and not args.dry_run:
        print('Nothing to translate. Exiting.')
        return 0

    # API key check (kecuali dry-run)
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    client = None
    if not args.dry_run:
        if not api_key:
            print('ERROR: GEMINI_API_KEY env var not set. Set it or use --dry-run.',
                  file=sys.stderr)
            return 2
        from google import genai
        client = genai.Client(api_key=api_key)

    # Process in batches
    batch_size = max(1, args.batch)
    translated_count = 0
    flagged_count = 0
    n_batches = (len(to_translate) + batch_size - 1) // batch_size

    for batch_idx in range(n_batches):
        batch = to_translate[batch_idx * batch_size:(batch_idx + 1) * batch_size]
        user_msg = build_user_message(batch)

        ids_in_batch = [b['id'] for b in batch]
        print(f'\n--- Batch {batch_idx + 1}/{n_batches} '
              f'(ids {ids_in_batch[0]}..{ids_in_batch[-1]}, n={len(batch)}) ---')

        if args.dry_run:
            print('\n[DRY-RUN] SYSTEM INSTRUCTION (first 800 chars):')
            print(system_prompt[:800] + ('...' if len(system_prompt) > 800 else ''))
            print(f'\n[DRY-RUN] SYSTEM INSTRUCTION length: {len(system_prompt)} chars')
            print('\n[DRY-RUN] USER MESSAGE:')
            print(user_msg)
            print('\n[DRY-RUN] No API call made.')
            # In dry-run, only show first batch fully then continue counting
            if batch_idx == 0 and n_batches > 1:
                print(f'\n[DRY-RUN] (suppressing {n_batches - 1} further batch previews)')
                break
            continue

        try:
            raw = call_gemini(client, args.model, system_prompt, user_msg,
                              args.max_output_tokens)
        except Exception as e:  # noqa: BLE001
            print(f'  API error: {e}', file=sys.stderr)
            for b in batch:
                idx = by_id_idx[b['id']]
                merged[idx]['status'] = 'error'
                merged[idx]['flags'] = [f'api_error:{type(e).__name__}']
            # Save partial progress
            metadata = build_metadata(args, total, merged)
            save_output(args.output, metadata, merged)
            time.sleep(args.sleep)
            continue

        try:
            parsed = parse_gemini_response(raw)
        except json.JSONDecodeError as e:
            print(f'  Failed to parse JSON response: {e}', file=sys.stderr)
            print(f'  Raw response (first 500): {raw[:500]}', file=sys.stderr)
            for b in batch:
                idx = by_id_idx[b['id']]
                merged[idx]['status'] = 'error'
                merged[idx]['flags'] = ['invalid_json_response']
            metadata = build_metadata(args, total, merged)
            save_output(args.output, metadata, merged)
            time.sleep(args.sleep)
            continue

        # Build id -> id_text map
        by_id_response = {item['id']: item.get('id_text', '') for item in parsed
                          if isinstance(item, dict) and 'id' in item}

        for b in batch:
            bid = b['id']
            idx = by_id_idx[bid]
            entry = merged[idx]
            if bid not in by_id_response:
                entry['status'] = 'error'
                entry['flags'] = ['missing_from_response']
                flagged_count += 1
                continue
            id_text = by_id_response[bid]
            id_text = expand_abbreviations(id_text, b['en'])
            flags = validate_translation(b['en'], id_text)
            entry['id_auto'] = id_text
            entry['flags'] = flags
            if flags:
                entry['status'] = 'needs_review'
                flagged_count += 1
            else:
                entry['status'] = 'auto'
                translated_count += 1

        # Save after each batch (resumable)
        metadata = build_metadata(args, total, merged)
        save_output(args.output, metadata, merged)
        print(f'  -> saved {args.output} ({translated_count} ok, {flagged_count} flagged so far)')

        # Rate-limit pause (skip after last batch)
        if batch_idx < n_batches - 1:
            time.sleep(args.sleep)

    if args.dry_run:
        print('\nDry-run complete.')
        return 0

    print('\n=== Summary ===')
    print(f'  Total blocks in output: {len(merged)}')
    print(f'  Translated OK this run: {translated_count}')
    print(f'  Flagged for review:     {flagged_count}')
    print(f'  Output: {args.output}')
    return 0


def build_metadata(args: argparse.Namespace, total: int,
                   merged: list[dict]) -> dict[str, Any]:
    status_counts = Counter(b['status'] for b in merged)
    return {
        'source': str(args.input.name),
        'model': args.model,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_blocks': total,
        'translated': status_counts.get('auto', 0),
        'flagged': status_counts.get('needs_review', 0),
        'errors': status_counts.get('error', 0),
        'pending': status_counts.get('pending', 0),
        'approved': status_counts.get('approved', 0),
        'skipped': status_counts.get('skip', 0),
    }


if __name__ == '__main__':
    sys.exit(main())
