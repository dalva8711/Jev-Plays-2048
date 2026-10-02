"""Pure 2048 game rules.

The board is represented as a 4x4 list of rows, each a list of 4 ints,
0 meaning empty. Row 0 is the top row, column 0 is the left column -
this matches how the board looks on screen and how `board.py` builds it.

All the move/merge arithmetic, legality checks, and heuristics live here
in plain code; the only thing we ask Jev to do is pick between the
legal options described by this module.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

Grid = list[list[int]]

DIRECTIONS = ("up", "down", "left", "right")

ANCHOR = (3, 0)  # bottom-left; must match jev2048.search.ANCHOR


def empty_grid() -> Grid:
    return [[0, 0, 0, 0] for _ in range(4)]


def _compress_merge_line(line: list[int]) -> tuple[list[int], int]:
    """Slide a single line (list of 4 ints) to the left and merge equal
    neighbors once each, 2048-style. Returns (new_line, score_gained)."""
    values = [v for v in line if v != 0]
    merged: list[int] = []
    gained = 0
    i = 0
    while i < len(values):
        if i + 1 < len(values) and values[i] == values[i + 1]:
            new_val = values[i] * 2
            merged.append(new_val)
            gained += new_val
            i += 2
        else:
            merged.append(values[i])
            i += 1
    merged.extend([0] * (4 - len(merged)))
    return merged, gained


def _transpose(grid: Grid) -> Grid:
    return [list(row) for row in zip(*grid)]


def _reverse_rows(grid: Grid) -> Grid:
    return [list(reversed(row)) for row in grid]


def apply_move(grid: Grid, direction: str) -> tuple[Grid, bool, int]:
    """Apply a move to `grid` without mutating it.

    Returns (new_grid, moved, score_gained). `moved` is False when the
    move would not change the board at all (an illegal/no-op move).
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"Unknown direction: {direction}")

    if direction == "left":
        working = grid
    elif direction == "right":
        working = _reverse_rows(grid)
    elif direction == "up":
        working = _transpose(grid)
    else:  # down
        working = _reverse_rows(_transpose(grid))

    new_rows: list[list[int]] = []
    total_gained = 0
    for row in working:
        new_row, gained = _compress_merge_line(row)
        new_rows.append(new_row)
        total_gained += gained

    if direction == "left":
        new_grid = new_rows
    elif direction == "right":
        new_grid = _reverse_rows(new_rows)
    elif direction == "up":
        new_grid = _transpose(new_rows)
    else:  # down
        new_grid = _transpose(_reverse_rows(new_rows))

    moved = new_grid != grid
    return new_grid, moved, total_gained


def legal_moves(grid: Grid) -> list[str]:
    return [d for d in DIRECTIONS if apply_move(grid, d)[1]]


def is_game_over(grid: Grid) -> bool:
    return len(legal_moves(grid)) == 0


def empty_cells(grid: Grid) -> int:
    return sum(1 for row in grid for v in row if v == 0)


def _anchor_distance(pos: tuple[int, int]) -> int:
    r, c = pos
    return abs(r - ANCHOR[0]) + abs(c - ANCHOR[1])


def max_tile(grid: Grid) -> tuple[int, tuple[int, int]]:
    """Returns (value, (row, col)) of the largest tile. Ties prefer the
    position closest to ANCHOR, so the reported "largest tile" doesn't
    flip between equal-valued tiles as the board shifts."""
    best_val = -1
    best_pos = (0, 0)
    best_dist = 0
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            if v < best_val:
                continue
            dist = _anchor_distance((r, c))
            if v > best_val or dist < best_dist:
                best_val = v
                best_pos = (r, c)
                best_dist = dist
    return best_val, best_pos


def spawn_random_tile(grid: Grid, rng: random.Random | None = None) -> Grid:
    """Returns a new grid with one tile (2 with probability 0.9, 4 with
    probability 0.1) placed in a random empty cell. Raises ValueError if
    the board is full."""
    rand = rng or random
    cells = [(r, c) for r in range(4) for c in range(4) if grid[r][c] == 0]
    if not cells:
        raise ValueError("No empty cells to spawn a tile into")
    row, col = rand.choice(cells)
    value = 2 if rand.random() < 0.9 else 4
    new_grid = [r[:] for r in grid]
    new_grid[row][col] = value
    return new_grid


CORNERS = {(0, 0), (0, 3), (3, 0), (3, 3)}


@dataclass
class MoveOutcome:
    direction: str
    grid: Grid
    score_gained: int
    empty_after: int
    max_tile_value: int
    max_tile_position: tuple[int, int]
    max_tile_in_corner: bool
    monotonic_rows: int = field(default=0)
    max_tile_in_anchor: bool = False
    monotonic_cols: int = 0


def _row_is_monotonic(row: list[int]) -> bool:
    nonzero = [v for v in row if v != 0]
    return nonzero == sorted(nonzero) or nonzero == sorted(nonzero, reverse=True)


def _monotonic_columns(grid: Grid) -> int:
    return sum(
        1 for c in range(4) if _row_is_monotonic([grid[r][c] for r in range(4)])
    )


def evaluate_move(grid: Grid, direction: str) -> MoveOutcome | None:
    """Simulate `direction` and summarize the resulting board. Returns
    None if the move is illegal (changes nothing)."""
    new_grid, moved, gained = apply_move(grid, direction)
    if not moved:
        return None
    value, pos = max_tile(new_grid)
    monotonic = sum(1 for row in new_grid if _row_is_monotonic(row))
    return MoveOutcome(
        direction=direction,
        grid=new_grid,
        score_gained=gained,
        empty_after=empty_cells(new_grid),
        max_tile_value=value,
        max_tile_position=pos,
        max_tile_in_corner=pos in CORNERS,
        monotonic_rows=monotonic,
        max_tile_in_anchor=(pos == ANCHOR),
        monotonic_cols=_monotonic_columns(new_grid),
    )


def evaluate_all_moves(grid: Grid) -> list[MoveOutcome]:
    outcomes = []
    for d in DIRECTIONS:
        outcome = evaluate_move(grid, d)
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes
