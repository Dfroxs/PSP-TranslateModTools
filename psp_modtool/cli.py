"""Antarmuka command-line untuk PSP Mod Tool."""

import argparse

from . import core


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='psp-modtool',
        description='PSP ISO Modding Tool - Extract, Scan, Edit, Repack',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh penggunaan:
  psp-modtool extract  game.iso     ./extracted
  psp-modtool scan     ./extracted  strings.json
  psp-modtool apply    ./extracted  strings_edited.json
  psp-modtool repack   ./extracted  game_modded.iso
  psp-modtool all      game.iso     ./workdir
""",
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('info', help='Cek kelayakan ISO untuk diterjemahkan')
    p.add_argument('iso')

    p = sub.add_parser('extract', help='Extract file dari ISO')
    p.add_argument('iso')
    p.add_argument('output')

    p = sub.add_parser('scan', help='Scan teks dalam folder')
    p.add_argument('folder')
    p.add_argument('json')
    p.add_argument('--min-len', type=int, default=5,
                   help='Panjang minimum string (default: 5)')

    p = sub.add_parser('apply', help='Apply terjemahan dari JSON')
    p.add_argument('folder')
    p.add_argument('json')

    p = sub.add_parser('repack', help='Repack folder menjadi ISO')
    p.add_argument('folder')
    p.add_argument('output')

    p = sub.add_parser('all', help='Full pipeline interaktif')
    p.add_argument('iso')
    p.add_argument('folder')

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.command == 'info':
        core.inspect_iso(args.iso)
    elif args.command == 'extract':
        core.extract_iso(args.iso, args.output)
    elif args.command == 'scan':
        core.scan_folder(args.folder, args.json, min_len=args.min_len)
    elif args.command == 'apply':
        core.apply_translations(args.folder, args.json)
    elif args.command == 'repack':
        core.repack_iso(args.folder, args.output)
    elif args.command == 'all':
        core.run_all(args.iso, args.folder)


if __name__ == '__main__':
    main()
