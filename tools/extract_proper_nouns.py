"""Extract daftar proper nouns dari WORLD.LZW dan OPEN.LZW.

Output: tools/proper_nouns.json — list nama yang TIDAK BOLEH ditranslate.
Bisa di-feed ke `translate_gemini.py` sebagai validator list.

Berdasarkan struktur WORLD.LZW:
  entry[6]  = job names
  entry[7]  = weapon names
  entry[8]  = character names
  entry[9]  = character names (duplicate)
  entry[12] = side quest titles
  entry[14] = spell names
  entry[18] = place names
  entry[21] = map location names
  entry[22] = battle commands
  entry[25] = quest names

Pakai:
    python tools/extract_proper_nouns.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path('/Users/dfroxs/Playground/Python/PspModTools')

# Mapping entry index ke kategori (dari hasil eksplorasi)
WORLD_CATEGORIES = {
    6: 'jobs',
    7: 'weapons',
    8: 'characters',
    # 9: duplicate of 8, skip
    12: 'sidequests',
    14: 'spells',
    15: 'currency_zodiac',
    16: 'chronicles',
    18: 'places',
    21: 'map_locations',
    22: 'battle_commands',
    23: 'rumors',
    25: 'quests',
    26: 'quest_ships',
    27: 'shrines',
    28: 'plates',
    29: 'apprentices',
    31: 'quest_descriptions',
}


def clean_string(s: str) -> str:
    """Bersihkan dari control codes untuk dapat plain text."""
    s = re.sub(r'<[0-9a-f]{2}>', '', s)
    s = s.replace('<f8>', ' ').replace('<fa>', '').replace('<SPEAKER>', '')
    s = s.replace('<PRAYER>', '').replace('<e3>', '').replace('<e0>', '')
    return s.strip()


def is_valid_proper_noun(s: str) -> bool:
    """Filter: bukan string kosong, panjang reasonable, mostly alphabetic."""
    if not s or len(s) < 2 or len(s) > 80:
        return False
    letters = sum(c.isalpha() for c in s)
    if letters / len(s) < 0.5:
        return False
    return True


def main():
    world = json.loads((ROOT / 'tools' / 'lzw_WORLD.json').read_text())

    nouns_by_category: dict[str, set[str]] = {}
    for entry in world['entries']:
        idx = entry['index']
        if idx not in WORLD_CATEGORIES:
            continue
        category = WORLD_CATEGORIES[idx]
        nouns_by_category.setdefault(category, set())
        for sub in entry.get('sub_strings', []) or []:
            clean = clean_string(sub)
            if is_valid_proper_noun(clean):
                nouns_by_category[category].add(clean)

    # Convert sets ke sorted list
    result = {
        'description': 'Proper nouns yang TIDAK BOLEH ditranslate. Diekstrak dari WORLD.LZW.',
        'source': 'WORLD.LZW (extracted via lzw_extract.py)',
        'categories': {
            cat: sorted(names) for cat, names in nouns_by_category.items()
        },
        'all_unique': sorted(set().union(*nouns_by_category.values())),
    }

    out = ROOT / 'tools' / 'proper_nouns.json'
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    print(f'Saved: {out}')
    print(f'Total unique proper nouns: {len(result["all_unique"])}')
    print()
    print('Per kategori:')
    for cat, names in sorted(result['categories'].items()):
        print(f'  {cat:25s}: {len(names):>4d} terms')
    print()
    print('=== Sample per kategori (5 first) ===')
    for cat, names in sorted(result['categories'].items()):
        sample = ', '.join(repr(n) for n in names[:5])
        print(f'  {cat:25s}: {sample}')


if __name__ == '__main__':
    main()
