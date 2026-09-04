#!/usr/bin/env python3
"""Listening overlay: a microphone and an equalizer animated by the voice.

A standalone process launched by the daemon with the system Python (the only
one that has PyGObject). It reads its orders on stdin, one command per line:

    state listening | state working    state change
    level 0.42 [0.10 0.31 ...]         overall volume, then the energy per band
    copy <base64>                      puts the text in the clipboard
    saveclip | restoreclip             saves / hands back the original clipboard
    quit                               close

Why GTK3 and the X11 backend (Xwayland) rather than GTK4/Wayland: under
Wayland a client can neither refuse focus nor position itself. A window of
type NOTIFICATION under X11 does both — essential here, since stealing focus
would send the paste into the overlay instead of the target application.

Only gi + the stdlib are needed: no venv, no pycairo. Hence bars made of
widgets rather than a cairo drawing — fifteen boxes resized on every frame.
"""

from __future__ import annotations

import base64
import binascii
import math
import os
import sys
import threading

# X11 first: it is the only backend that allows "no focus" + positioning.
# To be set before importing gi — set_allowed_backends() would come too late.
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
# Margins of the equalizer area inside the pill: after the mic, before the edge.
BARS_LEFT = 66
BARS_RIGHT = 18
BAR_MIN_HEIGHT = 4         # in silence, the bar shrinks to a dot
BAR_HEIGHT_MARGIN = 20     # room left above and below, in pixels

# An equalizer is read on the rise: the bar jumps on the attack of the syllable
# and comes down slowly, like the needle of a VU meter. Two speeds, then.
ATTACK = 0.55
RELEASE = 0.14
# Without a voice, the equalizer breathes instead of freezing: a passing wave.
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
        # Targets sent by the daemon, and heights actually displayed: the gap
        # between the two is what gives the VU meter its inertia.
        self.targets = [0.0] * self.bar_count
        self.values = [0.0] * self.bar_count
        self.elapsed = 0.0
        self._last_frame: int | None = None

        # No focus, no taskbar, no decoration: an information bubble.
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

        # The bars share the available room: the more of them there are, the
        # thinner they get, without ever going below 2 px.
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
        # Height applied to each bar: remembering it avoids a resize — and hence
        # a window recomputation — when nothing has moved by a single pixel.
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

    # -- commands ----------------------------------------------------------
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
            # Nobody feeds the levels any more: start from zero, otherwise
            # going back to listening would replay the last syllable heard.
            self.level = 0.0
            self.targets = [0.0] * self.bar_count

    def set_level(self, level: float, bands: list[float]) -> None:
        self.level = max(0.0, min(level, 1.0))
        if bands:
            self.targets = [max(0.0, min(band, 1.0)) for band in self._fit(bands)]
        else:
            # No spectrum available: the overall volume animates every bar, in a
            # bell shape, to keep an equalizer silhouette rather than a block.
            middle = (self.bar_count - 1) / 2
            self.targets = [
                self.level * (1.0 - 0.55 * abs(index - middle) / max(middle, 1.0))
                for index in range(self.bar_count)
            ]

    def _fit(self, bands: list[float]) -> list[float]:
        """Maps the received bands onto the number of bars, if the daemon differs."""
        if len(bands) == self.bar_count:
            return bands
        ratio = len(bands) / self.bar_count
        return [bands[min(int(index * ratio), len(bands) - 1)] for index in range(self.bar_count)]

    def copy(self, text: str) -> None:
        """Puts the text in the clipboard (X11: no focus needed)."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()

    def save_clipboard(self) -> None:
        """Saves the user's clipboard before requisitioning it."""
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
            # A sharp rise on the attack, a slow fall: it is that asymmetry
            # that reads as an equalizer rather than as flickering.
            rate = ATTACK if target > self.values[index] else RELEASE
            self.values[index] += (target - self.values[index]) * rate
            self._draw_bar(index, self.values[index], listening)
        return GLib.SOURCE_CONTINUE

    def _target(self, index: int, listening: bool) -> float:
        """Height aimed at by a bar, in 0..1."""
        if not listening:
            # Transcription in progress: a wave crosses the equalizer from left
            # to right, to say it is working without pretending to listen.
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
