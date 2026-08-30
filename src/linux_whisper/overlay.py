#!/usr/bin/env python3
"""Overlay d'écoute : un micro et trois points animés au rythme de la voix.

Processus autonome lancé par le daemon avec le Python système (le seul qui a
PyGObject). Il lit ses ordres sur stdin, une commande par ligne :

    state listening | state working    changement d'état
    level 0.42                         niveau de voix courant (0..1, échelle dB)
    copy <base64>                      pose le texte dans le presse-papiers
    saveclip | restoreclip             mémorise / rend le presse-papiers d'origine
    quit                               fermeture

Pourquoi GTK3 et le backend X11 (Xwayland) plutôt que GTK4/Wayland : sous
Wayland un client ne peut ni refuser le focus ni se positionner. Une fenêtre
de type NOTIFICATION sous X11 fait les deux — indispensable ici, car voler le
focus enverrait le collage dans l'overlay au lieu de l'application visée.

N'importe que gi + la stdlib : ni venv, ni pycairo.
"""

from __future__ import annotations

import base64
import binascii
import collections
import math
import os
import sys
import threading

# X11 d'abord : c'est le seul backend qui permette « pas de focus » + positionnement.
# À poser avant l'import de gi — set_allowed_backends() arriverait trop tard.
if os.environ.get("DISPLAY") and not os.environ.get("GDK_BACKEND"):
    os.environ["GDK_BACKEND"] = "x11"

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

WIDTH = 168
HEIGHT = 64
ACCENT = "#e46212"
POSITION = "bottom-center"
MARGIN = 96
DOT_COUNT = 3
DOT_SIZE = 9
MIC_SIZE = 24

# Chaque point porte une mesure de voix différente : la plus fraîche près du
# micro, les plus anciennes vers la droite. L'onde traverse donc la pilule au
# rythme réel de la parole, au lieu d'osciller toute d'un bloc.
DOT_TRAVEL_BASE = 2.5      # respiration au repos, en pixels
DOT_TRAVEL_VOICE = 10.0    # course ajoutée à pleine voix, en pixels
LEVEL_SMOOTHING = 0.25     # lissage exponentiel, par image

CSS_TEMPLATE = """
#overlay-root {{
    background-color: rgba(23, 23, 26, 0.94);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: {radius}px;
}}
.dot {{
    background-color: {accent};
    border-radius: {dot_radius}px;
}}
.dot.working {{ background-color: #ffffff; }}
.mic {{ color: {accent}; }}
.mic.working {{ color: rgba(255, 255, 255, 0.65); }}
.halo {{
    background-image: radial-gradient(circle, {accent} 0%, rgba(0, 0, 0, 0) 70%);
    border-radius: 24px;
}}
"""


