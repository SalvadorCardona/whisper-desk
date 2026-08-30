"""Rend le paquet importable depuis le dépôt, sans installation."""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))


import contextlib  # noqa: E402
import os  # noqa: E402


@contextlib.contextmanager
def forced_host(name: str):
    """Fait croire au programme qu'il tourne sur cet hôte, le temps du bloc.

    Les tests des trois hôtes doivent passer depuis n'importe lequel : la
    détection s'appuie sur LW_HOST, et son résultat est mis en cache.
    """
    from linux_whisper import host

    previous = os.environ.get("LW_HOST")
    os.environ["LW_HOST"] = name
    host.reset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LW_HOST", None)
        else:
            os.environ["LW_HOST"] = previous
        host.reset()
