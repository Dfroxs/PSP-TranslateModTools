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
from psp_translate.translate import wiki_ref

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
        byte_length = b.get('byte_length')
        if byte_length is None and b.get('byte_range'):
            byte_length = b['byte_range'][1] - b['byte_range'][0]
        out.append({
            'id': b['id'],
            'en': b['en'],
            'speaker': b.get('speaker'),
            # Real encoded byte budget (== repack's bubble length, terminator
            # included). Used for accurate max_bytes + post-translate compaction.
            'byte_length': byte_length,
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
    """Extract the SYSTEM INSTRUCTION block from the prompt template markdown.

    Accepts both layouts: the body may be wrapped in a ``` code fence or left as
    plain markdown. We grab everything between the "## SYSTEM INSTRUCTION" header
    and the "## USER CONTENT" header, then strip an optional surrounding fence
    and the trailing "---" separator.
    """
    if not PROMPT_TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f'Prompt template not found: {PROMPT_TEMPLATE_PATH}')
    md = PROMPT_TEMPLATE_PATH.read_text(encoding='utf-8')
    m = re.search(r'##\s*SYSTEM INSTRUCTION\s*\n(.*?)\n##\s*USER CONTENT',
                  md, re.DOTALL)
    if not m:
        raise ValueError('Could not extract SYSTEM INSTRUCTION block from template.')
    body = m.group(1).strip()
    # Drop a trailing horizontal-rule separator ("---") if present.
    body = re.sub(r'\n+-{3,}\s*$', '', body).strip()
    # Unwrap an optional ``` / ```lang ... ``` code fence around the whole body.
    fence = re.match(r'^```[^\n]*\n(.*)\n```$', body, re.DOTALL)
    if fence:
        body = fence.group(1).strip()
    if not body:
        raise ValueError('SYSTEM INSTRUCTION block is empty in template.')
    return body


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


# --- Real-encoder budget check + compaction -------------------------------
# The model frequently OVERSHOOTS the byte budget it is given (it cannot count
# bytes precisely). estimate_byte_length is only an approximation; the binding
# constraint at repack time is the REAL encoded length (must be <= the bubble's
# byte_length, terminator included). We therefore re-validate every translation
# against the real encoder and deterministically compact any overflow. If the
# real encoder can't be loaded (e.g. char table missing) we degrade gracefully
# to the estimate so the tool still runs standalone.
try:
    from psp_translate.codec.encode import encode_string as _encode_string, load_table as _load_table
    from psp_translate import paths as _paths

    _CHAR_TABLE_CACHE = None

    def _char_table():
        global _CHAR_TABLE_CACHE
        if _CHAR_TABLE_CACHE is None:
            _CHAR_TABLE_CACHE = _load_table(_paths.CHAR_TABLE)
        return _CHAR_TABLE_CACHE

    def encoded_byte_length(text: str) -> int:
        c2b, c2m, n2b = _char_table()
        b = _encode_string(text, c2b, c2m, n2b)
        if not b.endswith(b'\xfe'):
            b = b + b'\xfe'
        return len(b)

    _REAL_ENCODER = True
except Exception:  # pragma: no cover - fallback path
    _REAL_ENCODER = False

    def encoded_byte_length(text: str) -> int:
        return estimate_byte_length(text)


# Ordered full->short reductions, applied ONLY as needed to fit a tight budget.
# Approved abbreviations first (least lossy), then mild me-prefix stripping,
# then droppable auxiliaries. Meaning is preserved; only verbosity is cut.
_COMPACTION_ABBREV = [
    ('yang', 'yg'), ('dengan', 'dgn'), ('untuk', 'utk'), ('kepada', 'kpd'),
    ('sudah', 'sdh'), ('dalam', 'dlm'), ('tidak', 'tak'), ('tetapi', 'tapi'),
    ('karena', 'krn'), ('daripada', 'drpd'), ('sebelum', 'sblm'),
    ('sesudah', 'ssdh'), ('seperti', 'spt'), ('juga', 'jg'), ('belum', 'blm'),
    ('tentang', 'ttg'), ('sampai', 'smp'),
]
_COMPACTION_MEPREFIX = [
    ('membuat', 'buat'), ('melakukan', 'lakukan'), ('menyelamatkan', 'selamatkan'),
    ('mengalahkan', 'kalahkan'), ('memegang', 'pegang'), ('menolong', 'tolong'),
    ('membunuh', 'bunuh'), ('mengendalikan', 'kendalikan'), ('memperkuat', 'perkuat'),
    ('mendukung', 'dukung'), ('membantu', 'bantu'), ('menjaga', 'jaga'),
]
_COMPACTION_DROP = ['akan', 'adalah', 'telah']


def compact_to_budget(id_text: str, budget: int, en: str) -> tuple[str, bool]:
    """Shrink an overflowing translation to fit `budget` (real encoded bytes).

    Applies reductions in order, ONLY while still over budget, and ONLY when the
    control-code multiset stays identical to `en` (never drops a `<...>` token).
    Returns (possibly-shortened text, fits_budget).
    """
    want = extract_control_codes(en)

    def keeps_codes(s: str) -> bool:
        return extract_control_codes(s) == want

    out = id_text
    for full, short in _COMPACTION_ABBREV + _COMPACTION_MEPREFIX:
        if encoded_byte_length(out) <= budget:
            break
        cand = re.sub(r'(?<![A-Za-z])' + re.escape(full) + r'(?![A-Za-z])', short, out)
        if keeps_codes(cand):
            out = cand
    for word in _COMPACTION_DROP:
        if encoded_byte_length(out) <= budget:
            break
        cand = re.sub(r'(?<![A-Za-z])' + word + r'\s', '', out)
        cand = re.sub(r'  +', ' ', cand)
        if keeps_codes(cand):
            out = cand
    return out, encoded_byte_length(out) <= budget


def build_user_message(batch: list[dict[str, Any]]) -> str:
    """Bikin user message: instruction + JSON array of {id, en, max_bytes, speaker, wiki_ref}."""
    items = []
    any_wiki = False
    for b in batch:
        # Prefer the real bubble byte budget; fall back to the estimate.
        en_bytes = model_budget(b) or estimate_byte_length(model_en(b))
        item = {
            'id': b['id'],
            'en': model_en(b),
            'max_bytes': en_bytes,  # CRITICAL: ID translation must NOT exceed this
        }
        if b.get('speaker'):
            item['speaker'] = b['speaker']
        # Canonical clean English from the FFT wiki script (grounding). The
        # decoded `en` carries control codes + decode noise; `wiki_ref` is the
        # authoritative, noise-free meaning to translate FROM.
        if b.get('wiki_ref'):
            item['wiki_ref'] = b['wiki_ref']
            any_wiki = True
        items.append(item)
    js = json.dumps(items, ensure_ascii=False, indent=2)
    wiki_note = (
        'GROUNDING: Some blocks include a `wiki_ref` field — the official, clean '
        'English of that line from the game script. When present, translate the '
        'MEANING of `wiki_ref` (it is authoritative and free of decode noise), '
        'but keep every control code exactly as it appears in `en`, and still '
        'fit `max_bytes`. Never add anything not in `wiki_ref`/`en`.\n\n'
        if any_wiki else ''
    )
    return (
        'Translate the following dialog blocks EN→ID. Respond with a JSON array '
        'in the same order, same length. Preserve all control codes and proper '
        'nouns per the rules.\n\n'
        f'{wiki_note}'
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


def finalize_translation(b: dict[str, Any], raw_id_text: str) -> tuple[str, list[str]]:
    """Apply abbreviation cleanup + byte-budget compaction + validation.

    Returns (possibly-compacted id_text, flags). Shared by the first pass and
    the control-code retry pass so both go through identical post-processing.

    For split bytecode-glued blocks (`_prefix`/`_tail`), the model only produced
    the tail translation; we reattach the verbatim prefix and validate the FULL
    reconstructed bubble (control codes + full byte budget).
    """
    src = model_en(b)                       # what the model translated (tail or full)
    prefix = b.get('_prefix') or ''
    tail = expand_abbreviations(raw_id_text, src)
    full = prefix + tail
    flags = validate_translation(b['en'], full)   # validate against FULL bubble
    budget = b.get('byte_length')
    if budget and encoded_byte_length(full) > budget:
        tail_budget = budget - (encoded_byte_length(prefix) if prefix else 0)
        tail, fits = compact_to_budget(tail, tail_budget, src)
        full = prefix + tail
        if encoded_byte_length(full) > budget:
            flags = flags + [
                f'overflow_byte_budget:{encoded_byte_length(full) - budget}'
            ]
    return full, flags


def has_control_error(flags: list[str]) -> bool:
    """True if flags include a control-code mismatch (missing/extra)."""
    return any(f.startswith('missing_control_codes')
               or f.startswith('extra_control_codes') for f in flags)


def build_retry_message(batch: list[dict[str, Any]]) -> str:
    """Focused re-translation prompt for blocks whose control codes were dropped.

    Each item lists the EXACT control-code multiset that MUST appear (same count)
    plus the previous wrong attempt, so the model only fixes the code mismatch.
    """
    items = []
    for b in batch:
        required = dict(extract_control_codes(model_en(b)))
        item = {
            'id': b['id'],
            'en': model_en(b),
            'max_bytes': model_budget(b) or estimate_byte_length(model_en(b)),
            'required_control_codes': required,
            'previous_attempt': b.get('_retry_prev', ''),
        }
        if b.get('speaker'):
            item['speaker'] = b['speaker']
        if b.get('wiki_ref'):
            item['wiki_ref'] = b['wiki_ref']
        items.append(item)
    js = json.dumps(items, ensure_ascii=False, indent=2)
    return (
        'Your previous translation DROPPED or ALTERED control codes. Re-translate '
        'these blocks. CRITICAL: `id_text` MUST contain EVERY token in '
        '`required_control_codes` the EXACT number of times shown (e.g. <f8> x2 '
        'means two <f8> in the output), in natural positions, and a <SPEAKER>... '
        'bubble must START with that speaker tag. Keep the meaning of `wiki_ref`/'
        '`en`, fit `max_bytes`, preserve proper nouns. Output ONLY a JSON array '
        '[{"id":N,"id_text":"..."}], same order, same length.\n\n'
        f'{js}'
    )


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


def _is_transient(e: Exception) -> bool:
    """True for transient API failures worth retrying (overload / rate / 5xx)."""
    s = str(e).lower()
    return any(k in s for k in (
        '503', 'unavailable', 'overloaded', '429', 'resource_exhausted',
        'rate limit', '500', 'internal', 'deadline', 'timeout'))


def call_gemini_retry(client, model, system_prompt, user_msg, max_tokens,
                      sleep, tries: int = 4) -> str:
    """call_gemini with exponential backoff on transient errors (503/429/5xx)."""
    for attempt in range(tries):
        try:
            return call_gemini(client, model, system_prompt, user_msg, max_tokens)
        except Exception as e:  # noqa: BLE001
            if attempt < tries - 1 and _is_transient(e):
                wait = max(sleep, 2.0) * (2 ** attempt)
                print(f'  transient API error ({type(e).__name__}); '
                      f'retry {attempt + 1}/{tries - 1} in {wait:.0f}s...',
                      file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def translate_batch(client, model, system_prompt, batch, max_tokens,
                    sleep) -> dict[int, str]:
    """Translate one batch → {id: id_text}, resilient to transient + JSON errors.

    - Transient API errors (503/429/5xx) are retried with backoff.
    - A truncated/invalid JSON response (common when a batch is too large for the
      output-token limit) is recovered by SPLITTING the batch in half and
      translating each half separately — so a big batch degrades gracefully
      instead of dropping every block to 'error'.
    """
    raw = call_gemini_retry(client, model, system_prompt,
                            build_user_message(batch), max_tokens, sleep)
    try:
        parsed = parse_gemini_response(raw)
    except json.JSONDecodeError:
        if len(batch) <= 1:
            raise
        mid = (len(batch) + 1) // 2
        print(f'  JSON parse failed (n={len(batch)}); splitting into '
              f'{mid}+{len(batch) - mid} and retrying', file=sys.stderr)
        out: dict[int, str] = {}
        out.update(translate_batch(client, model, system_prompt,
                                   batch[:mid], max_tokens, sleep))
        time.sleep(sleep)
        out.update(translate_batch(client, model, system_prompt,
                                   batch[mid:], max_tokens, sleep))
        return out
    return {it['id']: it.get('id_text', '') for it in parsed
            if isinstance(it, dict) and 'id' in it}


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
            if b.get('byte_length') is not None:
                entry['byte_length'] = b['byte_length']
            out.append(entry)
        else:
            out.append({
                'id': bid,
                'en': b['en'],
                'id_auto': None,
                'id_final': None,
                'speaker': b.get('speaker'),
                'byte_length': b.get('byte_length'),
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


def split_bytecode_prefix(en: str):
    """For a bytecode-glued bubble, split into (prefix, tail) at the `<db>` mark.

    Some bubbles are mis-parsed: a long executable-bytecode prefix with the real
    renderable dialogue/narration glued on after a `<db>` marker (the bytecode→
    text boundary, e.g. `...<db><SPEAKER>Agrias...` or `...<db><PRAYER>Records...`).
    These fail `looks_like_dialog` (digits dominate) and would otherwise be
    skipped. We keep the prefix BYTE-VERBATIM (it is never sent to the model — the
    encoder roundtrips it exactly) and translate ONLY the tail, then reattach the
    prefix. (This implements the "send Gemini just the English, reassemble after"
    recovery.)

    Returns (prefix, tail) if a recoverable dialogue tail is found, else None.
    """
    idx = en.rfind('<db>')
    if idx == -1:
        return None
    cut = idx + len('<db>')
    prefix, tail = en[:cut], en[cut:]
    if not ('<SPEAKER>' in tail or '<PRAYER>' in tail):
        return None
    if not looks_like_dialog(tail):
        return None
    return prefix, tail


def model_en(b: dict[str, Any]) -> str:
    """Text the model actually translates (the tail, for split bytecode blocks)."""
    return b.get('_tail') or b['en']


def model_budget(b: dict[str, Any]):
    """Byte budget for the model's portion (tail budget for split blocks)."""
    if b.get('_prefix') is not None:
        return b.get('_tail_budget')
    return b.get('byte_length')


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
    recovered = 0
    for b in selected:
        entry = merged[by_id_idx[b['id']]]
        if entry['status'] in ('auto', 'approved', 'skip'):
            continue
        if not looks_like_dialog(b['en']):
            # Recovery: bytecode-glued bubble with real dialogue after a <db>
            # marker — translate only the tail, keep the prefix verbatim.
            sp = split_bytecode_prefix(b['en'])
            if sp:
                prefix, tail = sp
                full_budget = b.get('byte_length')
                pre_len = encoded_byte_length(prefix)
                # Recoverable only if the prefix fits and leaves room for a tail.
                if full_budget and pre_len < full_budget:
                    b['_prefix'], b['_tail'] = prefix, tail
                    b['_tail_budget'] = full_budget - pre_len
                    recovered += 1
                    continue
            entry['status'] = 'skip'
            entry['flags'] = ['non_dialog']
            newly_skipped += 1
    if newly_skipped:
        print(f'Skipping {newly_skipped} non-dialog/garbage blocks (kept as-is).')
        save_output(args.output, build_metadata(args, total, merged), merged)
    if recovered:
        print(f'Recovered {recovered} bytecode-glued block(s): translating dialogue '
              f'tail only, prefix kept verbatim.')

    # Filter to-translate: in range + not yet auto/approved/skip
    to_translate = [
        b for b in selected
        if merged[by_id_idx[b['id']]]['status'] not in ('auto', 'approved', 'skip')
    ]
    skipped = len(selected) - len(to_translate)
    if skipped:
        print(f'Resuming: {skipped} already done/skipped, {len(to_translate)} remaining.')

    # Ground each block against the canonical wiki script: attach `wiki_ref`
    # (clean English) so the model translates noise-free meaning. Loaded once;
    # degrades gracefully (ungrounded) if the script JSON is absent.
    wiki = wiki_ref.load_wiki()
    if wiki:
        grounded = 0
        for b in to_translate:
            w, score = wiki_ref.match_block(model_en(b), wiki)
            if w is not None:
                b['wiki_ref'] = w['en']
                grounded += 1
        print(f'Wiki grounding: {grounded}/{len(to_translate)} blocks matched a '
              f'canonical line ({paths.WIKI_SCRIPT.name}).')
    else:
        print(f'WARNING: wiki script not found ({paths.WIKI_SCRIPT}); '
              'translating WITHOUT grounding.', file=sys.stderr)

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
            by_id_response = translate_batch(
                client, args.model, system_prompt, batch,
                args.max_output_tokens, args.sleep)
        except Exception as e:  # noqa: BLE001
            print(f'  batch failed after retries: {type(e).__name__}: {e}',
                  file=sys.stderr)
            for b in batch:
                idx = by_id_idx[b['id']]
                merged[idx]['status'] = 'error'
                merged[idx]['flags'] = [f'api_error:{type(e).__name__}']
            metadata = build_metadata(args, total, merged)
            save_output(args.output, metadata, merged)
            time.sleep(args.sleep)
            continue

        # First pass: post-process each block (status assigned after retry).
        for b in batch:
            bid = b['id']
            entry = merged[by_id_idx[bid]]
            if bid not in by_id_response:
                entry['flags'] = ['missing_from_response']
                continue
            id_text, flags = finalize_translation(b, by_id_response[bid])
            entry['id_auto'] = id_text
            entry['flags'] = flags

        # Control-code retry: any block whose codes were dropped/altered gets ONE
        # focused re-translation. Directly prevents missing control codes (the
        # assembly pipeline also ABORTs on any that still slip through).
        retry_blocks = [
            b for b in batch
            if merged[by_id_idx[b['id']]]['flags'] != ['missing_from_response']
            and has_control_error(merged[by_id_idx[b['id']]]['flags'])
        ]
        if retry_blocks:
            for b in retry_blocks:
                b['_retry_prev'] = by_id_response.get(b['id'], '')
            print(f'  control-code retry: {len(retry_blocks)} block(s) '
                  f'(ids {", ".join(str(b["id"]) for b in retry_blocks)})')
            time.sleep(args.sleep)  # respect RPM before the extra call
            rmap: dict[int, str] = {}
            try:
                rraw = call_gemini_retry(client, args.model, system_prompt,
                                         build_retry_message(retry_blocks),
                                         args.max_output_tokens, args.sleep)
                rparsed = parse_gemini_response(rraw)
                rmap = {it['id']: it.get('id_text', '') for it in rparsed
                        if isinstance(it, dict) and 'id' in it}
            except Exception as e:  # noqa: BLE001
                print(f'  retry failed ({type(e).__name__}); keeping originals',
                      file=sys.stderr)
            fixed = 0
            for b in retry_blocks:
                if b['id'] not in rmap:
                    continue
                new_text, new_flags = finalize_translation(b, rmap[b['id']])
                # Adopt only if the control-code mismatch is gone (strict win).
                if not has_control_error(new_flags):
                    entry = merged[by_id_idx[b['id']]]
                    entry['id_auto'] = new_text
                    entry['flags'] = new_flags
                    fixed += 1
            print(f'  control-code retry: {fixed}/{len(retry_blocks)} fixed')

        # Finalize status + counts for the whole batch.
        for b in batch:
            entry = merged[by_id_idx[b['id']]]
            if entry['flags'] == ['missing_from_response']:
                entry['status'] = 'error'
                flagged_count += 1
            elif entry['flags']:
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
