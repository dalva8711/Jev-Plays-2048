"""TypeSafe / Jev client: picks the best legal move for a given board.

All the game arithmetic (what each move would actually do to the board)
is computed in `game.py`. The multi-move lookahead (what each move is
likely to lead to several turns from now, accounting for random tile
spawns) is computed in `search.py`. Jev's job is narrower: break ties
between moves that the search finds genuinely close, using judgment
about shape and strategy that's hard to reduce to a single number. See
https://docs.typesafe.ai/api.md for the HTTP contract this follows.

Three modes, controlled by `JEV_MODE` (or the `mode` argument):
  - "search": always play the search's top move; never call Jev.
  - "jev": always ask Jev, over every legal move (today's behavior,
    kept for comparison).
  - "hybrid" (default): let the search decide the clear cases on its
    own, and ask Jev only to break close calls among safe moves.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

from jev2048 import search
from jev2048.game import Grid, MoveOutcome

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

# How much better the search's top move must be than the runner-up
# (relative to the top move's expected value) to play it outright
# without asking Jev.
MARGIN = 0.03

# How many of the search's top (safe) moves to show Jev when a call is
# actually made.
TOP_K = 3

# Below this confidence, in "hybrid" mode, prefer the search's top move
# over Jev's answer.
MIN_JEV_CONFIDENCE = 0.55

# "search", "jev", or "hybrid"; overridable per-call via choose_move(mode=...).
MODE = os.environ.get("JEV_MODE", "hybrid")

MOVE_DESCRIPTIONS = {
    "up": "Slide all tiles up.",
    "down": "Slide all tiles down.",
    "left": "Slide all tiles left.",
    "right": "Slide all tiles right.",
}

INSTRUCTIONS = (
    "You are choosing the next move in a game of 2048. The board has a fixed "
    "anchor corner, named in `anchor_corner`; keep the largest tile there, with "
    "the row containing it decreasing in value away from the anchor and the next "
    "rows snaking in the same pattern. Each entry in `candidate_moves` already "
    "reflects a multi-move lookahead search, not just the immediate result: "
    "strongly prefer a lower `lookahead_rank` (1 is the search's top choice) "
    "unless taking it would clearly break the anchored snake pattern. Never "
    "choose a move with `survives_every_possible_spawn` false while another "
    "candidate has it true - that move can lose the game on the very next random "
    "tile. Among otherwise close options, prefer a larger "
    "`worst_case_empty_cells_after_next_move`."
)


class JevError(Exception):
    """Raised for a definitive TypeSafe API failure (bad key, bad request)
    that a caller should surface rather than silently work around."""


class JevUnavailable(Exception):
    """Raised internally when the API is transiently unreachable (network
    errors, 429/529) even after retries. Callers of `choose_move` never
    see this; it's caught and turned into a search-based fallback."""


@dataclass
class JevDecision:
    direction: str
    confidence: float
    probabilities: dict[str, float]
    source: str  # "jev", "trivial", "search", or "fallback"


def _api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise JevError(
            "TYPESAFE_API_KEY is not set. Add it to .env in the project root."
        )
    return key


def _grid_rows(grid: Grid) -> list[list[int]]:
    return [row[:] for row in grid]


def _build_state(
    grid: Grid,
    candidates: list[MoveOutcome],
    ranked: list[MoveOutcome],
    analyses: dict[str, search.MoveAnalysis],
) -> dict:
    rank_by_direction = {o.direction: i + 1 for i, o in enumerate(ranked)}
    best_value = analyses[ranked[0].direction].expected_value
    return {
        "board": _grid_rows(grid),
        "note": (
            "4x4 2048 board as rows top-to-bottom, columns left-to-right, "
            "0 means an empty cell."
        ),
        "anchor_corner": (
            "bottom-left (row 3, column 0); the largest tile should stay there."
        ),
        "candidate_moves": [
            {
                "direction": o.direction,
                "resulting_board": _grid_rows(o.grid),
                "points_gained": o.score_gained,
                "empty_cells_after": o.empty_after,
                "largest_tile_value": o.max_tile_value,
                "largest_tile_in_anchor_corner": o.max_tile_in_anchor,
                "lookahead_rank": rank_by_direction[o.direction],
                "lookahead_value_vs_best": (
                    analyses[o.direction].expected_value / best_value
                    if best_value
                    else 1.0
                ),
                "survives_every_possible_spawn": analyses[o.direction].survives_every_spawn,
                "worst_case_empty_cells_after_next_move": analyses[
                    o.direction
                ].worst_case_empty_after_next_move,
            }
            for o in candidates
        ],
    }


def _search_decision(ranked: list[MoveOutcome], source: str = "search") -> JevDecision:
    top = ranked[0]
    return JevDecision(direction=top.direction, confidence=0.0, probabilities={}, source=source)


