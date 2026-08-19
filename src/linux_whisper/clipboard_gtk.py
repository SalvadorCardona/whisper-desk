#!/usr/bin/env python3
"""Repli presse-papiers via GTK4, quand wl-copy/xclip ne sont pas installés.

Sous Wayland, seul un client possédant une fenêtre et le focus peut poser une
sélection : on affiche donc une fenêtre minuscule le temps de la copie, puis on
laisse le gestionnaire de presse-papiers du bureau (mutter…) reprendre le texte.

Lancé comme processus autonome avec le Python système ; le texte arrive sur stdin.
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

    app = Gtk.Application(application_id="fr.linuxwhisper.clipboard")

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
