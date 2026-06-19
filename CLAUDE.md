# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Two layers:

1. **`psp_modtool/`** — generic Python CLI to extract, scan, translate, and repack PSP ISO files (ISO 9660 / UMD), aimed at game localization. Pure stdlib, Python ≥ 3.8.
2. **`tools/`** — game-specific reverse engineering & translation tools for **Final Fantasy Tactics: The War of the Lions (PSP)**. Custom decoder, font analyzer, character table builder. Pure stdlib.

Active focus: EN → ID translation of FFT WoTL. See `TODO_PLAN.md` for roadmap and `DocumentOfComunity.md` for community research & internal reverse engineering findings.

## Commands

### Generic ISO pipeline (psp_modtool)

```bash
pip install -e .
python main.py <subcommand> ...
psp-modtool   <subcommand> ...
```

Subcommands (see `psp_modtool/cli.py`):

- `extract <iso> <out_dir>` — unpack ISO into a folder
- `scan <folder> <strings.json> [--min-len N]` — produce translation JSON
- `apply <folder> <strings.json>` — write `translation` values back; creates `.bak`
- `repack <folder> <out.iso>` — rebuild ISO from folder
- `all <iso> <workdir>` — interactive full pipeline

### FFT WoTL tools (tools/)

**Translation pipeline (end-to-end)**:
```bash
# Single-command: translations → modified ISO
python tools/translate_pipeline.py \
    --translations <translations.json or workspace_dir/> \
    --original-iso "games/FFT WoTL.iso" \
    --output-iso /tmp/FFT_ID.iso

# Build translation workspace (45 chunks of 100 blocks each)
python tools/build_workspace.py tools/events_parsed.json workspace/ --filter-quality

# Gemini auto-translate (needs GEMINI_API_KEY env var)
python tools/translate_gemini.py workspace/chapter_01.json out.json --end 10
```

**Reverse engineering tools**:
```bash
# Heuristic byte stats for any binary
python tools/explore.py <folder-or-file> [--min-len N]

# Render FONT.BIN to PGM (10x14 px @ 2bpp confirmed format)
python tools/font_render.py <FONT.BIN> <out.pgm> [--cols 32] [--scale 4]

# Manage character mapping table
python tools/char_table.py init <out.json>
python tools/char_table.py dump <font.bin> <table.json> <out.txt>
python tools/char_table.py set <table.json> <index> <char>
python tools/char_table.py stats <table.json>

# Decode TEST.EVT (or similar FFT files) to readable English
python tools/decode_evt.py <file.evt> tools/char_table.json [--offset 0x5800] [--length 1024]
python tools/decode_evt.py <file.evt> tools/char_table.json --search "Father"
python tools/decode_evt.py <file.evt> tools/char_table.json --full  # decode entire file

# Parse TEST.EVT structure (231 event chunks, 24K bubbles)
python tools/evt_header.py extracted/.../TEST.EVT --output tools/evt_structure.json
python tools/evt_parser.py extracted/.../TEST.EVT tools/evt_structure.json --output tools/events_parsed.json

# Extract content from plain-text .LZW files (WORLD/OPEN/ATCHELP)
python tools/lzw_extract.py extracted/.../WORLD.LZW tools/char_table.json --output out.json

# Generate per-bubble byte budget (translator constraint reference)
python tools/translation_budget.py extracted/.../TEST.EVT tools/events_parsed.json tools/char_table.json --output tools/translation_budget.json
```

**Encoder & repack tools** (Phase 5+6):
```bash
# Encode text → bytes (lossless, verified roundtrip)
python tools/encode_evt.py <input.txt> tools/char_table.json [--output out.bin]

# Apply translations to TEST.EVT (in-place substitution)
python tools/repack_evt.py extracted/.../TEST.EVT tools/events_parsed.json <translations.json> tools/char_table.json --output modified.evt [--allow-stretch] [--allow-truncate]

# Patch fftpack.bin with modified files
python tools/repack_fftpack.py --fftpack extracted/.../fftpack.bin --map tools/fftpack_event_map.json --substitute TEST.EVT:modified.evt --output modified_fftpack.bin

# Patch ISO directly (size-preserving, no full rebuild)
python tools/patch_iso.py --iso "FFT.iso" --substitute fftpack.bin:modified_fftpack.bin:0x02c20000 --output FFT_ID.iso
```

No test suite, linter, or build script defined.

## Architecture

### psp_modtool (generic ISO pipeline)

Entry: `main.py` → `psp_modtool.cli.main` → `psp_modtool.core` functions re-exported in `core/__init__.py`.

Pipeline stages (each is a function and a CLI subcommand):

1. `core/extractor.py :: extract_iso` — reads PVD + walks directory records via `core/iso9660.py` and writes files to disk.
2. `core/scanner.py :: scan_folder` — classifies files by extension (`utils/constants.py`: `PLAIN_TEXT_EXTENSIONS`, `BINARY_SCAN_EXTENSIONS`, `BINARY_SKIP_EXTENSIONS`) and extracts strings using `utils/text_detect.py`.
3. `core/translator.py :: apply_translations` — patches files in place using `(offset, original, translation)` tuples. **Hard constraint**: for binary files, translated bytes are truncated/padded to the original length so internal offsets/pointers don't shift. Plain-text files are rewritten line-based. A `.bak` is created before mutation.
4. `core/repacker.py :: repack_iso` — rebuilds a minimal ISO 9660 image (System Area + PVD + VDST + root dir + file data) using `iso9660.build_pvd`, `build_vdst`, `write_dir_record`.
5. `core/pipeline.py :: run_all` — chains the above with an interactive pause between scan and apply.

