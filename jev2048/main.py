"""Entry point: global hotkey toggle + play loop + UI wiring.

Open 2048 Game yourself, then press Ctrl+Option+J to have Jev start
choosing moves; press it again to stop. The loop also stops itself if
the game ends, or pauses if focus moves away from 2048 Game and resumes
once it's focused again.
"""

from __future__ import annotations

import sys
import threading
import time

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from PyObjCTools import AppHelper
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGEventKeyDown,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

from jev2048 import board
from jev2048 import input as jinput
from jev2048 import search  # noqa: F401  (imported to warm up its lookup tables)
from jev2048 import ui
from jev2048.game import evaluate_all_moves
from jev2048.jev import MODE, JevError, choose_move

HOTKEY_KEYCODE = 38  # virtual keycode for 'J' on a standard ANSI layout
HOTKEY_MODIFIERS = kCGEventFlagMaskControl | kCGEventFlagMaskAlternate
_RELEVANT_MODIFIER_MASK = (
    kCGEventFlagMaskControl
    | kCGEventFlagMaskAlternate
    | kCGEventFlagMaskCommand
    | kCGEventFlagMaskShift
)

MOVE_INTERVAL = 0.35  # lets the slide/merge animation settle between moves
PAUSED_POLL_INTERVAL = 0.5


class JevPlayer:
    """Owns the running state and the background play loop. All public
    methods are safe to call from the main thread (the hotkey callback)."""

    def __init__(self):
        self._widget = ui.StatusWidget(on_quit=self.shutdown)
        self._reader = board.BoardReader()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------

    def toggle(self):
        with self._lock:
            if self._running.is_set():
                self._stop_locked()
            else:
                self._start_locked()

    def _start_locked(self):
        if not jinput.is_2048_running():
            self._widget.set_running(True)
            self._widget.show_message("2048 Game isn't open")
            AppHelper.callLater(1.5, self._widget.set_running, False)
            return
        self._running.set()
        self._widget.set_running(True)
        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._thread.start()

    def _stop_locked(self):
        self._running.clear()
        self._widget.set_running(False)

    def shutdown(self):
        self._running.clear()
        AppHelper.stopEventLoop()

    # -- play loop (runs on a background thread) -------------------------

    def _play_loop(self):
        move_count = 0
        while self._running.is_set():
            if not jinput.is_2048_frontmost():
                self._widget.show_message("Paused \u2013 2048 Game lost focus")
                time.sleep(PAUSED_POLL_INTERVAL)
                continue

            try:
                snapshot = self._reader.read_stable()
            except board.BoardUnavailable:
                time.sleep(0.3)
                continue

            if snapshot.game_over:
                self._widget.show_message(f"Game over after {move_count} moves")
                time.sleep(1.2)
                with self._lock:
                    self._stop_locked()
                return

            outcomes = evaluate_all_moves(snapshot.grid)
            if not outcomes:
                # Belt-and-suspenders: the board has no legal moves even
                # though the "Game over!" text wasn't detected.
                self._widget.show_message(f"No legal moves after {move_count} moves")
                time.sleep(1.2)
                with self._lock:
                    self._stop_locked()
                return

            try:
                decision = choose_move(snapshot.grid, outcomes)
            except JevError as exc:
                self._widget.show_message(f"Jev error: {exc}")
                time.sleep(1.5)
                with self._lock:
                    self._stop_locked()
                return

            try:
                jinput.send_move(decision.direction)
            except jinput.NotFrontmost:
                continue

            move_count += 1
            self._widget.update_status(
                move_count, decision.direction, decision.confidence, decision.source
            )
            time.sleep(MOVE_INTERVAL)


def _hotkey_matches(event) -> bool:
    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
    if keycode != HOTKEY_KEYCODE:
        return False
    flags = CGEventGetFlags(event) & _RELEVANT_MODIFIER_MASK
    return flags == HOTKEY_MODIFIERS


def main():
    if not jinput.accessibility_trusted():
        print(
            "Accessibility permission is required.\n"
            "Open System Settings > Privacy & Security > Accessibility, enable it "
            "for your terminal app (or the python3 binary running this), then run "
            "this again.",
            file=sys.stderr,
        )
        sys.exit(1)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    player = JevPlayer()

    def tap_callback(proxy, event_type, event, refcon):
        if event_type == kCGEventKeyDown and _hotkey_matches(event):
            player.toggle()
            return None  # swallow the hotkey so it doesn't reach other apps
        return event

    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionDefault,
        CGEventMaskBit(kCGEventKeyDown),
        tap_callback,
        None,
    )
    if tap is None:
        print(
            "Could not create the global hotkey listener. Double-check "
            "Accessibility access is granted, then try again.",
            file=sys.stderr,
        )
        sys.exit(1)

    run_loop_source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), run_loop_source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)

    print(f"Jev 2048 helper is running. (mode: {MODE}; set JEV_MODE=search|hybrid|jev to change)")
    print("Open 2048 Game, then press Ctrl+Option+J to start/stop Jev playing.")

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
