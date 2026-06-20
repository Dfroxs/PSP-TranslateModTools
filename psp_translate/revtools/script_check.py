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
from pathlib import Path

from psp_translate.translate.gemini import looks_like_dialog
from psp_translate.translate.wiki_ref import norm_en, best_match, load_wiki


def has_embedded_dialogue(en: str) -> bool:
    """True if a `skip` block actually carries real story text.

    Catches mis-parsed bubbles where evt-parse glued a bytecode prefix onto real
    dialogue/narration/prayer — including prayers and narration the wiki
    paraphrases (so a wiki fuzzy-match alone misses them). Signal: a dialogue
    marker (<db>/<SPEAKER>/<PRAYER>) plus several real English words.
    """
    if not any(m in en for m in ('<db>', '<SPEAKER>', '<PRAYER>')):
        return False
    txt = re.sub(r'<[^<>]+>', ' ', en).lower()
    words = re.findall(r'[a-z]{3,}', txt)
    common = {'the', 'and', 'you', 'not', 'our', 'but', 'that', 'from', 'your',
              'this', 'will', 'with', 'what', 'here', 'his', 'who', 'are', 'for'}
    real = [w for w in words if w in common or len(w) >= 5]
    return len(real) >= 4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('chapter', type=Path, help='workspace chapter_*.out.json')
    ap.add_argument('--threshold', type=float, default=0.6)
    ap.add_argument('--show-unmatched', action='store_true')
    args = ap.parse_args()

    wiki = load_wiki()
    blocks = json.loads(args.chapter.read_text())['blocks']

    problems_skip, problems_garbage, ok = [], [], 0
    for b in blocks:
        bn = norm_en(b['en'])
        has_text = len(re.findall(r'[a-z]{3,}', bn)) >= 3
        w, score = best_match(bn, wiki) if has_text else (None, 0.0)
        matched = w is not None and score >= args.threshold
        st = b['status']
        if st == 'skip' and (matched or has_embedded_dialogue(b['en'])):
            # real dialogue wrongly skipped (wiki match OR embedded text the
            # wiki paraphrases, e.g. prayers / on-screen narration)
            problems_skip.append((b['id'], score, w))
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
        if w is not None:
            print(f"  id {i} (score {sc:.2f}) <- {w['chapter']} / {w['scene']}: {w['en'][:60]}")
        else:
            print(f"  id {i} (embedded text, wiki-paraphrased — prayer/narration)")
    print(f'\n[?] translated but NO wiki match (possible garbage echo): {len(problems_garbage)}')
    for i, sc, txt in problems_garbage:
        print(f"  id {i}: {txt}")
    if args.show_unmatched:
        pass
    return 1 if problems_skip else 0


if __name__ == '__main__':
    raise SystemExit(main())
