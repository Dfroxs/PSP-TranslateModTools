"""Parse the offline FFT WoTL wiki script (wikitext) into structured JSON.

Source: data/wiki_script/fft_script_raw.wikitext (fetched from the Fandom
MediaWiki API). Extracts the '== Story dialogue ==' section, splits by scene
(==== headers ====), and pulls each '''Speaker''': line entry.

Output: data/wiki_script/fft_story_dialogue.json
  {meta, scenes: [{chapter, scene, lines: [{speaker, en, norm}]}],
   flat: [{chapter, scene, speaker, en, norm}]}

`norm` is the line normalised for matching against decoded `en` in the
workspace JSON (lowercased, punctuation/whitespace collapsed).
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

RAW = Path('data/wiki_script/fft_script_raw.wikitext')
OUT = Path('data/wiki_script/fft_story_dialogue.json')


def normalize(s: str) -> str:
    """Collapse to a matchable key: drop wiki markup, lowercase, strip punctuation."""
    s = re.sub(r"'''?", '', s)            # bold/italic markers
    s = re.sub(r'\[\[([^\]|]+\|)?([^\]]+)\]\]', r'\2', s)  # [[link|text]] -> text
    s = re.sub(r'<[^>]+>', ' ', s)        # html tags
    s = re.sub(r'\{\{[^}]+\}\}', ' ', s)  # templates
    s = s.lower()
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)    # keep alnum+space
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def main() -> int:
    wt = RAW.read_text(encoding='utf-8')
    # Story dialogue section: from '== Story dialogue ==' to next top-level '== X =='
    m = re.search(r'==\s*Story dialogue\s*==', wt)
    if not m:
        print('Story dialogue header not found', file=sys.stderr); return 1
    start = m.end()
    nxt = re.search(r'\n==[^=].*?==\s*\n', wt[start:])
    body = wt[start:start + nxt.start()] if nxt else wt[start:]

    # Linear scan: robust against scene-split edge cases. Track the current
    # chapter (=== header ===) and scene (==== header ====) as we walk lines,
    # appending every '''Speaker''': line entry to the active scene.
    scenes = []
    chapter, scene = 'Prologue', '(intro)'
    cur = {'chapter': chapter, 'scene': scene, 'lines': []}
    hdr = re.compile(r'^(={3,4})\s*(.+?)\s*\1\s*$')
    spk = re.compile(r"'''(.+?)''':\s*(.*)")

    def flush(c):
        if c['lines']:
            scenes.append(c)

    for line in body.splitlines():
        line = line.strip()
        h = hdr.match(line)
        if h:
            if len(h.group(1)) == 3:           # === Chapter ===
                chapter = h.group(2)
            else:                              # ==== Scene ====
                flush(cur)
                scene = h.group(2)
                cur = {'chapter': chapter, 'scene': scene, 'lines': []}
            continue
        mm = spk.match(line)
        if mm:
            speaker, text = mm.group(1).strip(), mm.group(2).strip()
            if text:
                cur['lines'].append({'speaker': speaker, 'en': text,
                                     'norm': normalize(text)})
    flush(cur)

    flat = [{'chapter': s['chapter'], 'scene': s['scene'], **ln}
            for s in scenes for ln in s['lines']]
    OUT.write_text(json.dumps(
        {'meta': {'source': str(RAW), 'scenes': len(scenes), 'lines': len(flat)},
         'scenes': scenes, 'flat': flat}, ensure_ascii=False, indent=2))
    print(f'parsed {len(scenes)} scenes, {len(flat)} dialogue lines -> {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
