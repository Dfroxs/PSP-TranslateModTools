"""Local web UI for the FFT WoTL translation workflow.

Stdlib-only (http.server). Wraps the existing CLI subcommands (`gemini`,
`script-check`) plus the real encoder so the human reviewer can, from a browser:

  1. one-click full-translate a chapter (streamed live log),
  2. preview each block as an FFT WoTL dialog box,
  3. filter blocks by Skip / Error / Review / Done,
  4. hand-edit `id_final` (with live encoded byte-budget check),
  5. chat with Gemini about a block / the chapter.

Run:  python -m psp_translate webui  [--port 8000] [--host 127.0.0.1]

No bespoke argparse lives here beyond `__main__`; the server itself is in
`server.py`. Paths come from `psp_translate.paths` (single source of truth).
"""
from __future__ import annotations

from .server import main

__all__ = ["main"]
