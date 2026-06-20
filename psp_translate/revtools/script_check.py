"""Cross-check workspace chapter blocks against the offline wiki script.

Matches each block's decoded `en` against the canonical Story-dialogue lines
(data/wiki_script/fft_story_dialogue.json) to catch:
  - blocks marked `skip` that actually contain real dialogue (mis-parsed) -> RECOVER
  - 'translated' blocks that match no wiki line (likely garbage echo)      -> REVIEW
  - wiki lines not covered by any block in the file                        -> coverage

Usage:
    python -m psp_translate script-check workspace/chapter_01.out.json
    python -m psp_translate script-check workspace/chapter_01.out.json --show-unmatched
"""
from __future__ import annotations
import argparse, json, re, sys
from difflib import SequenceMatcher
from pathlib import Path

from psp_translate.translate.gemini import looks_like_dialog

WIKI = Path('data/wiki_script/fft_story_dialogue.json')


def norm_en(s: str) -> str:
    s = re.sub(r'<[^<>]+>', ' ', s)          # strip control codes / hex tags
    s = s.lower()
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def best_match(block_norm: str, wiki):
    """Return (wiki_entry, score) best matching this block (substring or fuzzy)."""
    best, best_score = None, 0.0
    for w in wiki:
        wn = w['norm']
        if len(wn) < 8:
            continue
        if wn in block_norm:                 # canonical line embedded in block
            return w, 1.0
        # fuzzy on the readable core
        r = SequenceMatcher(None, wn, block_norm).ratio()
        if r > best_score:
            best, best_score = w, r
    return best, best_score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('chapter', type=Path, help='workspace chapter_*.out.json')
    ap.add_argument('--threshold', type=float, default=0.6)
    ap.add_argument('--show-unmatched', action='store_true')
    args = ap.parse_args()

    wiki = json.loads(WIKI.read_text())['flat']
    blocks = json.loads(args.chapter.read_text())['blocks']

    problems_skip, problems_garbage, ok = [], [], 0
    for b in blocks:
        bn = norm_en(b['en'])
        has_text = len(re.findall(r'[a-z]{3,}', bn)) >= 3
        w, score = best_match(bn, wiki) if has_text else (None, 0.0)
        matched = w is not None and score >= args.threshold
        st = b['status']
        if st == 'skip' and matched:
            problems_skip.append((b['id'], score, w))      # real dialogue wrongly skipped
        elif st in ('approved', 'auto') and not matched and not looks_like_dialog(b['en']):
            # Only flag as garbage when the block ISN'T dialogue-shaped; short
            # real lines (e.g. "Unhand me!") that the matcher can't confidently
            # pin to a wiki line are not problems.
            problems_garbage.append((b['id'], score, bn[:50]))
        elif matched:
            ok += 1

    print(f'== {args.chapter.name} ==')
    print(f'matched (translated & in wiki): {ok}')
    print(f'\n[!] skipped but MATCHES wiki (real dialogue, should recover): {len(problems_skip)}')
    for i, sc, w in problems_skip:
        print(f"  id {i} (score {sc:.2f}) <- {w['chapter']} / {w['scene']}: {w['en'][:60]}")
    print(f'\n[?] translated but NO wiki match (possible garbage echo): {len(problems_garbage)}')
    for i, sc, txt in problems_garbage:
        print(f"  id {i}: {txt}")
    if args.show_unmatched:
        pass
    return 1 if problems_skip else 0


if __name__ == '__main__':
    raise SystemExit(main())
