"""Rend le paquet importable depuis le dépôt, sans installation."""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
