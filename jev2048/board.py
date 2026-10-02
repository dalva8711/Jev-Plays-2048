"""Reads the live 4x4 board from the "2048 Game" macOS app.

This uses the macOS Accessibility API (the same API VoiceOver and UI
scripting rely on) to read tile values and positions directly out of the
app's WebView - no screen-pixel scraping and no cooperation needed from
the app itself. The app's own NSUserDefaults save file was tested and
found to only sync to disk on quit, not live during play, so it is not
used here.

Tile grid layout refresher: `grid[row][col]`, row 0 is the top row,
column 0 is the left column, 0 means an empty cell.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXValueGetValue,
    kAXErrorSuccess,
    kAXValueCGPointType,
)
from Quartz import NSWorkspace

from jev2048.game import Grid, empty_grid

APP_NAME = "2048 Game"
BUNDLE_ID = "com.kfir.mac2048"


class BoardUnavailable(Exception):
    """The board can't be read right now (app not running, no window,
    or the page hasn't finished rendering any tiles yet)."""


@dataclass
class BoardSnapshot:
    grid: Grid
    game_over: bool
    tile_count: int


def _ax_attr(element, name):
    err, value = AXUIElementCopyAttributeValue(element, name, None)
    if err != kAXErrorSuccess:
        return None
    return value


def _ax_point(element):
    value = _ax_attr(element, "AXPosition")
    if value is None:
        return None
    ok, point = AXValueGetValue(value, kAXValueCGPointType, None)
    return (point.x, point.y) if ok else None


class BoardReader:
    """Reads the live board for one instance of the 2048 Game app.

    Tile pixel geometry (grid origin and cell pitch) is calibrated
    automatically from whatever tiles are currently on screen, relative
    to the app window's position, so it keeps working if the window is
    moved or resized. It starts with defaults measured against the app's
    normal window size so the very first read (when the board may only
    have 1-2 tiles) still maps to the right cells.
    """

    def __init__(self):
        self._pitch_x = 121.0
        self._origin_x = 134.0
        self._pitch_y = 121.0
        self._origin_y = 242.0

    # -- process / focus helpers -------------------------------------------------

    def get_pid(self) -> int | None:
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.bundleIdentifier() == BUNDLE_ID or app.localizedName() == APP_NAME:
                return app.processIdentifier()
        return None

    def is_running(self) -> bool:
        return self.get_pid() is not None

    def is_frontmost(self) -> bool:
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is None:
            return False
        return front.bundleIdentifier() == BUNDLE_ID or front.localizedName() == APP_NAME

    # -- AX tree walking -----------------------------------------------------

    def _get_window(self):
        pid = self.get_pid()
        if pid is None:
            return None
        app_el = AXUIElementCreateApplication(pid)
        windows = _ax_attr(app_el, "AXWindows")
        if not windows:
            return None
        return windows[0]

    def _walk(self, element, tiles: list[tuple[int, tuple[float, float]]], texts: list[str]):
        role = _ax_attr(element, "AXRole")
        children = _ax_attr(element, "AXChildren") or []

        if role == "AXGroup" and len(children) == 1:
            child = children[0]
            if _ax_attr(child, "AXRole") == "AXStaticText":
                text = _ax_attr(child, "AXValue")
                if text is not None and str(text).strip().isdigit():
                    pos = _ax_point(element)
                    if pos is not None:
                        tiles.append((int(str(text).strip()), pos))
        elif role == "AXStaticText":
            text = _ax_attr(element, "AXValue")
            if text:
                texts.append(str(text))

        for child in children:
            self._walk(child, tiles, texts)

    def _recalibrate(self, window_pos, tiles):
        rel_x = sorted({round(pos[0] - window_pos[0], 1) for _, pos in tiles})
        rel_y = sorted({round(pos[1] - window_pos[1], 1) for _, pos in tiles})
        if len(rel_x) == 4:
            self._origin_x = rel_x[0]
            self._pitch_x = (rel_x[-1] - rel_x[0]) / 3
        if len(rel_y) == 4:
            self._origin_y = rel_y[0]
            self._pitch_y = (rel_y[-1] - rel_y[0]) / 3

    # -- public API -----------------------------------------------------------

    def read(self) -> BoardSnapshot:
        """Take one snapshot of the current board.

        Raises BoardUnavailable if the app isn't running, has no window,
        or no tiles could be found yet (e.g. the page is still loading).
        """
        window = self._get_window()
        if window is None:
            raise BoardUnavailable("2048 Game is not running or has no window")

        window_pos = _ax_point(window)
        if window_pos is None:
            raise BoardUnavailable("Could not read the 2048 Game window position")

        tiles: list[tuple[int, tuple[float, float]]] = []
        texts: list[str] = []
        self._walk(window, tiles, texts)

        if not tiles:
            raise BoardUnavailable("No tiles found - the board may still be loading")

        self._recalibrate(window_pos, tiles)

        grid = empty_grid()
        for value, pos in tiles:
            rel_x = pos[0] - window_pos[0]
            rel_y = pos[1] - window_pos[1]
            col = round((rel_x - self._origin_x) / self._pitch_x)
            row = round((rel_y - self._origin_y) / self._pitch_y)
            if 0 <= row < 4 and 0 <= col < 4:
                # Mid-animation reads can briefly show two overlapping
                # nodes at the same cell (the old pre-merge tile fading
                # out next to the new merged value); the larger value is
                # always the post-merge, current one.
                grid[row][col] = max(grid[row][col], value)

        game_over = any("game over" in t.lower() for t in texts)
        return BoardSnapshot(grid=grid, game_over=game_over, tile_count=len(tiles))

    def read_stable(self, attempts: int = 12, interval: float = 0.12) -> BoardSnapshot:
        """Poll until two consecutive reads agree, to ride out the
        slide/merge animation after a move. Falls back to the last
        successful read if it never fully stabilizes."""
        previous: BoardSnapshot | None = None
        last: BoardSnapshot | None = None
        last_error: Exception | None = None

        for _ in range(attempts):
            try:
                last = self.read()
            except BoardUnavailable as exc:
                last_error = exc
                last = None
                time.sleep(interval)
                continue

            if (
                previous is not None
                and previous.grid == last.grid
                and previous.game_over == last.game_over
            ):
                return last
            previous = last
            time.sleep(interval)

        if last is not None:
            return last
        raise last_error or BoardUnavailable("Could not read the board")


def format_grid(grid: Grid) -> str:
    width = max(1, max((len(str(v)) for row in grid for v in row), default=1))
    lines = []
    for row in grid:
        lines.append(" ".join(str(v).rjust(width) if v else ".".rjust(width) for v in row))
    return "\n".join(lines)


if __name__ == "__main__":
    # Quick manual check: run `python -m jev2048.board` with 2048 Game
    # open to print live board reads once per second.
    reader = BoardReader()
    while True:
        try:
            snap = reader.read()
            print(f"\ngame_over={snap.game_over} tiles={snap.tile_count}")
            print(format_grid(snap.grid))
        except BoardUnavailable as exc:
            print(f"(unavailable: {exc})")
        time.sleep(1.0)
