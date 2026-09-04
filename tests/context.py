"""Makes the package importable from the repository, without installing it."""

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
    """Makes the program believe it runs on this host, for the duration of the block.

    The tests of all three hosts must pass from any of them: detection relies
    on WD_HOST, and its result is cached.
    """
    from whisper_desk import host

    previous = os.environ.get("WD_HOST")
    os.environ["WD_HOST"] = name
    host.reset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("WD_HOST", None)
        else:
            os.environ["WD_HOST"] = previous
        host.reset()
