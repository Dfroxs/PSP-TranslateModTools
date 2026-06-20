"""Centralized paths for psp_translate.

Single source of truth — no path literals or `sys.path.insert` hacks
elsewhere in the package.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
BUILD = ROOT / "build"
DOCS = ROOT / "docs"
EXTRACTED = ROOT / "extracted"
GAMES = ROOT / "games"
WORKSPACE = ROOT / "workspace"

# Source-of-truth data (versioned)
CHAR_TABLE = DATA / "char_table.json"
FFTPACK_MAP = DATA / "fftpack_event_map.json"
PROPER_NOUNS = DATA / "proper_nouns.json"

# Generated (gitignored, regenerable)
EVENTS_PARSED = BUILD / "events_parsed.json"
TRANS_BUDGET = BUILD / "translation_budget.json"

# Input game files (extracted via psp_modtool)
ORIGINAL_TEST_EVT = EXTRACTED / "FFTPACK_Extracted" / "EVENT" / "TEST.EVT"
ORIGINAL_FFTPACK = EXTRACTED / "PSP_GAME" / "USRDIR" / "fftpack.bin"

PROMPT_TEMPLATE = DOCS / "gemini_prompt_template.md"

# ISO layout
FFTPACK_ISO_OFFSET = 0x02c20000
