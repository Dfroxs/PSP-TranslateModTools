"""Entry point: `python -m psp_translate webui` (via cli.py dispatcher)."""
from __future__ import annotations

import sys

from .server import main

if __name__ == "__main__":
    sys.exit(main())
