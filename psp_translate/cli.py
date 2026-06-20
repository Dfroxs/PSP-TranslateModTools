"""Unified `psp-translate` CLI.

Dispatches each subcommand to the existing module's `__main__` via runpy.
No re-implementation of argparse — submodules own their own flags.
"""
from __future__ import annotations

import runpy
import sys

SUBCOMMANDS: dict[str, tuple[str, str]] = {
    # name              (module path,                              one-line help)
    'decode':           ('psp_translate.codec.decode',             'Decode .evt bytes → readable text'),
    'encode':           ('psp_translate.codec.encode',             'Encode text → bytes (lossless)'),
    'char-table':       ('psp_translate.codec.char_table',         'Manage char_table.json (init/dump/set/stats)'),
    'evt-header':       ('psp_translate.evt.header',               'Parse TEST.EVT chunk header'),
    'evt-parse':        ('psp_translate.evt.parser',               'Parse TEST.EVT events → JSON'),
    'evt-repack':       ('psp_translate.evt.repack',               'Apply ID translations to TEST.EVT'),
    'budget':           ('psp_translate.evt.budget',               'Per-bubble byte budget for translator'),
    'fftpack':          ('psp_translate.pack.fftpack',             'Patch fftpack.bin with modified files'),
    'iso':              ('psp_translate.pack.iso',                 'Size-preserving ISO patch (no rebuild)'),
    'workspace':        ('psp_translate.translate.workspace',      'Build translation workspace chunks'),
    'gemini':           ('psp_translate.translate.gemini',         'Auto-translate via Gemini API'),
    'pipeline':         ('psp_translate.translate.pipeline',       'End-to-end: translations → modified ISO'),
    'review-apply':     ('psp_translate.translate.review',         'Auto-apply proper-noun precedents to needs_review blocks'),
    'lzw-extract':      ('psp_translate.lzw.extract',              'Extract content from plain-text .LZW files'),
    'explore':          ('psp_translate.revtools.explore',         'Byte-level heuristic analyzer'),
    'font-render':      ('psp_translate.revtools.font_render',     'Render FONT.BIN to PGM grid'),
    'script-check':     ('psp_translate.revtools.script_check',        'Cross-check blocks vs offline wiki script'),
    'proper-nouns':     ('psp_translate.revtools.proper_nouns',    'Extract proper nouns from WORLD.LZW'),
    'webui':            ('psp_translate.webui',                    'Local web UI: translate/review/edit chapters'),
    'verify':           ('tests.test_stretch_path',                'Regression gate (stretch path + roundtrip)'),
}


def print_help() -> None:
    print('usage: psp-translate <subcommand> [args...]')
    print('       psp-translate <subcommand> --help')
    print()
    print('FFT WoTL translation toolkit — see CLAUDE.md / TUTORIAL.md for context.')
    print()
    print('Subcommands:')
    width = max(len(n) for n in SUBCOMMANDS)
    for name, (_, help_) in SUBCOMMANDS.items():
        print(f'  {name:<{width}}  {help_}')


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print_help()
        return 0
    sub = sys.argv[1]
    if sub not in SUBCOMMANDS:
        print(f'psp-translate: unknown subcommand: {sub!r}', file=sys.stderr)
        print('Run `psp-translate --help` for the list.', file=sys.stderr)
        return 2
    mod, _ = SUBCOMMANDS[sub]
    # Drop the subcommand token so the submodule's argparse sees its own args.
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    try:
        runpy.run_module(mod, run_name='__main__', alter_sys=True)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
