"""Auto-apply reviewed proper-noun precedents to a chapter's needs_review blocks.

After `psp-translate gemini`, many `needs_review` blocks are flagged only because
a localized proper noun differs from the English one. We've made standing
decisions (chapter 01-02 review):

  - `Order`          -> "Ordo"          (localize; accept)
  - `Corpse Brigade` -> "Pasukan Mayat" (localize; normalize text + accept)
  - `Akademy`        -> keep English     (institution name; "Akademi" -> "Akademy")

This tool applies those precedents to `id_final`, clears the precedent-only
flags, and APPROVES blocks whose remaining flags are clean — so human review
only has to deal with byte overflow + genuinely new proper nouns. Every change
is re-validated against the real encoder (byte budget) and control-code multiset
before approving; nothing is approved that would overflow or drop a `<...>`.

Usage:
    psp-translate review-apply workspace/chapter_03.out.json
    psp-translate review-apply workspace/            # all chapter_*.out.json
    psp-translate review-apply workspace/chapter_03.out.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from psp_translate.translate.gemini import (
    validate_translation, encoded_byte_length,
)

# Proper nouns we have DECIDED to localize/keep — a `missing_proper_noun:<X>`
# flag for these is an accepted style call, not an error.
ACCEPTED_PRECEDENT = {'Order', 'Corpse Brigade', 'Akademy'}


def apply_precedents(id_text: str) -> str:
    """Normalize localized proper nouns to the agreed forms."""
    out = id_text.replace('Brigade Mayat', 'Pasukan Mayat')   # Corpse Brigade
    out = re.sub(r'(?<![A-Za-z])Akademi(?![A-Za-z])', 'Akademy', out)  # keep English
    return out


def _remaining_flags(en: str, cand: str, budget) -> list[str]:
    """Flags after applying precedents: control codes + overflow + NEW proper nouns."""
    flags = [
        f for f in validate_translation(en, cand)
        if not (f.startswith('missing_proper_noun:')
                and f.split(':', 1)[1] in ACCEPTED_PRECEDENT)
    ]
    if budget and encoded_byte_length(cand) > budget:
        flags.append(f'overflow_byte_budget:{encoded_byte_length(cand) - budget}')
    return flags


def process_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Returns (approved_count, still_needs_review_count) for one chapter file."""
    doc = json.loads(path.read_text(encoding='utf-8'))
    approved = still = 0
    for b in doc['blocks']:
        if b.get('status') != 'needs_review':
            continue
        base = b.get('id_final') or b.get('id_auto') or ''
        cand = apply_precedents(base)
        remaining = _remaining_flags(b['en'], cand, b.get('byte_length'))
        b['id_final'] = cand
        if not remaining:
            b['status'] = 'approved'
            b['flags'] = []
            approved += 1
        else:
            b['flags'] = remaining
            still += 1
    if not dry_run:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    print(f'{path.name}: +{approved} approved by precedent, {still} still need '
          f'review (overflow / new proper nouns){" [dry-run]" if dry_run else ""}')
    return approved, still


def main() -> int:
    ap = argparse.ArgumentParser(
        description='Auto-apply proper-noun precedents to needs_review blocks.')
    ap.add_argument('path', type=Path,
                    help='chapter_*.out.json file, or a directory of them')
    ap.add_argument('--dry-run', action='store_true',
                    help='Report changes without writing')
    args = ap.parse_args()

    if args.path.is_dir():
        files = sorted(args.path.glob('chapter_*.out.json'))
    elif args.path.is_file():
        files = [args.path]
    else:
        print(f'ERROR: not found: {args.path}', file=sys.stderr)
        return 1
    if not files:
        print('No chapter_*.out.json found.', file=sys.stderr)
        return 1

    tot_a = tot_s = 0
    for f in files:
        a, s = process_file(f, args.dry_run)
        tot_a += a; tot_s += s
    if len(files) > 1:
        print(f'\nTotal: +{tot_a} approved by precedent, {tot_s} still need review.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
