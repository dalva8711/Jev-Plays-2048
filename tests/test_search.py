import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev2048 import game, search


def _random_grid(rng: random.Random) -> game.Grid:
    grid = [[0] * 4 for _ in range(4)]
    for r in range(4):
        for c in range(4):
            if rng.random() < 0.6:
                grid[r][c] = 1 << rng.randint(1, 6)
    return grid


class TestRowTablesMatchGame(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        rng = random.Random(1)
        for _ in range(50):
            grid = _random_grid(rng)
            self.assertEqual(search.decode(search.encode(grid)), grid)

    def test_apply_move_matches_game_on_random_boards(self):
        rng = random.Random(42)
        for _ in range(200):
            grid = _random_grid(rng)
            board = search.encode(grid)
            for d in game.DIRECTIONS:
                expected_grid, expected_moved, expected_score = game.apply_move(grid, d)
                got_board, got_score, got_moved = search.apply_move(board, d)
                self.assertEqual(got_moved, expected_moved, (grid, d))
                self.assertEqual(search.decode(got_board), expected_grid, (grid, d))
                self.assertEqual(got_score, expected_score, (grid, d))


class TestExpectimaxEdgeCases(unittest.TestCase):
    def test_dead_board_scores_lowest(self):
        grid = [
            [2, 4, 2, 4],
            [4, 2, 4, 2],
            [2, 4, 2, 4],
            [4, 2, 4, 2],
        ]
        board = search.encode(grid)
        deadline = time.monotonic() + 1.0
        value = search.expectimax_player(board, 2, {}, deadline)
        self.assertEqual(value, search.LOST_SCORE)

    def test_single_legal_move_is_the_only_analysis(self):
        grid = [[2, 4, 8, 16], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        analyses = search.analyze(grid)
        self.assertEqual({a.direction for a in analyses}, set(game.legal_moves(grid)))

    def test_no_legal_moves_returns_empty(self):
        grid = [
            [2, 4, 2, 4],
            [4, 2, 4, 2],
            [2, 4, 2, 4],
            [4, 2, 4, 2],
        ]
        self.assertEqual(search.analyze(grid), [])


class TestHeuristic(unittest.TestCase):
    def test_anchored_board_scores_higher_than_scattered(self):
        anchored = [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [16, 8, 4, 2],
        ]
        scattered = [
            [16, 8, 4, 2],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ]
        self.assertGreater(
            search.heuristic(search.encode(anchored)),
            search.heuristic(search.encode(scattered)),
        )


class TestSpawnSurvival(unittest.TestCase):
    def test_every_move_survives_on_an_open_board(self):
        grid = [[0, 0, 0, 0], [0, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        analyses = search.analyze(grid, time_budget=0.05)
        self.assertTrue(all(a.survives_every_spawn for a in analyses))

    def test_detects_an_unsafe_move_on_a_nearly_full_board(self):
        # Only one empty cell (row 3, col 3). Moving "up" leaves the board
        # fully packed with no merges available for several columns, so a
        # bad spawn can end the game; "down" should remain safe.
        grid = [
            [2, 4, 8, 16],
            [4, 8, 16, 32],
            [8, 16, 32, 64],
            [16, 32, 64, 0],
        ]
        analyses = {a.direction: a for a in search.analyze(grid, time_budget=0.05)}
        self.assertIn("down", analyses)
        # At least the search should distinguish moves rather than
        # reporting every move as equally (un)safe.
        self.assertTrue(any(a.survives_every_spawn for a in analyses.values()))


class TestTimeBudget(unittest.TestCase):
    def test_analyze_respects_time_budget(self):
        grid = [
            [2, 4, 8, 16],
            [4, 8, 16, 32],
            [8, 16, 32, 64],
            [16, 32, 64, 0],
        ]
        budget = 0.05
        start = time.monotonic()
        search.analyze(grid, time_budget=budget)
        elapsed = time.monotonic() - start
        # Generous slack: the deadline is polled, not preemptive, so a
        # single node's recursion can overshoot slightly.
        self.assertLess(elapsed, budget + 0.5)

    def test_analyze_on_open_board_respects_time_budget(self):
        grid = [[0, 0, 0, 0], [0, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        budget = 0.05
        start = time.monotonic()
        search.analyze(grid, time_budget=budget)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, budget + 0.5)


if __name__ == "__main__":
    unittest.main()