Shared low-level ISO logic lives in `core/iso9660.py`. ISO layout constants (`SECTOR_SIZE=2048`, `PVD_SECTOR=16`, etc.) are in `utils/constants.py` — don't hardcode elsewhere. `utils/logger.py` provides colored terminal output; `utils/text_detect.py` holds ASCII heuristics.

### FFT WoTL tooling (tools/)

The generic scanner CANNOT find dialog in FFT WoTL because text is custom-encoded (not plain ASCII). A separate stack lives in `tools/`:

- `tools/explore.py` — byte-level heuristic analyzer (printable %, top-N bytes, ASCII runs, format hints). Used to characterize unknown binary files.
- `tools/font_render.py` — renders `FONT.BIN` as PGM grid. Format known: **10×14 px, 2bpp, MSB first, 35 bytes/glyph, 2223 glyphs**.
- `tools/char_table.py` — CLI to build & maintain `char_table.json`.
- `tools/char_table.json` — mapping `byte → Unicode char` for FFT WoTL custom encoding. Currently 62 single-byte (digit + A-Z + a-z) + punctuation + multi-byte sequences.
- `tools/decode_evt.py` — decodes `TEST.EVT` and similar files using `char_table.json`. Handles single-byte, multi-byte sequences, control codes, padding skip, search mode.

Data flow for FFT WoTL:

```
ISO → psp_modtool.extract → extracted/FFTPACK_Extracted/EVENT/
                                            │
                            ┌───────────────┼─────────────┐
                            ▼               ▼             ▼
                       FONT.BIN        TEST.EVT       *.LZW
                            │               │             │
                  font_render.py    decode_evt.py    (TODO: lzw_codec)
                            │               │
                            └──► char_table.json ◄┘
                                       │
                                  TEST_EVT_dialog_only.txt
                                  (8203 readable dialog blocks)
```

### FFT WoTL byte encoding (key facts for editing the table/decoder)

Single-byte mappings in `char_table.json`:

- `0x00-0x09` = digit `0-9`
- `0x0A-0x23` = `A-Z` (uppercase)
- `0x24-0x3D` = `a-z` (lowercase)
- `0x3E` = `!`, `0x40` = `?`, `0x5F` = `.`, `0x93` = `'`, `0x95` = ` ` (space)
- `0xFE` = end-of-string / line break
- `0xF8` = soft line break within dialog bubble
- `0xE0` = player name placeholder (Ramza by default)

Multi-byte:

- `0xDA 0x74` = `,` (comma)
- `0xD1 0x1D` = `-` (hyphen)
- `0xE3 0x08` = speaker tag start prefix
- `0xE2 0x02` = paragraph/stanza start (used in opening prayer)

**Caveat**: `0xD1` appears 210K times in TEST.EVT, but mostly in the file header / pointer table (offset 0x0000–0x5800), where it functions as bytecode opcode — not as text. In the dialog region (≥ 0x58C0), `0xD1` is rare and acts as a multi-byte prefix.

## Domain notes

- Shift-JIS / non-ASCII encodings (Japanese games) are not handled by the generic pipeline.
- Custom `.pak`/`.arc` formats vary per game; the generic scanner only finds raw ASCII runs.
- FFT WoTL uses a **custom 2bpp anti-aliased font + custom byte encoding + multi-byte sequences** — the generic `psp-modtool scan` does not work; use the `tools/` stack instead.
- **Hard constraint** for any future encoder: text length must not exceed the original (or pointer table must be rewritten). See `TODO_PLAN.md` Fase 5 for the encoder strategy.
- **Repack bubble invariant (CRITICAL — `tools/repack_evt.py`)**: a dialog bubble
  is delimited by a single `0xFE` terminator at `byte_end-1`. When substituting a
  shorter ID translation you MUST preserve the original bubble byte-length and keep
  **exactly one** `0xFE`, at its original position. Implementation: write the encoded
  ID text (without an early `0xFE`), fill the gap with **space bytes `0x95`**, then
  place the single `0xFE` at `byte_end-1`.
  - Do NOT append an early `0xFE` and leave the original tail behind: that creates a
    SECOND terminator + leftover English, which shifts the engine's sequential read →
    dialogs split, speaker names vanish, sentences cut off. (Regression fixed 2026-06-20.)
  - Do NOT pad with `0x00`: `0x00` is the glyph `'0'` and renders as "0000" when the
    renderer reads past `0xFE` (the old "OOOO" bug). Space `0x95` renders invisibly.
  - Verified: identity roundtrip byte-identical (19,925 bubbles) + in-game on PPSSPP
    (opening Orbonne prayer + dialogue, event 1).
- **Translation must preserve control codes**: every `<...>` token (`<SPEAKER>`,
  `<f8>`, `<e3>`, `<e0>`, `<PRAYER>`, `<e2>6`, raw `<XX>`) present in `en` must appear
  with the same count in `id_final`, and a speaker bubble's `id_final` must start with
  `<SPEAKER>`. `translate_pipeline.py :: validate_translation` enforces this and ABORTS
  the pipeline on violation (override: `--ignore-control-errors`). Dropping a
  `<SPEAKER>` tag makes the speaker name disappear in-game.
- Always test repacked ISOs in PPSSPP.

## Reference files

- `TODO_PLAN.md` — phased roadmap for completing the FFT WoTL translation pipeline (~5-8 weeks engineering + translation work).
- `DocumentOfComunity.md` — community research (ffhacktics) + internal reverse engineering findings (font format, character table verification, control codes).
- `tools/TEST_EVT_decoded.txt` — full decoded TEST.EVT (5.9 MB raw).
- `tools/TEST_EVT_dialog_only.txt` — 8203 dialog-only blocks (844 KB readable English).
- `tools/font_renders/glyph_dump.txt` — ASCII art of each glyph (visual reference for extending `char_table.json`).
