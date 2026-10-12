#!/usr/bin/env python3
"""Keystrokes through GNOME's own remote desktop API, when /dev/uinput is closed.

Mutter exposes org.gnome.Mutter.RemoteDesktop on the session bus: any client
of the session may open a remote desktop session there and send it evdev
keycodes, which the compositor delivers to the focused window — Wayland or
Xwayland alike, without root and without a prompt. The session dies with the
D-Bus connection that created it: hence a process that holds it for the length
of a dictation, rather than one call per keystroke.

Run as a standalone process with the system Python (PyGObject). Protocol, one
line each way: it first prints "ready" or "error <why>"; then every line of
evdev keycodes read on stdin ("29 47") is pressed in order, released in
reverse, and answered with "ok" or "error <why>". End of stdin stops the
session.
"""

from __future__ import annotations

import sys
import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "org.gnome.Mutter.RemoteDesktop"
OBJECT_PATH = "/org/gnome/Mutter/RemoteDesktop"
SESSION_INTERFACE = "org.gnome.Mutter.RemoteDesktop.Session"
# Keys sent right after Start are sometimes dropped: the compositor is still
# wiring its virtual keyboard up.
SETTLE_SECONDS = 0.5
HOLD_SECONDS = 0.02


class Session:
    def __init__(self) -> None:
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = self.bus.call_sync(
            BUS_NAME, OBJECT_PATH, BUS_NAME, "CreateSession", None,
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None,
        )
        self.path = reply.unpack()[0]
        self._call("Start")
        time.sleep(SETTLE_SECONDS)

    def _call(self, method: str, arguments: GLib.Variant | None = None) -> None:
        self.bus.call_sync(
            BUS_NAME, self.path, SESSION_INTERFACE, method, arguments,
            None, Gio.DBusCallFlags.NONE, -1, None,
        )

    def key(self, code: int, pressed: bool) -> None:
        self._call("NotifyKeyboardKeycode", GLib.Variant("(ub)", (code, pressed)))

    def press(self, codes: list[int]) -> None:
        for code in codes:
            self.key(code, True)
        time.sleep(HOLD_SECONDS)
        for code in reversed(codes):
            self.key(code, False)

    def stop(self) -> None:
        try:
            self._call("Stop")
        except GLib.Error:
            pass


def answer(line: str) -> None:
    print(line, flush=True)


def main() -> int:
    try:
        session = Session()
    except GLib.Error as error:
        answer(f"error {error.message}")
        return 1
    answer("ready")
    try:
        for line in sys.stdin:
            try:
                codes = [int(code) for code in line.split()]
            except ValueError:
                answer(f"error unreadable keycodes: {line.strip()!r}")
                continue
            try:
                session.press(codes)
            except GLib.Error as error:
                answer(f"error {error.message}")
                continue
            answer("ok")
    finally:
        session.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
