"""Sends arrow-key presses to the 2048 Game app.

A key is only ever posted while "2048 Game" is the frontmost (focused)
app, so this can't steal a keystroke meant for something else the user
is doing, and stops safely if focus moves away mid-game.
"""

from __future__ import annotations

import time

from ApplicationServices import AXIsProcessTrusted
from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap
from Quartz import NSWorkspace

APP_NAME = "2048 Game"
BUNDLE_ID = "com.kfir.mac2048"

KEY_CODES = {
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
}


class NotFrontmost(Exception):
    """2048 Game isn't the focused app right now, so no key was sent."""


def is_2048_frontmost() -> bool:
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    if front is None:
        return False
    return front.bundleIdentifier() == BUNDLE_ID or front.localizedName() == APP_NAME


def is_2048_running() -> bool:
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == BUNDLE_ID or app.localizedName() == APP_NAME:
            return True
    return False


def accessibility_trusted() -> bool:
    """True once the user has granted this process (or its parent
    terminal/python interpreter) Accessibility access in System
    Settings > Privacy & Security > Accessibility."""
    return bool(AXIsProcessTrusted())


def send_move(direction: str, hold: float = 0.02) -> None:
    """Send one arrow-key press for `direction`.

    Raises NotFrontmost if 2048 Game isn't the focused app at the moment
    of sending; callers should treat that as a reason to pause rather
    than retry blindly.
    """
    if direction not in KEY_CODES:
        raise ValueError(f"Unknown direction: {direction!r}")
    if not is_2048_frontmost():
        raise NotFrontmost("2048 Game is not the frontmost app")

    code = KEY_CODES[direction]
    key_down = CGEventCreateKeyboardEvent(None, code, True)
    key_up = CGEventCreateKeyboardEvent(None, code, False)
    CGEventPost(kCGHIDEventTap, key_down)
    time.sleep(hold)
    CGEventPost(kCGHIDEventTap, key_up)


if __name__ == "__main__":
    # Quick manual check: `python -m jev2048.input` sends a single "left"
    # press to a focused 2048 Game window.
    print("accessibility_trusted:", accessibility_trusted())
    print("2048 running:", is_2048_running())
    print("2048 frontmost:", is_2048_frontmost())
    if is_2048_frontmost():
        send_move("left")
        print("sent left")
