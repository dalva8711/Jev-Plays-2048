import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev2048.game import (
    ANCHOR,
    apply_move,
    empty_cells,
    evaluate_all_moves,
    is_game_over,
    legal_moves,
    max_tile,
    spawn_random_tile,
)


class TestApplyMove(unittest.TestCase):
    def test_left_merge(self):
        grid = [
            [2, 2, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ]
        new_grid, moved, gained = apply_move(grid, "left")
        self.assertTrue(moved)
        self.assertEqual(gained, 4)
        self.assertEqual(new_grid[0], [4, 0, 0, 0])

    def test_right_merge(self):
        grid = [[2, 0, 0, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        new_grid, moved, gained = apply_move(grid, "right")
        self.assertTrue(moved)
        self.assertEqual(gained, 4)
        self.assertEqual(new_grid[0], [0, 0, 0, 4])

    def test_up_merge(self):
        grid = [[2, 0, 0, 0], [2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        new_grid, moved, gained = apply_move(grid, "up")
        self.assertTrue(moved)
        self.assertEqual(gained, 4)
        self.assertEqual([row[0] for row in new_grid], [4, 0, 0, 0])

    def test_down_merge(self):
        grid = [[2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [2, 0, 0, 0]]
        new_grid, moved, gained = apply_move(grid, "down")
        self.assertTrue(moved)
        self.assertEqual(gained, 4)
        self.assertEqual([row[0] for row in new_grid], [0, 0, 0, 4])

    def test_no_double_merge_in_one_move(self):
        # 2 2 2 2 -> left should give 4 4 0 0, not 8 0 0 0
        grid = [[2, 2, 2, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        new_grid, moved, gained = apply_move(grid, "left")
        self.assertTrue(moved)
        self.assertEqual(new_grid[0], [4, 4, 0, 0])
        self.assertEqual(gained, 8)

    def test_illegal_move_reports_not_moved(self):
        grid = [[2, 4, 8, 16], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        new_grid, moved, gained = apply_move(grid, "left")
        self.assertFalse(moved)
        self.assertEqual(gained, 0)
        self.assertEqual(new_grid, grid)

    def test_does_not_mutate_input(self):
        grid = [[2, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        original = [row[:] for row in grid]
        apply_move(grid, "left")
        self.assertEqual(grid, original)


class TestLegalMovesAndGameOver(unittest.TestCase):
    def test_legal_moves_on_open_board(self):
        # A single tile in the middle can legally move in all 4 directions.
        grid = [[0, 0, 0, 0], [0, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        moves = legal_moves(grid)
        self.assertEqual(set(moves), {"up", "down", "left", "right"})

    def test_game_over_board(self):
        grid = [
            [2, 4, 2, 4],
            [4, 2, 4, 2],
            [2, 4, 2, 4],
            [4, 2, 4, 2],
        ]
        self.assertTrue(is_game_over(grid))
        self.assertEqual(legal_moves(grid), [])

    def test_not_game_over_when_merge_possible(self):
        grid = [
            [2, 4, 2, 4],
            [4, 2, 4, 2],
            [2, 4, 2, 4],
            [4, 2, 2, 4],
        ]
        self.assertFalse(is_game_over(grid))


class TestHelpers(unittest.TestCase):
    def test_empty_cells(self):
        grid = [[2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        self.assertEqual(empty_cells(grid), 15)

    def test_max_tile(self):
        grid = [[2, 0, 0, 0], [0, 0, 0, 256], [0, 0, 0, 0], [0, 0, 0, 0]]
        value, pos = max_tile(grid)
        self.assertEqual(value, 256)
        self.assertEqual(pos, (1, 3))

    def test_evaluate_all_moves_shape(self):
        grid = [[0, 0, 0, 0], [0, 2, 2, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        outcomes = evaluate_all_moves(grid)
        directions = {o.direction for o in outcomes}
        self.assertEqual(directions, {"up", "down", "left", "right"})
        for o in outcomes:
            self.assertIsInstance(o.max_tile_in_corner, bool)
            self.assertIsInstance(o.max_tile_in_anchor, bool)

    def test_max_tile_ties_prefer_the_anchor(self):
        grid = [[4, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [4, 0, 0, 0]]
        value, pos = max_tile(grid)
        self.assertEqual(value, 4)
        self.assertEqual(pos, ANCHOR)


class TestSpawnRandomTile(unittest.TestCase):
    def test_places_one_tile_in_an_empty_cell(self):
        grid = [[0, 0, 0, 0], [0, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        rng = random.Random(0)
        new_grid = spawn_random_tile(grid, rng)
        self.assertEqual(empty_cells(new_grid), empty_cells(grid) - 1)

        added = [
            new_grid[r][c]
            for r in range(4)
            for c in range(4)
            if new_grid[r][c] != grid[r][c]
        ]
        self.assertEqual(len(added), 1)
        self.assertIn(added[0], (2, 4))

    def test_does_not_mutate_input(self):
        grid = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        original = [row[:] for row in grid]
        spawn_random_tile(grid, random.Random(1))
        self.assertEqual(grid, original)

    def test_raises_when_board_is_full(self):
        grid = [[2] * 4 for _ in range(4)]
        with self.assertRaises(ValueError):
            spawn_random_tile(grid, random.Random(1))

    def test_is_deterministic_given_a_seeded_rng(self):
        grid = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
        first = spawn_random_tile(grid, random.Random(123))
        second = spawn_random_tile(grid, random.Random(123))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
