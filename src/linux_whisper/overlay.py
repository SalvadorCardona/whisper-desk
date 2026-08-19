#!/usr/bin/env python3
"""Overlay d'écoute : un micro et trois points animés au rythme de la voix.

Processus autonome lancé par le daemon avec le Python système (le seul qui a
PyGObject). Il lit ses ordres sur stdin, une commande par ligne :

    state listening | state working    changement d'état
    level 0.42                         niveau audio courant (0..1)
    copy <base64>                      pose le texte dans le presse-papiers
    quit                               fermeture

La copie passe par l'overlay parce que, sous Wayland, seul un client qui a une
fenêtre focalisée peut poser une sélection.

N'importe que gi + la stdlib : ni venv, ni pycairo, ni gtk4-layer-shell.
"""

from __future__ import annotations

import base64
import binascii
import math
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

WIDTH = 168
HEIGHT = 64
ACCENT = "#e46212"
DOT_COUNT = 3
DOT_SIZE = 9
MIC_SIZE = 24

CSS_TEMPLATE = """
window, window.background {{ background: transparent; }}
.pill {{
    background-color: rgba(23, 23, 26, 0.92);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: {radius}px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
}}
.dot {{
    background-color: {accent};
    border-radius: {dot_radius}px;
    min-width: {dot}px;
    min-height: {dot}px;
}}
.dot.working {{ background-color: #ffffff; }}
.mic {{ color: {accent}; }}
.mic.working {{ color: rgba(255, 255, 255, 0.65); }}
.halo {{
    background-image: radial-gradient(circle, {accent} 0%, rgba(0,0,0,0) 70%);
    border-radius: 24px;
    min-width: 48px;
    min-height: 48px;
}}
"""


class Overlay(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, width: int, height: int, accent: str):
        super().__init__(application=app)
        self.state = "listening"
        self.level = 0.0
        self.smoothed = 0.0
        self.elapsed = 0.0
        self._last_frame: int | None = None

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(width, height)
        self.set_title("linux-whisper")

        provider = Gtk.CssProvider()
        provider.load_from_data(
            CSS_TEMPLATE.format(
                radius=height // 2,
                accent=accent,
                dot=DOT_SIZE,
                dot_radius=DOT_SIZE // 2 + 1,
            ).encode()
        )
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        canvas = Gtk.Fixed()
        canvas.add_css_class("pill")
        canvas.set_size_request(width, height)
        self.set_child(canvas)
        self.canvas = canvas

        self.halo = Gtk.Box()
        self.halo.add_css_class("halo")
        self.halo.set_opacity(0.0)
        canvas.put(self.halo, 10, height / 2 - 24)

        self.mic = Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic")
        self.mic.set_pixel_size(MIC_SIZE)
        self.mic.add_css_class("mic")
        canvas.put(self.mic, 34 - MIC_SIZE / 2, height / 2 - MIC_SIZE / 2)

        span = width - 78 - 24
        self.dots: list[Gtk.Box] = []
        self.dot_x: list[float] = []
        for index in range(DOT_COUNT):
            dot = Gtk.Box()
            dot.add_css_class("dot")
            dot.set_size_request(DOT_SIZE, DOT_SIZE)
            x = 78 + index * (span / max(DOT_COUNT - 1, 1)) - DOT_SIZE / 2
            canvas.put(dot, x, height / 2 - DOT_SIZE / 2)
            self.dots.append(dot)
            self.dot_x.append(x)

        self.center_y = height / 2 - DOT_SIZE / 2
        self.add_tick_callback(self._tick)

    # -- commandes ---------------------------------------------------------
    def set_state(self, state: str) -> None:
        self.state = state
        working = state == "working"
        for widget in (*self.dots, self.mic):
            if working:
                widget.add_css_class("working")
            else:
                widget.remove_css_class("working")
        if working:
            self.halo.set_opacity(0.0)

    def set_level(self, level: float) -> None:
        self.level = max(0.0, min(level, 1.0))

    def copy(self, text: str) -> None:
        """Pose le texte dans le presse-papiers du bureau."""
        self.get_display().get_clipboard().set(text)

    # -- animation ---------------------------------------------------------
    def _tick(self, _widget: Gtk.Widget, clock) -> bool:
        now = clock.get_frame_time()
        if self._last_frame is not None:
            self.elapsed += (now - self._last_frame) / 1_000_000
        self._last_frame = now
        # Lissage exponentiel : la voix module l'animation sans à-coups.
        self.smoothed += (self.level - self.smoothed) * 0.25

        listening = self.state == "listening"
        if listening:
            breathe = 0.5 + 0.5 * math.sin(self.elapsed * 3.5)
            self.halo.set_opacity(0.10 + 0.22 * self.smoothed + 0.05 * breathe)
            self.mic.set_opacity(0.85 + 0.15 * breathe)
        else:
            self.mic.set_opacity(0.7)

        speed = 5.0 if listening else 3.2
        amplitude = 3.5 + 9.0 * self.smoothed if listening else 0.0
        for index, dot in enumerate(self.dots):
            wave = math.sin(self.elapsed * speed - index * 0.7)
            if listening:
                self.canvas.move(dot, self.dot_x[index], self.center_y - wave * amplitude)
                dot.set_opacity(0.65 + 0.35 * ((wave + 1) / 2))
            else:
                self.canvas.move(dot, self.dot_x[index], self.center_y)
                dot.set_opacity(0.30 + 0.60 * max(wave, 0.0))
        return GLib.SOURCE_CONTINUE


class OverlayApp(Gtk.Application):
    def __init__(self, width: int, height: int, accent: str):
        super().__init__(application_id="fr.linuxwhisper.overlay")
        self.width, self.height, self.accent = width, height, accent
        self.window: Overlay | None = None

    def do_activate(self) -> None:  # noqa: N802 (API GTK)
        if self.window is None:
            self.window = Overlay(self, self.width, self.height, self.accent)
            threading.Thread(target=self._read_commands, daemon=True).start()
        self.window.present()

    def _read_commands(self) -> None:
        for line in sys.stdin:
            parts = line.split()
            if not parts:
                continue
            command, *rest = parts
            if command == "quit":
                break
            if not self.window or not rest:
                continue
            if command == "state":
                GLib.idle_add(self.window.set_state, rest[0])
            elif command == "copy":
                try:
                    text = base64.b64decode(rest[0]).decode("utf-8")
                except (binascii.Error, UnicodeDecodeError):
                    continue
                GLib.idle_add(self.window.copy, text)
            elif command == "level":
                try:
                    GLib.idle_add(self.window.set_level, float(rest[0]))
                except ValueError:
                    pass
        GLib.idle_add(self.quit)


def main(argv: list[str]) -> int:
    width = int(argv[1]) if len(argv) > 1 else WIDTH
    height = int(argv[2]) if len(argv) > 2 else HEIGHT
    accent = argv[3] if len(argv) > 3 else ACCENT
    return OverlayApp(width, height, accent).run([])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
