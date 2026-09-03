#!/usr/bin/env python3
"""Overlay d'écoute : un micro et un equalizer animé au rythme de la voix.

Processus autonome lancé par le daemon avec le Python système (le seul qui a
PyGObject). Il lit ses ordres sur stdin, une commande par ligne :

    state listening | state working    changement d'état
    level 0.42 [0.10 0.31 ...]         volume global, puis l'énergie par bande
    copy <base64>                      pose le texte dans le presse-papiers
    saveclip | restoreclip             mémorise / rend le presse-papiers d'origine
    quit                               fermeture

Pourquoi GTK3 et le backend X11 (Xwayland) plutôt que GTK4/Wayland : sous
Wayland un client ne peut ni refuser le focus ni se positionner. Une fenêtre
de type NOTIFICATION sous X11 fait les deux — indispensable ici, car voler le
focus enverrait le collage dans l'overlay au lieu de l'application visée.

N'importe que gi + la stdlib : ni venv, ni pycairo. D'où des barres en widgets
plutôt qu'un dessin cairo — quinze boîtes redimensionnées à chaque image.
"""

from __future__ import annotations

import base64
import binascii
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

WIDTH = 232
HEIGHT = 64
ACCENT = "#e46212"
POSITION = "bottom-center"
MARGIN = 96
BAR_COUNT = 15
MIC_SIZE = 24
# Marges de la zone d'equalizer dans la pilule : après le micro, avant le bord.
BARS_LEFT = 66
BARS_RIGHT = 18
BAR_MIN_HEIGHT = 4         # au silence, la barre se réduit à une pastille
BAR_HEIGHT_MARGIN = 20     # air laissé au-dessus et en dessous, en pixels

# Un equalizer se lit à la montée : la barre bondit sur l'attaque de la syllabe
# et redescend doucement, comme l'aiguille d'un VU-mètre. Deux vitesses, donc.
ATTACK = 0.55
RELEASE = 0.14
# Sans voix, l'equalizer respire au lieu de se figer : une onde qui traverse.
IDLE_WAVE = 0.10
IDLE_SPEED = 3.2
WORKING_SPEED = 4.5

CSS_TEMPLATE = """
#overlay-root {{
    background-color: rgba(23, 23, 26, 0.94);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: {radius}px;
}}
.bar {{
    background-color: {accent};
    border-radius: {bar_radius}px;
}}
.bar.working {{ background-color: #ffffff; }}
.mic {{ color: {accent}; }}
.mic.working {{ color: rgba(255, 255, 255, 0.65); }}
.halo {{
    background-image: radial-gradient(circle, {accent} 0%, rgba(0, 0, 0, 0) 70%);
    border-radius: 24px;
}}
"""


