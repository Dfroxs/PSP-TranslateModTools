"""Single-command end-to-end translation pipeline.

Chain: translation JSON → modified ISO ready untuk PPSSPP.

Steps internal:
  1. Validate translation JSON (control codes preserved, proper nouns intact)
  2. Encode + repack TEST.EVT (substitute bubbles)
  3. Patch fftpack.bin (substitute TEST.EVT + optional other files)
  4. Patch ISO (substitute fftpack.bin)
  5. Optional: generate xdelta3 patch (untuk distribution)
  6. Report stats lengkap

Pakai:
    python tools/translate_pipeline.py \\
        --translations <translations.json> \\
        --original-iso <FFT_WoTL.iso> \\
        --output-iso <FFT_WoTL_ID.iso> \\
        [--xdelta-patch out.xdelta]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


from psptranslationmod import paths

ORIGINAL_TEST_EVT = paths.ORIGINAL_TEST_EVT
ORIGINAL_FFTPACK = paths.ORIGINAL_FFTPACK
EVENTS_PARSED = paths.EVENTS_PARSED
CHAR_TABLE = paths.CHAR_TABLE
FFTPACK_MAP = paths.FFTPACK_MAP
PROPER_NOUNS = paths.PROPER_NOUNS
FFTPACK_ISO_OFFSET = paths.FFTPACK_ISO_OFFSET


def run_step(label: str, cmd: list[str]) -> bool:
    """Run subprocess step, print status."""
    print(f'\n=== {label} ===', file=sys.stderr)
    print(f'$ {" ".join(cmd[:5])}...' if len(cmd) > 5 else f'$ {" ".join(cmd)}', file=sys.stderr)
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f'❌ FAILED ({elapsed:.1f}s)', file=sys.stderr)
        print('STDERR:', result.stderr, file=sys.stderr)
        print('STDOUT:', result.stdout, file=sys.stderr)
        return False
    print(f'✅ done ({elapsed:.1f}s)', file=sys.stderr)
    # Show last few lines of stderr (where progress info lives)
    if result.stderr:
        for line in result.stderr.strip().split('\n')[-8:]:
            print(f'   {line}', file=sys.stderr)
    return True


# Token control-code di dalam teks decoded: <SPEAKER>, <PRAYER>, <e0>, <f8>,
# <e3>, <xx> hex, dll. Semua ini WAJIB dipertahankan di id_final — kalau Gemini
# membuangnya, nama speaker hilang / dialog rusak / pointer bergeser.
CONTROL_TOKEN_RE = re.compile(r'<[^<>]+>')


def _control_tokens(s: str):
    """Multiset (Counter) dari semua token control-code <...> dalam string."""
    from collections import Counter
    return Counter(CONTROL_TOKEN_RE.findall(s))


def validate_translation(trans_path: Path, proper_nouns_path: Path) -> dict:
    """Validasi: proper nouns preserved + control codes/<SPEAKER> tag intact.

    Mengembalikan dict berisi:
      - total_blocks, translated
      - warnings        : proper-noun yang hilang (non-fatal)
      - control_errors  : control-code yang hilang/berkurang di id_final (FATAL)
    """
    trans = json.loads(trans_path.read_text())
    proper_nouns = json.loads(proper_nouns_path.read_text()) if proper_nouns_path.exists() else {}
    all_nouns = set(proper_nouns.get('all_unique', []))

    blocks = trans.get('blocks', trans) if isinstance(trans, dict) else trans
    warnings = []
    control_errors = []
    info = {'total_blocks': len(blocks), 'translated': 0,
            'warnings': [], 'control_errors': []}

    for block in blocks:
        if not isinstance(block, dict):
            continue
        en = block.get('en', '')
        id_text = block.get('id_final') or block.get('id_auto') or ''
        if not id_text:
            continue
        info['translated'] += 1
        bid = block.get('id', '?')

        # --- 1. Control-code / SPEAKER tag preservation (FATAL) ---
        en_tok = _control_tokens(en)
        id_tok = _control_tokens(id_text)
        for tok, cnt in en_tok.items():
            got = id_tok.get(tok, 0)
            if got < cnt:
                control_errors.append(
                    f'  block#{bid}: control code {tok} hilang/berkurang '
                    f'(en={cnt}, id={got})'
                )
        # SPEAKER bubble: id_final harus mulai dengan tag speaker yang sama
        if en.startswith('<SPEAKER>') and not id_text.startswith('<SPEAKER>'):
            control_errors.append(
                f'  block#{bid}: id_final tidak diawali <SPEAKER> '
                f'(nama speaker akan hilang in-game)'
            )

        # --- 2. Proper nouns (non-fatal warning) ---
        for noun in all_nouns:
            if len(noun) > 3 and noun in en and noun not in id_text:
                warnings.append(f'  block#{bid}: proper noun "{noun}" missing in id_final')

    info['warnings'] = warnings
    info['control_errors'] = control_errors
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--translations', type=Path, required=True,
                    help='Translation JSON tunggal ATAU folder berisi chapter_*.json')
    ap.add_argument('--original-iso', type=Path, required=True,
                    help='Original FFT WoTL ISO')
    ap.add_argument('--output-iso', type=Path, required=True,
                    help='Output modified ISO')
    ap.add_argument('--workdir', type=Path, default=Path('/tmp/translate_pipeline'),
                    help='Tempat intermediate files')
    ap.add_argument('--xdelta-patch', type=Path,
                    help='Generate xdelta3 patch (untuk distribution)')
    ap.add_argument('--allow-truncate', action='store_true',
                    help='Truncate translations yang terlalu panjang')
    ap.add_argument('--allow-stretch', action='store_true', default=True,
                    help='Extend ke trailing zeros kalau ada')
    ap.add_argument('--skip-validation', action='store_true')
    ap.add_argument('--ignore-control-errors', action='store_true',
                    help='Lanjut walau ada control-code/<SPEAKER> yang hilang '
                         '(TIDAK disarankan — bisa bikin nama speaker hilang in-game)')
    args = ap.parse_args()

    # Verify required files
    required = [args.original_iso, args.translations, ORIGINAL_TEST_EVT,
                ORIGINAL_FFTPACK, EVENTS_PARSED, CHAR_TABLE, FFTPACK_MAP]
    for p in required:
        if not p.exists():
            print(f'error: required file not found: {p}', file=sys.stderr)
            return 1

    args.workdir.mkdir(parents=True, exist_ok=True)
    PY = sys.executable

    # Merge directory of chunks → single translation JSON
    if args.translations.is_dir():
        merged_blocks = []
        chunk_files = sorted(args.translations.glob('chapter_*.json'))
        print(f'Merging {len(chunk_files)} chunk files...', file=sys.stderr)
        for cf in chunk_files:
            d = json.loads(cf.read_text())
            for block in d.get('blocks', []):
                if block.get('id_final') or block.get('id_auto'):
                    merged_blocks.append(block)
        merged_path = args.workdir / 'merged_translations.json'
        merged_path.write_text(json.dumps(
            {'blocks': merged_blocks, 'metadata': {'merged_from': len(chunk_files)}},
            ensure_ascii=False, indent=2))
        args.translations = merged_path
        print(f'  Merged {len(merged_blocks)} translations → {merged_path}', file=sys.stderr)

    # Step 1: Validation
    if not args.skip_validation:
        print('=== Step 1: Validation ===', file=sys.stderr)
        info = validate_translation(args.translations, PROPER_NOUNS)
        print(f'  Total blocks  : {info["total_blocks"]}', file=sys.stderr)
        print(f'  Translated    : {info["translated"]}', file=sys.stderr)
        print(f'  Proper-noun warn: {len(info["warnings"])}', file=sys.stderr)
        for w in info['warnings'][:5]:
            print(w, file=sys.stderr)
        if len(info['warnings']) > 5:
            print(f'  ... +{len(info["warnings"]) - 5} more', file=sys.stderr)

        # Control-code preservation = FATAL (kecuali di-override)
        ctl = info.get('control_errors', [])
        print(f'  Control-code err: {len(ctl)}', file=sys.stderr)
        for e in ctl[:10]:
            print(e, file=sys.stderr)
        if len(ctl) > 10:
            print(f'  ... +{len(ctl) - 10} more', file=sys.stderr)
        if ctl and not args.ignore_control_errors:
            print('\n❌ ABORT: ada control code/<SPEAKER> yang hilang di id_final.',
                  file=sys.stderr)
            print('   Perbaiki translasi (pertahankan <SPEAKER>, <f8>, <e0>, dll),',
                  file=sys.stderr)
            print('   atau paksa lanjut dengan --ignore-control-errors (berisiko).',
                  file=sys.stderr)
            return 1

    # Step 2: repack_evt — apply translations to TEST.EVT
    modified_evt = args.workdir / 'TEST_modified.evt'
    cmd = [
        PY, '-m', 'psptranslationmod.evt.repack',
        str(ORIGINAL_TEST_EVT),
        str(EVENTS_PARSED),
        str(args.translations),
        str(CHAR_TABLE),
        '--output', str(modified_evt),
    ]
    if args.allow_stretch:
        cmd.append('--allow-stretch')
    if args.allow_truncate:
        cmd.append('--allow-truncate')
    if not run_step('Step 2: repack_evt (apply translations)', cmd):
        return 1

    # Step 3: patch fftpack.bin
    modified_fftpack = args.workdir / 'fftpack_modified.bin'
    cmd = [
        PY, '-m', 'psptranslationmod.pack.fftpack',
        '--fftpack', str(ORIGINAL_FFTPACK),
        '--map', str(FFTPACK_MAP),
        '--substitute', f'TEST.EVT:{modified_evt}',
        '--output', str(modified_fftpack),
    ]
    if not run_step('Step 3: repack_fftpack (patch TEST.EVT into fftpack.bin)', cmd):
        return 1

    # Step 4: patch ISO
    cmd = [
        PY, '-m', 'psptranslationmod.pack.iso',
        '--iso', str(args.original_iso),
        '--substitute', f'fftpack.bin:{modified_fftpack}:{FFTPACK_ISO_OFFSET:#x}',
        '--output', str(args.output_iso),
    ]
    if not run_step('Step 4: patch_iso (patch fftpack.bin into ISO)', cmd):
        return 1

    # Step 5: Optional xdelta patch
    if args.xdelta_patch:
        # Check if xdelta3 available
        which_result = subprocess.run(['which', 'xdelta3'], capture_output=True, text=True)
        if which_result.returncode != 0:
            print(f'\n⚠️  xdelta3 not found, skip patch generation', file=sys.stderr)
            print(f'   Install: brew install xdelta', file=sys.stderr)
        else:
            cmd = [
                'xdelta3', '-e', '-9',
                '-s', str(args.original_iso),
                str(args.output_iso),
                str(args.xdelta_patch),
            ]
            if not run_step('Step 5: Generate xdelta3 patch', cmd):
                return 1
            patch_size = args.xdelta_patch.stat().st_size
            print(f'  Patch size: {patch_size:,} bytes ({patch_size/1024:.1f} KB)',
                  file=sys.stderr)

    # Final summary
    print(f'\n{"=" * 60}', file=sys.stderr)
    print(f'✅ PIPELINE COMPLETE', file=sys.stderr)
    print(f'{"=" * 60}', file=sys.stderr)
    print(f'  Original ISO  : {args.original_iso} ({args.original_iso.stat().st_size:,} bytes)',
          file=sys.stderr)
    print(f'  Modified ISO  : {args.output_iso} ({args.output_iso.stat().st_size:,} bytes)',
          file=sys.stderr)
    if args.xdelta_patch:
        print(f'  XDelta patch  : {args.xdelta_patch}', file=sys.stderr)
    print(f'  Intermediate  : {args.workdir}/', file=sys.stderr)
    print(f'\nNext: boot {args.output_iso.name} di PPSSPP untuk verify in-game text', file=sys.stderr)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
