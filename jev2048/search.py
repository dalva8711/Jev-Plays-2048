"""Expectimax search for 2048: how far Jev's moves are actually looked
ahead before any API call happens.

The board is packed into a 64-bit integer, 4 bits per cell holding the
tile's exponent (0 for empty, 1 for a 2, 2 for a 4, ...). All 65536
possible 16-bit rows are precomputed once at import time into lookup
tables for move results, scores, and heuristic components, so applying
a move or scoring a board during search is a handful of table lookups
rather than a loop over Python lists.

`analyze()` is the public entry point: given a grid (the same
list-of-lists shape as `game.py`), it runs a time-budgeted expectimax
search and returns one `MoveAnalysis` per legal move, best first.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from jev2048.game import DIRECTIONS, Grid

ANCHOR = (3, 0)  # bottom-left; must match jev2048.game.ANCHOR

# Rank of each cell in the snake path anchored at ANCHOR: 0 is the
# anchor itself, and rank increases moving away from it along the
# snake (bottom row right-to-left, then up, alternating direction).
SNAKE_RANK = [
    [15, 14, 13, 12],
    [8, 9, 10, 11],
    [7, 6, 5, 4],
    [0, 1, 2, 3],
]

PROB_CUTOFF = 1e-4
TIME_BUDGET_S = 0.15
LOST_SCORE = -1e9


@dataclass
class Weights:
    lost_base: float = 200_000.0
    empty: float = 270.0
    merge: float = 700.0
    mono: float = 47.0
    line_sum: float = 11.0
    gradient: float = 4.0
    corner: float = 8.0
    smooth: float = 30.0


WEIGHTS = Weights()


@dataclass
class MoveAnalysis:
    direction: str
    expected_value: float
    survives_every_spawn: bool
    worst_case_empty_after_next_move: int
    depth_reached: int


# -- board encoding ------------------------------------------------------


def encode(grid: Grid) -> int:
    board = 0
    for r in range(4):
        for c in range(4):
            value = grid[r][c]
            exp = value.bit_length() - 1 if value else 0
            board |= exp << (4 * (r * 4 + c))
    return board


def decode(board: int) -> Grid:
    grid = [[0, 0, 0, 0] for _ in range(4)]
    for r in range(4):
        for c in range(4):
            exp = (board >> (4 * (r * 4 + c))) & 0xF
            grid[r][c] = 0 if exp == 0 else 1 << exp
    return grid


def _row_bits(board: int, r: int) -> int:
    return (board >> (16 * r)) & 0xFFFF


def _nibbles(bits: int) -> tuple[int, int, int, int]:
    return (bits & 0xF, (bits >> 4) & 0xF, (bits >> 8) & 0xF, (bits >> 12) & 0xF)


def _pack(nibbles: tuple[int, int, int, int]) -> int:
    a, b, c, d = nibbles
    return a | (b << 4) | (c << 8) | (d << 12)


def transpose(board: int) -> int:
    new_board = 0
    for r in range(4):
        for c in range(4):
            exp = (board >> (4 * (r * 4 + c))) & 0xF
            new_board |= exp << (4 * (c * 4 + r))
    return new_board


def _empty_cells_board(board: int) -> list[int]:
    return [i for i in range(16) if (board >> (4 * i)) & 0xF == 0]


# -- row tables, built once at import time --------------------------------


def _merge_left(nibbles: tuple[int, ...]) -> tuple[tuple[int, int, int, int], int]:
    values = [n for n in nibbles if n != 0]
    merged: list[int] = []
    gained = 0
    i = 0
    while i < len(values):
        if i + 1 < len(values) and values[i] == values[i + 1]:
            new_exp = values[i] + 1
            merged.append(new_exp)
            gained += 1 << new_exp
            i += 2
        else:
            merged.append(values[i])
            i += 1
    merged.extend([0] * (4 - len(merged)))
    return (merged[0], merged[1], merged[2], merged[3]), gained


def _line_monotonicity_violation(nibbles: tuple[int, ...]) -> float:
    """Soft monotonicity measure: whichever direction (increasing or
    decreasing) the line is closer to already following, the violation
    is how far it is from that direction, weighted by exponent^4."""
    inc = 0.0
    dec = 0.0
    for a, b in zip(nibbles, nibbles[1:]):
        if a < b:
            inc += b**4 - a**4
        elif b < a:
            dec += a**4 - b**4
    return min(inc, dec)


ROW_LEFT_RESULT: list[int] = [0] * 65536
ROW_LEFT_SCORE: list[int] = [0] * 65536
ROW_RIGHT_RESULT: list[int] = [0] * 65536
ROW_RIGHT_SCORE: list[int] = [0] * 65536
ROW_EMPTY: list[int] = [0] * 65536
ROW_MERGE: list[int] = [0] * 65536
ROW_MONO: list[float] = [0.0] * 65536
ROW_SUM: list[float] = [0.0] * 65536


def _build_tables() -> None:
    for bits in range(65536):
        nibbles = _nibbles(bits)

        merged, gained = _merge_left(nibbles)
        ROW_LEFT_RESULT[bits] = _pack(merged)
        ROW_LEFT_SCORE[bits] = gained

        reversed_nibbles = nibbles[::-1]
        rev_merged, rev_gained = _merge_left(reversed_nibbles)
        ROW_RIGHT_RESULT[bits] = _pack(rev_merged[::-1])
        ROW_RIGHT_SCORE[bits] = rev_gained

        ROW_EMPTY[bits] = sum(1 for n in nibbles if n == 0)
        ROW_MERGE[bits] = sum(
            1 for i in range(3) if nibbles[i] != 0 and nibbles[i] == nibbles[i + 1]
        )
        ROW_MONO[bits] = _line_monotonicity_violation(nibbles)
        ROW_SUM[bits] = sum(n**3.5 for n in nibbles if n)


_build_tables()


# -- applying moves to an encoded board ------------------------------------


def _apply_horizontal(
    board: int, result_table: list[int], score_table: list[int]
) -> tuple[int, int, bool]:
    new_board = 0
    total_score = 0
    moved = False
    for r in range(4):
        bits = _row_bits(board, r)
        new_bits = result_table[bits]
        total_score += score_table[bits]
        if new_bits != bits:
            moved = True
        new_board |= new_bits << (16 * r)
    return new_board, total_score, moved


def apply_move(board: int, direction: str) -> tuple[int, int, bool]:
    """Returns (new_board, score_gained, moved)."""
    if direction == "left":
        return _apply_horizontal(board, ROW_LEFT_RESULT, ROW_LEFT_SCORE)
    if direction == "right":
        return _apply_horizontal(board, ROW_RIGHT_RESULT, ROW_RIGHT_SCORE)
    if direction == "up":
        new_board, score, moved = _apply_horizontal(
            transpose(board), ROW_LEFT_RESULT, ROW_LEFT_SCORE
        )
        return transpose(new_board), score, moved
    if direction == "down":
        new_board, score, moved = _apply_horizontal(
            transpose(board), ROW_RIGHT_RESULT, ROW_RIGHT_SCORE
        )
        return transpose(new_board), score, moved
    raise ValueError(f"Unknown direction: {direction}")


def _legal_boards(board: int) -> list[tuple[str, int, int]]:
    """Returns (direction, new_board, score_gained) for each legal move."""
    results = []
    for d in DIRECTIONS:
        new_board, score, moved = apply_move(board, d)
        if moved:
            results.append((d, new_board, score))
    return results


# -- heuristic --------------------------------------------------------------


def heuristic(board: int) -> float:
    total = WEIGHTS.lost_base

    for r in range(4):
        bits = _row_bits(board, r)
        total += WEIGHTS.empty * ROW_EMPTY[bits]
        total += WEIGHTS.merge * ROW_MERGE[bits]
        total -= WEIGHTS.mono * ROW_MONO[bits]
        total -= WEIGHTS.line_sum * ROW_SUM[bits]

    transposed = transpose(board)
    for c in range(4):
        bits = _row_bits(transposed, c)
        total += WEIGHTS.empty * ROW_EMPTY[bits]
        total += WEIGHTS.merge * ROW_MERGE[bits]
        total -= WEIGHTS.mono * ROW_MONO[bits]
        total -= WEIGHTS.line_sum * ROW_SUM[bits]

    exps = [0] * 16
    max_exp = 0
    max_pos = (0, 0)
    gradient = 0.0
    for r in range(4):
        for c in range(4):
            exp = (board >> (4 * (r * 4 + c))) & 0xF
            exps[r * 4 + c] = exp
            if exp > max_exp:
                max_exp = exp
                max_pos = (r, c)
            if exp:
                gradient += (1 << exp) * (0.5 ** SNAKE_RANK[r][c])
    total += WEIGHTS.gradient * gradient
    if max_exp and max_pos != ANCHOR:
        total -= WEIGHTS.corner * (1 << max_exp)

    smooth = 0.0
    for r in range(4):
        for c in range(3):
            smooth += abs(exps[r * 4 + c] - exps[r * 4 + c + 1])
    for c in range(4):
        for r in range(3):
            smooth += abs(exps[r * 4 + c] - exps[(r + 1) * 4 + c])
    total -= WEIGHTS.smooth * smooth

    return total


# -- expectimax --------------------------------------------------------------


class _TimeUp(Exception):
    """Raised to unwind a search pass once its deadline has passed. Caught
    by `analyze()`, which then keeps the previous, fully-completed depth's
    result rather than a half-computed one."""


def expectimax_player(board: int, depth: int, cache: dict, deadline: float) -> float:
    # Checked here (not in expectimax_chance) because every chance branch
    # calls back into this function, so this alone gives fine-grained
    # coverage without timing every single node.
    if time.monotonic() > deadline:
        raise _TimeUp()

    key = (board, depth, "p")
    if key in cache:
        return cache[key]
    moves = _legal_boards(board)
    if not moves:
        value = LOST_SCORE
    elif depth <= 0:
        value = max(heuristic(nb) for _, nb, _ in moves)
    else:
        value = max(expectimax_chance(nb, depth, cache, deadline) for _, nb, _ in moves)
    cache[key] = value
    return value


def expectimax_chance(
    board: int, depth: int, cache: dict, deadline: float, prob: float = 1.0
) -> float:
    key = (board, depth, "c")
    if key in cache:
        return cache[key]
    empties = _empty_cells_board(board)
    if not empties:
        value = expectimax_player(board, depth - 1, cache, deadline)
        cache[key] = value
        return value

    n = len(empties)
    total = 0.0
    for i in empties:
        for exp, p in ((1, 0.9), (2, 0.1)):
            spawned = board | (exp << (4 * i))
            branch_prob = prob * p / n
            if branch_prob < PROB_CUTOFF:
                # Too unlikely to be worth recursing into; use the static
                # heuristic for this spawn instead of expanding further.
                total += (p / n) * heuristic(spawned)
            else:
                total += (p / n) * expectimax_player(spawned, depth - 1, cache, deadline)
    cache[key] = total
    return total


def _spawn_survival(
    board: int, moves: list[tuple[str, int, int]]
) -> tuple[dict[str, bool], dict[str, int]]:
    """For each candidate move, checks every possible spawn (every empty
    cell, both tile values) and reports whether a legal move always
    remains afterward, and the worst-case empty cells the best response
    to that spawn can leave."""
    survives: dict[str, bool] = {}
    worst_case: dict[str, int] = {}

    for d, nb, _ in moves:
        empties = _empty_cells_board(nb)
        if not empties:
            after = _legal_boards(nb)
            survives[d] = len(after) > 0
            worst_case[d] = 0
            continue

        all_survive = True
        min_best_empty = None
        for i in empties:
            for exp in (1, 2):
                spawned = nb | (exp << (4 * i))
                after = _legal_boards(spawned)
                if not after:
                    all_survive = False
                    best_empty = 0
                else:
                    best_empty = max(
                        len(_empty_cells_board(ab)) for _, ab, _ in after
                    )
                if min_best_empty is None or best_empty < min_best_empty:
                    min_best_empty = best_empty
        survives[d] = all_survive
        worst_case[d] = min_best_empty if min_best_empty is not None else 0

    return survives, worst_case


def analyze(grid: Grid, time_budget: float = TIME_BUDGET_S) -> list[MoveAnalysis]:
    """Runs a time-budgeted expectimax search from `grid` and returns one
    `MoveAnalysis` per legal move, sorted best (highest expected_value)
    first. Returns an empty list if there are no legal moves.

    Uses iterative deepening: tries depth 1, then 2, then 3, ... The
    deadline is checked both between passes and, cheaply, at every
    player node within a pass, so a pass that turns out to be too
    expensive (few empty cells left means less pruning from the
    probability cutoff, so cost per ply grows quickly) gets abandoned
    partway through rather than running over budget. The result is
    always the last depth that finished completely - never a partial
    one - so deeper search happens automatically when boards are cheap
    to search (many empty cells canceled out by heavy pruning, or few
    empty cells meaning few spawn branches) and shallower search
    happens automatically when a board is expensive.
    """
    board = encode(grid)
    moves = _legal_boards(board)
    if not moves:
        return []

    deadline = time.monotonic() + time_budget

    # Always have *some* result, even if depth 1 itself can't finish
    # within the budget (shouldn't happen in practice, but a one-ply
    # lookahead is cheap enough to be a safe floor).
    best_values = {d: heuristic(nb) for d, nb, _ in moves}
    depth_reached = 0
    depth = 1
    while True:
        cache: dict = {}
        try:
            trial_values = {
                d: expectimax_chance(nb, depth, cache, deadline) for d, nb, _ in moves
            }
        except _TimeUp:
            break
        best_values = trial_values
        depth_reached = depth
        if time.monotonic() >= deadline:
            break
        depth += 1

    survives, worst_case = _spawn_survival(board, moves)

    analyses = [
        MoveAnalysis(
            direction=d,
            expected_value=best_values[d],
            survives_every_spawn=survives[d],
            worst_case_empty_after_next_move=worst_case[d],
            depth_reached=depth_reached,
        )
        for d, _, _ in moves
    ]
    analyses.sort(key=lambda a: a.expected_value, reverse=True)
    return analyses


if __name__ == "__main__":
    # Quick manual check: `python -m jev2048.search` analyzes one sample
    # board and prints the ranked moves.
    sample_grid = [
        [2, 4, 8, 16],
        [4, 0, 0, 32],
        [0, 0, 0, 64],
        [0, 0, 2, 128],
    ]
    start = time.monotonic()
    for move in analyze(sample_grid):
        print(move)
    print(f"({time.monotonic() - start:.3f}s)")
