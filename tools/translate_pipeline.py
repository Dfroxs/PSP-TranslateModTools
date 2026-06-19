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
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).parent.parent
TOOLS_DIR = ROOT / 'tools'
EXTRACTED_DIR = ROOT / 'extracted'


# Standard paths
ORIGINAL_TEST_EVT = EXTRACTED_DIR / 'FFTPACK_Extracted' / 'EVENT' / 'TEST.EVT'
ORIGINAL_FFTPACK = EXTRACTED_DIR / 'PSP_GAME' / 'USRDIR' / 'fftpack.bin'
EVENTS_PARSED = TOOLS_DIR / 'events_parsed.json'
CHAR_TABLE = TOOLS_DIR / 'char_table.json'
FFTPACK_MAP = TOOLS_DIR / 'fftpack_event_map.json'
PROPER_NOUNS = TOOLS_DIR / 'proper_nouns.json'

# Standard ISO location of fftpack.bin
FFTPACK_ISO_OFFSET = 0x02c20000


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


def validate_translation(trans_path: Path, proper_nouns_path: Path) -> dict:
    """Quick validation: check proper nouns preserved, control codes intact."""
    trans = json.loads(trans_path.read_text())
    proper_nouns = json.loads(proper_nouns_path.read_text()) if proper_nouns_path.exists() else {}
    all_nouns = set(proper_nouns.get('all_unique', []))

    blocks = trans.get('blocks', trans) if isinstance(trans, dict) else trans
    warnings = []
    info = {'total_blocks': len(blocks), 'translated': 0, 'warnings': []}

    for block in blocks:
        if not isinstance(block, dict):
            continue
        en = block.get('en', '')
        id_text = block.get('id_final') or block.get('id_auto') or ''
        if not id_text:
            continue
        info['translated'] += 1

        # Check proper nouns
        bid = block.get('id', '?')
        for noun in all_nouns:
            if len(noun) > 3 and noun in en and noun not in id_text:
                warnings.append(f'  block#{bid}: proper noun "{noun}" missing in id_final')
                if len(warnings) >= 10:
                    warnings.append('  ... (more warnings truncated)')
                    break
        if len(warnings) >= 11:
            break

    info['warnings'] = warnings
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
        print(f'  Total blocks: {info["total_blocks"]}', file=sys.stderr)
        print(f'  Translated  : {info["translated"]}', file=sys.stderr)
        print(f'  Warnings    : {len(info["warnings"])}', file=sys.stderr)
        for w in info['warnings'][:5]:
            print(w, file=sys.stderr)
        if len(info['warnings']) > 5:
            print(f'  ... +{len(info["warnings"]) - 5} more', file=sys.stderr)

    # Step 2: repack_evt — apply translations to TEST.EVT
    modified_evt = args.workdir / 'TEST_modified.evt'
    cmd = [
        PY, str(TOOLS_DIR / 'repack_evt.py'),
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
        PY, str(TOOLS_DIR / 'repack_fftpack.py'),
        '--fftpack', str(ORIGINAL_FFTPACK),
        '--map', str(FFTPACK_MAP),
        '--substitute', f'TEST.EVT:{modified_evt}',
        '--output', str(modified_fftpack),
    ]
    if not run_step('Step 3: repack_fftpack (patch TEST.EVT into fftpack.bin)', cmd):
        return 1

    # Step 4: patch ISO
    cmd = [
        PY, str(TOOLS_DIR / 'patch_iso.py'),
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