def _fallback_decision(grid: Grid, outcomes: list[MoveOutcome]) -> JevDecision:
    """Used only when the TypeSafe API call fails after retries. Plays
    the search's top move rather than guessing with a fixed priority."""
    analyses = {a.direction: a for a in search.analyze(grid)}
    ranked = sorted(outcomes, key=lambda o: analyses[o.direction].expected_value, reverse=True)
    return _search_decision(ranked, source="fallback")


def _ask_typesafe(payload: dict, timeout: float, retries: int) -> JevDecision:
    """Makes the real HTTP call, with retries and backoff for transient
    failures. Raises JevUnavailable once retries are exhausted, and
    JevError for a definitive rejection (bad key, bad request)."""
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    backoff = 1.0
    for attempt in range(retries + 1):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException:
            if attempt == retries:
                raise JevUnavailable()
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code in (429, 529):
            if attempt == retries:
                raise JevUnavailable()
            time.sleep(backoff)
            backoff *= 2
            continue
        if resp.status_code == 401:
            raise JevError("TypeSafe rejected the API key (401 Unauthorized).")
        if resp.status_code >= 400:
            raise JevError(f"TypeSafe API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        answer = data["answers"]["best_move"]
        return JevDecision(
            direction=answer["choice"],
            confidence=answer.get("confidence", 0.0),
            probabilities=answer.get("probabilities", {}),
            source="jev",
        )

    raise JevUnavailable()  # unreachable, keeps type checkers happy


def choose_move(
    grid: Grid,
    outcomes: list[MoveOutcome],
    timeout: float = 15.0,
    retries: int = 3,
    mode: str | None = None,
    ask=None,
    search_time_budget: float | None = None,
) -> JevDecision:
    """Picks the next move for `grid` given `outcomes` (the legal moves,
    as produced by `game.evaluate_all_moves`).

    Runs the expectimax search from `search.py` first. In "hybrid" mode
    (the default), clear-cut decisions are played without calling Jev
    at all; Jev is only asked to break genuinely close calls among safe
    moves, and its answer is only trusted above `MIN_JEV_CONFIDENCE`.

    `ask(payload, timeout, retries) -> JevDecision` defaults to the real
    HTTP call; tests and the offline simulator pass a stand-in so neither
    needs the API.

    `search_time_budget` overrides `search.TIME_BUDGET_S` for this call;
    the offline simulator uses a smaller budget so it can play hundreds
    of games without each move taking as long as live play allows.

    Raises JevError for a definitive API failure (missing/invalid key,
    or a rejected request). Transient failures fall back to the
    search's top move rather than stalling the game.
    """
    if not outcomes:
        raise JevError("No legal moves to choose from")
    if len(outcomes) == 1:
        only = outcomes[0]
        return JevDecision(
            direction=only.direction,
            confidence=1.0,
            probabilities={only.direction: 1.0},
            source="trivial",
        )

    mode = mode or MODE
    time_budget = search_time_budget if search_time_budget is not None else search.TIME_BUDGET_S
    analyses = {a.direction: a for a in search.analyze(grid, time_budget=time_budget)}
    ranked = sorted(outcomes, key=lambda o: analyses[o.direction].expected_value, reverse=True)

    if mode == "search":
        return _search_decision(ranked)

    if mode == "jev":
        candidates = ranked
    else:  # "hybrid"
        safe = [o for o in ranked if analyses[o.direction].survives_every_spawn]
        if len(safe) <= 1:
            # Either exactly one move survives every possible spawn, or
            # none do (a forced loss either way) - no need to ask Jev.
            return _search_decision(safe or ranked)

        best = analyses[ranked[0].direction].expected_value
        second = analyses[ranked[1].direction].expected_value
        if best != 0 and (best - second) / abs(best) >= MARGIN:
            return _search_decision(ranked)

        candidates = safe[:TOP_K]

    payload = {
        "state": _build_state(grid, candidates, ranked, analyses),
        "model": MODEL,
        "questions": {
            "best_move": {
                "type": "choice",
                "instructions": INSTRUCTIONS,
                "criteria": {o.direction: MOVE_DESCRIPTIONS[o.direction] for o in candidates},
            }
        },
    }

    requester = ask or _ask_typesafe
    try:
        decision = requester(payload, timeout, retries)
    except JevUnavailable:
        return _fallback_decision(grid, outcomes)

    if mode == "hybrid" and decision.confidence < MIN_JEV_CONFIDENCE:
        return _search_decision(ranked)

    return decision


if __name__ == "__main__":
    # Quick manual check: `python -m jev2048.jev` sends one sample board
    # to TypeSafe and prints the decision, to confirm the request/response
    # shape against the live API.
    from jev2048.game import evaluate_all_moves

    sample_grid = [
        [2, 4, 8, 16],
        [4, 0, 0, 32],
        [0, 0, 0, 64],
        [0, 0, 2, 128],
    ]
    sample_outcomes = evaluate_all_moves(sample_grid)
    decision = choose_move(sample_grid, sample_outcomes)
    print(decision)