class Overlay(Gtk.Window):
    def __init__(
        self,
        width: int,
        height: int,
        accent: str,
        position: str,
        margin: int,
        bars: int,
    ):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.width, self.height = width, height
        self.state = "listening"
        self._saved_clipboard: str | None = None
        self.level = 0.0
        self.smoothed = 0.0
        self.bar_count = max(bars, 1)
        # Cibles envoyées par le daemon, et hauteurs réellement affichées : c'est
        # l'écart entre les deux qui donne l'inertie du VU-mètre.
        self.targets = [0.0] * self.bar_count
        self.values = [0.0] * self.bar_count
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

        # Les barres se partagent la place disponible : plus elles sont
        # nombreuses, plus elles sont fines, sans jamais descendre sous 2 px.
        span = max(width - BARS_LEFT - BARS_RIGHT, self.bar_count * 3)
        self.pitch = span / self.bar_count
        self.bar_width = max(int(self.pitch * 0.58), 2)
        self.max_height = max(height - BAR_HEIGHT_MARGIN, BAR_MIN_HEIGHT + 2)

        provider = Gtk.CssProvider()
        provider.load_from_data(
            CSS_TEMPLATE.format(
                radius=height // 2, accent=accent, bar_radius=self.bar_width // 2 + 1
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

        self.center_y = height // 2
        self.bars: list[Gtk.Box] = []
        self.bar_x: list[int] = []
        # Hauteur posée sur chaque barre : la retenir évite un redimensionnement
        # — et donc un recalcul de la fenêtre — quand rien n'a bougé d'un pixel.
        self.bar_heights = [0] * self.bar_count
        for index in range(self.bar_count):
            bar = Gtk.Box()
            bar.get_style_context().add_class("bar")
            bar.set_size_request(self.bar_width, BAR_MIN_HEIGHT)
            x = int(BARS_LEFT + index * self.pitch + (self.pitch - self.bar_width) / 2)
            canvas.put(bar, x, self.center_y - BAR_MIN_HEIGHT // 2)
            self.bars.append(bar)
            self.bar_x.append(x)
            self.bar_heights[index] = BAR_MIN_HEIGHT

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
        for widget in (*self.bars, self.mic):
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
            self.targets = [0.0] * self.bar_count

    def set_level(self, level: float, bands: list[float]) -> None:
        self.level = max(0.0, min(level, 1.0))
        if bands:
            self.targets = [max(0.0, min(band, 1.0)) for band in self._fit(bands)]
        else:
            # Spectre indisponible : le volume global anime toutes les barres, en
            # cloche, pour garder une silhouette d'equalizer plutôt qu'un bloc.
            middle = (self.bar_count - 1) / 2
            self.targets = [
                self.level * (1.0 - 0.55 * abs(index - middle) / max(middle, 1.0))
                for index in range(self.bar_count)
            ]

    def _fit(self, bands: list[float]) -> list[float]:
        """Ramène les bandes reçues au nombre de barres, si le daemon en diffère."""
        if len(bands) == self.bar_count:
            return bands
        ratio = len(bands) / self.bar_count
        return [bands[min(int(index * ratio), len(bands) - 1)] for index in range(self.bar_count)]

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
        self.smoothed += (self.level - self.smoothed) * ATTACK

        listening = self.state == "listening"
        if listening:
            breathe = 0.5 + 0.5 * math.sin(self.elapsed * 3.5)
            self.halo.set_opacity(0.10 + 0.22 * self.smoothed + 0.05 * breathe)
            self.mic.set_opacity(0.85 + 0.15 * breathe)
        else:
            self.mic.set_opacity(0.7)

        for index in range(self.bar_count):
            target = self._target(index, listening)
            # Montée franche sur l'attaque, redescente lente : c'est cette
            # asymétrie qui fait lire un equalizer plutôt qu'un scintillement.
            rate = ATTACK if target > self.values[index] else RELEASE
            self.values[index] += (target - self.values[index]) * rate
            self._draw_bar(index, self.values[index], listening)
        return GLib.SOURCE_CONTINUE

    def _target(self, index: int, listening: bool) -> float:
        """Hauteur visée par une barre, en 0..1."""
        if not listening:
            # Transcription en cours : une onde traverse l'equalizer de gauche
            # à droite, pour dire que ça travaille sans prétendre écouter.
            phase = self.elapsed * WORKING_SPEED - index * 0.55
            return 0.10 + 0.32 * max(math.sin(phase), 0.0) ** 2
        wave = 0.5 + 0.5 * math.sin(self.elapsed * IDLE_SPEED - index * 0.45)
        return max(self.targets[index], IDLE_WAVE * wave)

    def _draw_bar(self, index: int, value: float, listening: bool) -> None:
        height = BAR_MIN_HEIGHT + int((self.max_height - BAR_MIN_HEIGHT) * value)
        bar = self.bars[index]
        if height != self.bar_heights[index]:
            self.bar_heights[index] = height
            bar.set_size_request(self.bar_width, height)
            self.canvas.move(bar, self.bar_x[index], self.center_y - height // 2)
        bar.set_opacity(0.45 + 0.55 * value if listening else 0.30 + 0.60 * value)


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
                values = [float(part) for part in rest]
            except ValueError:
                continue
            GLib.idle_add(window.set_level, values[0], values[1:])
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
    bars = int(argv[6]) if len(argv) > 6 else BAR_COUNT

    window = Overlay(width, height, accent, position, margin, bars)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    threading.Thread(target=read_commands, args=(window,), daemon=True).start()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
