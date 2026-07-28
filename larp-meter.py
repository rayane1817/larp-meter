#!/usr/bin/env python3
"""LARP Meter entry point — keeps `python larp-meter.py ...` working.

The implementation lives in the larp_meter package; this shim only fixes
sys.path so the script runs from any working directory.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from larp_meter.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main() or 0)
