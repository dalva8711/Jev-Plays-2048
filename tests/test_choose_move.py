import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev2048 import jev
from jev2048.game import evaluate_all_moves
from jev2048.jev import JevDecision, JevUnavailable, choose_move
from jev2048.search import MoveAnalysis

# A single centered tile is legal in all four directions, which keeps
# every test free to pick any subset of directions as "the safe ones"
# without worrying about which moves are actually legal.
GRID = [[0, 0, 0, 0], [0, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]


def _outcomes():
    return evaluate_all_moves(GRID)


def _analyses(values: dict[str, float], survives: dict[str, bool] | None = None) -> list[MoveAnalysis]:
    survives = survives if survives is not None else {d: True for d in values}
    return [
        MoveAnalysis(
            direction=d,
            expected_value=v,
            survives_every_spawn=survives[d],
            worst_case_empty_after_next_move=5,
            depth_reached=2,
        )
        for d, v in values.items()
    ]


def _fail_ask(payload, timeout, retries):
    raise AssertionError("Jev should not have been called")


class TestMarginShortCircuit(unittest.TestCase):
    def test_clear_margin_skips_jev(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        values = {d: (100.0 if i == 0 else 50.0) for i, d in enumerate(directions)}
        analyses = _analyses(values)

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="hybrid", ask=_fail_ask)

        self.assertEqual(decision.source, "search")
        self.assertEqual(decision.direction, directions[0])


class TestSingleSafeMove(unittest.TestCase):
    def test_single_safe_move_skips_jev(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        # Best by raw expected value is directions[0], but it's unsafe;
        # directions[1] is the only move that survives every spawn.
        values = {d: 100.0 - i for i, d in enumerate(directions)}
        survives = {d: (d == directions[1]) for d in directions}
        analyses = _analyses(values, survives)

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="hybrid", ask=_fail_ask)

        self.assertEqual(decision.source, "search")
        self.assertEqual(decision.direction, directions[1])

    def test_no_safe_move_falls_back_to_best_expected_value(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        values = {d: 100.0 - i for i, d in enumerate(directions)}
        survives = {d: False for d in directions}
        analyses = _analyses(values, survives)

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="hybrid", ask=_fail_ask)

        self.assertEqual(decision.source, "search")
        self.assertEqual(decision.direction, directions[0])


class TestTopKToJev(unittest.TestCase):
    def test_sends_only_top_k_safe_moves_when_close(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        self.assertEqual(len(directions), 4)  # all four legal on this board
        values = {d: 100.0 - i * 0.1 for i, d in enumerate(directions)}
        analyses = _analyses(values)

        seen = {}

        def capture_ask(payload, timeout, retries):
            seen["candidates"] = payload["state"]["candidate_moves"]
            top_direction = seen["candidates"][0]["direction"]
            return JevDecision(direction=top_direction, confidence=0.9, probabilities={}, source="jev")

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="hybrid", ask=capture_ask)

        self.assertEqual(len(seen["candidates"]), jev.TOP_K)
        self.assertEqual(decision.source, "jev")
        self.assertEqual(decision.direction, directions[0])


class TestLowConfidenceFallsBackToSearch(unittest.TestCase):
    def test_low_confidence_uses_search_top_move(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        values = {d: 100.0 - i * 0.1 for i, d in enumerate(directions)}
        analyses = _analyses(values)

        def low_confidence_ask(payload, timeout, retries):
            other_direction = payload["state"]["candidate_moves"][-1]["direction"]
            return JevDecision(direction=other_direction, confidence=0.1, probabilities={}, source="jev")

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="hybrid", ask=low_confidence_ask)

        self.assertEqual(decision.source, "search")
        self.assertEqual(decision.direction, directions[0])

    def test_high_confidence_is_trusted(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        values = {d: 100.0 - i * 0.1 for i, d in enumerate(directions)}
        analyses = _analyses(values)

        def high_confidence_ask(payload, timeout, retries):
            other_direction = payload["state"]["candidate_moves"][-1]["direction"]
            return JevDecision(direction=other_direction, confidence=0.9, probabilities={}, source="jev")

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="hybrid", ask=high_confidence_ask)

        self.assertEqual(decision.source, "jev")


class TestApiFailureFallsBack(unittest.TestCase):
    def test_api_failure_gives_fallback_source(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        values = {d: 100.0 - i * 0.1 for i, d in enumerate(directions)}
        analyses = _analyses(values)

        def unavailable_ask(payload, timeout, retries):
            raise JevUnavailable()

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="hybrid", ask=unavailable_ask)

        self.assertEqual(decision.source, "fallback")
        self.assertEqual(decision.direction, directions[0])


class TestModes(unittest.TestCase):
    def test_search_mode_never_calls_jev(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        values = {d: 100.0 - i for i, d in enumerate(directions)}
        analyses = _analyses(values)

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="search", ask=_fail_ask)

        self.assertEqual(decision.source, "search")
        self.assertEqual(decision.direction, directions[0])

    def test_jev_mode_sends_every_legal_move(self):
        outcomes = _outcomes()
        directions = [o.direction for o in outcomes]
        values = {d: 100.0 - i for i, d in enumerate(directions)}
        analyses = _analyses(values)

        seen = {}

        def capture_ask(payload, timeout, retries):
            seen["candidates"] = payload["state"]["candidate_moves"]
            return JevDecision(direction=directions[0], confidence=0.5, probabilities={}, source="jev")

        with patch("jev2048.jev.search.analyze", return_value=analyses):
            decision = choose_move(GRID, outcomes, mode="jev", ask=capture_ask)

        self.assertEqual(len(seen["candidates"]), len(outcomes))
        # No confidence gating in legacy "jev" mode.
        self.assertEqual(decision.source, "jev")


class TestSingleLegalMove(unittest.TestCase):
    def test_trivial_when_only_one_move(self):
        from jev2048.game import MoveOutcome

        only = MoveOutcome(
            direction="left",
            grid=GRID,
            score_gained=0,
            empty_after=14,
            max_tile_value=2,
            max_tile_position=(1, 1),
            max_tile_in_corner=False,
        )
        decision = choose_move(GRID, [only], ask=_fail_ask)
        self.assertEqual(decision.source, "trivial")
        self.assertEqual(decision.direction, "left")


if __name__ == "__main__":
    unittest.main()
