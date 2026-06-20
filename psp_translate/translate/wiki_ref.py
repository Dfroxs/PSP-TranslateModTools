"""Ground decoded dialogue blocks against the canonical FFT WoTL wiki script.

The decoded `en` of a workspace block carries control codes and decode noise
(stray digit glyphs, mis-parsed bytecode). The Final Fantasy Wiki story script
(`data/wiki_script/fft_story_dialogue.json`, produced by `wiki_parse.py`) holds
the SAME lines in clean canonical English. Matching a block to its wiki line
gives us an authoritative, noise-free meaning to feed the translator — which
both anti-hallucinates and steadies the EN→ID output.

This module is the single home for the normalisation + matching helpers so that
both the translator (`gemini.py`) and the QA checker (`script_check.py`) share
one implementation (no duplicated `norm_en` / `best_match`).
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from psp_translate import paths

# Minimum normalised length of a wiki line we will try to match against. Very
# short lines ("Ramza!", "What?") are ambiguous and would mis-anchor blocks.
_MIN_WIKI_LEN = 8
# Default fuzzy-ratio threshold for accepting a match.
DEFAULT_THRESHOLD = 0.6


def norm_en(s: str) -> str:
    """Normalise text to a matchable key: drop control codes, lowercase, alnum+space."""
    s = re.sub(r'<[^<>]+>', ' ', s)           # strip control codes / hex tags
    s = s.lower()
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)        # keep alnum + space only
    return re.sub(r'\s+', ' ', s).strip()


def load_wiki(path=None) -> list[dict[str, Any]]:
    """Load the flat list of canonical lines from the wiki script JSON.

    Returns [] (with a stderr warning handled by the caller) if the file is
    missing, so the translator can degrade gracefully to ungrounded mode.
    """
    p = path or paths.WIKI_SCRIPT
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding='utf-8'))
    return data.get('flat', [])


def _candidates(wiki: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [(w['norm'], w) for w in wiki if len(w.get('norm', '')) >= _MIN_WIKI_LEN]


def best_match(block_norm: str, wiki: list[dict[str, Any]]):
    """Return (wiki_entry, score) best matching this normalised block.

    A canonical line fully embedded in the block scores 1.0 (exact substring);
    otherwise the best `SequenceMatcher` ratio over all candidates is returned.
    (block_norm, []) -> (None, 0.0).
    """
    best, best_score = None, 0.0
    for wn, w in _candidates(wiki):
        if wn in block_norm:                  # canonical line embedded in block
            return w, 1.0
        r = SequenceMatcher(None, wn, block_norm).ratio()
        if r > best_score:
            best, best_score = w, r
    return best, best_score


def match_block(en: str, wiki: list[dict[str, Any]],
                threshold: float = DEFAULT_THRESHOLD):
    """Best canonical wiki entry for a block's raw `en`, or None below threshold.

    Requires the block to carry at least a few real words (>=3 letter-runs) so
    pure-bytecode garbage never anchors to a wiki line.
    """
    bn = norm_en(en)
    if len(re.findall(r'[a-z]{3,}', bn)) < 3:
        return None, 0.0
    w, score = best_match(bn, wiki)
    if w is not None and score >= threshold:
        return w, score
    return None, score