class Overlay(Gtk.Window):
    def __init__(self, width: int, height: int, accent: str, position: str, margin: int):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.width, self.height = width, height
        self.state = "listening"
        self._saved_clipboard: str | None = None
        self.level = 0.0
        self.smoothed = 0.0
        # Une case par point : le niveau y est décalé d'un cran à chaque mesure.
        self.history: collections.deque[float] = collections.deque(
            [0.0] * DOT_COUNT, maxlen=DOT_COUNT
        )
        self.dot_levels = [0.0] * DOT_COUNT
        self.elapsed = 0.0
        self._last_frame: int | None = None

        # Ni focus, ni barre des tâches, ni décoration : une bulle d'information.
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_app_paintable(True)
        self.set_default_size(width, height)
        self.set_size_request(width, height)

        screen = self.get_screen()
        visual = screen.get_rgba_visual() if screen else None
        if visual is not None:
            self.set_visual(visual)

        provider = Gtk.CssProvider()
        provider.load_from_data(
            CSS_TEMPLATE.format(
                radius=height // 2, accent=accent, dot_radius=DOT_SIZE // 2 + 1
            ).encode()
        )
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        canvas = Gtk.Fixed()
        canvas.set_name("overlay-root")
        canvas.set_size_request(width, height)
        self.add(canvas)
        self.canvas = canvas

        self.halo = Gtk.Box()
        self.halo.get_style_context().add_class("halo")
        self.halo.set_size_request(48, 48)
        self.halo.set_opacity(0.0)
        canvas.put(self.halo, 10, height // 2 - 24)

        self.mic = Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic", Gtk.IconSize.DND)
        self.mic.set_pixel_size(MIC_SIZE)
        self.mic.get_style_context().add_class("mic")
        canvas.put(self.mic, 34 - MIC_SIZE // 2, height // 2 - MIC_SIZE // 2)

        span = width - 78 - 24
        self.dots: list[Gtk.Box] = []
        self.dot_x: list[int] = []
        for index in range(DOT_COUNT):
            dot = Gtk.Box()
            dot.get_style_context().add_class("dot")
            dot.set_size_request(DOT_SIZE, DOT_SIZE)
            x = int(78 + index * (span / max(DOT_COUNT - 1, 1)) - DOT_SIZE / 2)
            canvas.put(dot, x, height // 2 - DOT_SIZE // 2)
            self.dots.append(dot)
            self.dot_x.append(x)

        self.center_y = height // 2 - DOT_SIZE // 2
        self.connect("realize", lambda _widget: self._place(position, margin))
        self.add_tick_callback(self._tick)

    # -- placement ---------------------------------------------------------
    def _place(self, position: str, margin: int) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor is None:
            return
        area = monitor.get_workarea()
        x = area.x + (area.width - self.width) // 2
        if position == "top-center":
            y = area.y + margin
        elif position == "center":
            y = area.y + (area.height - self.height) // 2
        else:  # bottom-center
            y = area.y + area.height - self.height - margin
        self.move(x, y)

    # -- commandes ---------------------------------------------------------
    def set_state(self, state: str) -> None:
        self.state = state
        working = state == "working"
        for widget in (*self.dots, self.mic):
            context = widget.get_style_context()
            if working:
                context.add_class("working")
            else:
                context.remove_class("working")
        if working:
            self.halo.set_opacity(0.0)
            # Plus personne n'alimente les niveaux : on repart de zéro, sinon le
            # retour à l'écoute rejouerait la dernière syllabe entendue.
            self.level = 0.0
            self.history.extend([0.0] * DOT_COUNT)

    def set_level(self, level: float) -> None:
        self.level = max(0.0, min(level, 1.0))
        self.history.appendleft(self.level)

    def copy(self, text: str) -> None:
        """Pose le texte dans le presse-papiers (X11 : pas besoin du focus)."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()

    def save_clipboard(self) -> None:
        """Mémorise le presse-papiers de l'utilisateur avant de le réquisitionner."""
        if self._saved_clipboard is None:
            self._saved_clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or ""

    def restore_clipboard(self) -> None:
        if self._saved_clipboard is None:
            return
        if self._saved_clipboard:
            self.copy(self._saved_clipboard)
        self._saved_clipboard = None

    # -- animation ---------------------------------------------------------
    def _tick(self, _widget: Gtk.Widget, clock) -> bool:
        now = clock.get_frame_time()
        if self._last_frame is not None:
            self.elapsed += (now - self._last_frame) / 1_000_000
        self._last_frame = now
        # Lissage exponentiel : la voix module l'animation sans à-coups.
        self.smoothed += (self.level - self.smoothed) * LEVEL_SMOOTHING
        for index, target in enumerate(self.history):
            self.dot_levels[index] += (target - self.dot_levels[index]) * LEVEL_SMOOTHING

        listening = self.state == "listening"
        if listening:
            breathe = 0.5 + 0.5 * math.sin(self.elapsed * 3.5)
            self.halo.set_opacity(0.10 + 0.22 * self.smoothed + 0.05 * breathe)
            self.mic.set_opacity(0.85 + 0.15 * breathe)
        else:
            self.mic.set_opacity(0.7)

        speed = 5.0 if listening else 3.2
        for index, dot in enumerate(self.dots):
            wave = math.sin(self.elapsed * speed - index * 0.7)
            if listening:
                voice = self.dot_levels[index]
                travel = DOT_TRAVEL_BASE + DOT_TRAVEL_VOICE * voice
                self.canvas.move(dot, self.dot_x[index], int(self.center_y - wave * travel))
                dot.set_opacity(0.45 + 0.25 * ((wave + 1) / 2) + 0.30 * voice)
            else:
                self.canvas.move(dot, self.dot_x[index], self.center_y)
                dot.set_opacity(0.30 + 0.60 * max(wave, 0.0))
        return GLib.SOURCE_CONTINUE


def read_commands(window: Overlay) -> None:
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        command, *rest = parts
        if command == "quit":
            break
        if command == "saveclip":
            GLib.idle_add(window.save_clipboard)
            continue
        if command == "restoreclip":
            GLib.idle_add(window.restore_clipboard)
            continue
        if not rest:
            continue
        if command == "state":
            GLib.idle_add(window.set_state, rest[0])
        elif command == "level":
            try:
                GLib.idle_add(window.set_level, float(rest[0]))
            except ValueError:
                pass
        elif command == "copy":
            try:
                text = base64.b64decode(rest[0]).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                continue
            GLib.idle_add(window.copy, text)
    GLib.idle_add(Gtk.main_quit)


def main(argv: list[str]) -> int:
    width = int(argv[1]) if len(argv) > 1 else WIDTH
    height = int(argv[2]) if len(argv) > 2 else HEIGHT
    accent = argv[3] if len(argv) > 3 else ACCENT
    position = argv[4] if len(argv) > 4 else POSITION
    margin = int(argv[5]) if len(argv) > 5 else MARGIN

    window = Overlay(width, height, accent, position, margin)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    threading.Thread(target=read_commands, args=(window,), daemon=True).start()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
