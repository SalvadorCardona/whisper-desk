#!/usr/bin/env python3
"""Clipboard fallback through GTK4, when wl-copy/xclip are not installed.

Under Wayland, only a client that owns a window and has focus can set a
selection: so a tiny window is shown for the duration of the copy, then the
desktop's clipboard manager (mutter…) takes the text over.

Run as a standalone process with the system Python; the text arrives on stdin.
"""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

HOLD_MS = 1400


def main() -> int:
    text = sys.stdin.read()
    if not text:
        return 0

    app = Gtk.Application(application_id="fr.whisperdesk.clipboard")

    def on_activate(application: Gtk.Application) -> None:
        window = Gtk.ApplicationWindow(application=application)
        window.set_decorated(False)
        window.set_default_size(1, 1)
        window.set_opacity(0.0)
        window.present()

        def copy() -> bool:
            window.get_display().get_clipboard().set(text)
            GLib.timeout_add(HOLD_MS, lambda: (application.quit(), False)[1])
            return False

        GLib.timeout_add(120, copy)

    app.connect("activate", on_activate)
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
