"""Compatibility wrapper. Phase 2 — real code lives in psptranslationmod.evt.header.

Will be deleted in Phase 5 once docs migrate fully to the unified CLI.
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
runpy.run_module('psptranslationmod.evt.header', run_name='__main__', alter_sys=True)
