"""Headless win-rate simulator: plays full games of 2048 with no macOS
app involved, so the search and the Jev escalation logic can be
measured and tuned with real evidence instead of guesswork.

Usage:
    python -m jev2048.simulate --games 200 --mode hybrid --seed 0
    python -m jev2048.simulate --games 30 --mode hybrid --real-jev

Without --real-jev, Jev calls are replaced by a mock that answers with
the search's own top candidate - this exercises the escalation logic
and its timing without touching the network or costing anything.
--real-jev calls the live TypeSafe API and asks for confirmation first.
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field

from jev2048 import game, jev


@dataclass
class GameResult:
    reached_2048: bool
    max_tile: int
    moves: int
    source_counts: Counter = field(default_factory=Counter)
    move_times: list[float] = field(default_factory=list)


def _mock_ask(payload: dict, timeout: float, retries: int) -> jev.JevDecision:
    """Stands in for the real API: always agrees with the search's own
    top candidate (the first entry sent), at a fixed moderate confidence."""
    candidates = payload["state"]["candidate_moves"]
    direction = candidates[0]["direction"]
    return jev.JevDecision(
        direction=direction,
        confidence=0.8,
        probabilities={direction: 0.8},
        source="jev",
    )


def play_game(mode: str, rng: random.Random, ask, time_budget: float) -> GameResult:
    grid = game.empty_grid()
    grid = game.spawn_random_tile(grid, rng)
    grid = game.spawn_random_tile(grid, rng)

    moves = 0
    source_counts: Counter = Counter()
    move_times: list[float] = []

    while True:
        outcomes = game.evaluate_all_moves(grid)
        if not outcomes:
            break

        start = time.monotonic()
        decision = jev.choose_move(
            grid, outcomes, mode=mode, ask=ask, search_time_budget=time_budget
        )
        move_times.append(time.monotonic() - start)
        source_counts[decision.source] += 1

        new_grid, moved, _ = game.apply_move(grid, decision.direction)
        if not moved:
            # Shouldn't happen (choose_move only returns legal moves);
            # treat as game over rather than looping forever.
            break
        grid = new_grid
        moves += 1
        grid = game.spawn_random_tile(grid, rng)

    max_value, _ = game.max_tile(grid)
    return GameResult(
        reached_2048=max_value >= 2048,
        max_tile=max_value,
        moves=moves,
        source_counts=source_counts,
        move_times=move_times,
    )


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(p * (len(ordered) - 1)))))
    return ordered[k]


def _report(mode: str, results: list[GameResult]) -> None:
    n = len(results)
    wins = sum(1 for r in results if r.reached_2048)
    max_tiles = Counter(r.max_tile for r in results)
    all_times = [t for r in results for t in r.move_times]
    total_jev_calls = sum(r.source_counts.get("jev", 0) for r in results)
    source_totals: Counter = Counter()
    for r in results:
        source_totals.update(r.source_counts)

    print(f"\n=== {n} games, mode={mode} ===")
    print(f"Win rate (reached 2048): {wins}/{n} ({100 * wins / n:.1f}%)")
    print("Largest tile reached, by frequency:")
    for value, count in sorted(max_tiles.items(), reverse=True):
        print(f"  {value:>6}: {count} ({100 * count / n:.1f}%)")
    print(f"Average moves per game: {statistics.mean(r.moves for r in results):.1f}")
    print(
        f"Time per move: p50={_percentile(all_times, 0.5) * 1000:.1f}ms "
        f"p95={_percentile(all_times, 0.95) * 1000:.1f}ms"
    )
    print(f"Jev calls per game: {total_jev_calls / n:.2f}")
    print("Decisions by source:")
    for source, count in source_totals.most_common():
        print(f"  {source}: {count} ({100 * count / sum(source_totals.values()):.1f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Headless 2048 simulator for measuring and tuning Jev's search."
    )
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--mode", choices=["search", "hybrid", "jev"], default="hybrid")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--time-budget",
        type=float,
        default=0.03,
        help=(
            "Per-move search time budget in seconds. Live play uses "
            "search.TIME_BUDGET_S (0.15s by default); batch simulation "
            "defaults lower so hundreds of games finish in a reasonable time."
        ),
    )
    parser.add_argument(
        "--real-jev",
        action="store_true",
        help="Call the real TypeSafe API instead of a mock (uses your API key and costs money).",
    )
    args = parser.parse_args()

    if args.mode == "search" and args.real_jev:
        print("--real-jev has no effect in --mode search (Jev is never called).")

    ask = _mock_ask
    if args.real_jev:
        reply = input(
            f"This will make real TypeSafe API calls for up to {args.games} games. Continue? [y/N] "
        )
        if reply.strip().lower() != "y":
            print("Aborted.")
            return
        ask = None  # choose_move's default: the real HTTP call

    rng = random.Random(args.seed)
    results = [
        play_game(args.mode, rng, ask, args.time_budget) for _ in range(args.games)
    ]
    _report(args.mode, results)


if __name__ == "__main__":
    main()
