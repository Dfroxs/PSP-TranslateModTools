#!/usr/bin/env python3
"""
Entry point PSP Mod Tool.

Penggunaan:
  python main.py extract  game.iso     ./extracted
  python main.py scan     ./extracted  strings.json
  python main.py apply    ./extracted  strings_edited.json
  python main.py repack   ./extracted  game_modded.iso
  python main.py all      game.iso     ./workdir
"""

from psp_modtool.cli import main

if __name__ == '__main__':
    main()
