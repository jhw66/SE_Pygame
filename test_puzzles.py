"""生成、配置与整盘可解性测试；独立模拟验证消除顺序。"""
import random
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from game_logic import Arrow, BoardState, solve_board
from levels import (GenerationCancelled, GenerationError, LevelConfig, generate_level,
                    level_metrics, load_level)
from test_logic import independent_replay

ROOT = Path(__file__).parent


class PuzzleTests(unittest.TestCase):
    # 固定种子覆盖多种尺寸与密度，逐题独立回放而非只信任求解器。
    def test_thousand_original_puzzles(self):
        previous = None
        signatures = set()
        for seed in range(1000):
            board = generate_level(LevelConfig(), previous=previous, rng=random.Random(seed))
            self.assertEqual((board.rows, board.cols, len(board.arrows)), (5, 5, 13))
            self.assertEqual({a.direction for a in board.arrows.values()}, set("UDLR"))
            snapshot = board.copy()
            independent_replay(board, solve_board(board))
            self.assertEqual(board, snapshot)
            if previous is not None:
                self.assertNotEqual(board.signature(), previous.signature())
            signatures.add(board.signature())
            previous = board
        self.assertGreater(len(signatures), 950)

    def test_sizes_densities_and_mixed_paths(self):
        configs = [
            LevelConfig(4, 4, 8, 1, 3, 0.5),
            LevelConfig(7, 10, 25, 1, 6, 0.7),
            LevelConfig(16, 16, 90, 1, 8, 0.3),
            LevelConfig(25, 25, 180, 1, 6, 0.45),
            LevelConfig(25, 25, 500, 1, 3, 0.5),
            LevelConfig(8, 8, 50, 1, 4, 0.35),
            LevelConfig(6, 9, 6, 2, 5, 0.5),
            LevelConfig(2, 3, 6),
            LevelConfig(1, 1, 1),
            LevelConfig(27, 31, 40, 1, 5, 0.5),
        ]
        saw_bent = False
        for config in configs:
            for seed in (18, 29, 53):
                with self.subTest(config=config, seed=seed):
                    board = generate_level(config, rng=random.Random(seed))
                    self.assertEqual((board.rows, board.cols), (config.rows, config.cols))
                    self.assertEqual(len(board.arrows), config.arrow_count)
                    self.assertTrue(all(config.min_length <= len(a.cells) <= config.max_length
                                        for a in board.arrows.values()))
                    self.assertLessEqual(sum(len(a.cells) for a in board.arrows.values()),
                                         config.rows * config.cols)
                    independent_replay(board, solve_board(board))
                    for a in board.arrows.values():
                        deltas = {(b[0] - c[0], b[1] - c[1]) for c, b in zip(a.cells, a.cells[1:])}
                        saw_bent |= len(deltas) > 1
        self.assertTrue(saw_bent)

    def test_probability_zero_never_turns(self):
        config = LevelConfig(8, 8, 10, 1, 6, 0)
        for seed in range(10):
            board = generate_level(config, rng=random.Random(seed))
            for a in board.arrows.values():
                deltas = {(b[0] - c[0], b[1] - c[1]) for c, b in zip(a.cells, a.cells[1:])}
                self.assertLessEqual(len(deltas), 1)

    def test_seed_and_previous_not_mutated(self):
        config = LevelConfig(7, 10, 22, 1, 5, 0.4)
        first = generate_level(config, rng=random.Random(42))
        self.assertEqual(first, generate_level(config, rng=random.Random(42)))
        snapshot = first.copy()
        changed = generate_level(config, previous=first, rng=random.Random(42))
        self.assertNotEqual(first.signature(), changed.signature())
        self.assertEqual(first, snapshot)
        independent_replay(changed, solve_board(changed))

    def test_invalid_configuration_and_budgets(self):
        for args in ({"rows": 0}, {"cols": -1}, {"arrow_count": 26},
                     {"min_length": 3}, {"turn_probability": 1.1},
                     {"turn_probability": float("nan")}, {"rows": 4.5}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                LevelConfig(**args)
        previous = generate_level(rng=random.Random(3))
        before = previous.copy()
        with patch("levels.time.monotonic", side_effect=[0, 6]):
            with self.assertRaises(GenerationError):
                generate_level(previous=previous)
        with self.assertRaises(GenerationError):
            generate_level(previous=previous, rng=random.Random(3), max_attempts=1)
        self.assertEqual(previous, before)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(GenerationCancelled):
            generate_level(cancel_event=cancel)

    def test_manual_and_metrics(self):
        board = load_level(ROOT / "examples/manual.json")
        independent_replay(board, solve_board(board))
        self.assertIsInstance(load_level(ROOT / "examples/large.json"), LevelConfig)
        metrics = level_metrics(board)
        self.assertEqual(metrics["initial_choices"], 3)
        self.assertEqual(metrics["unlock_rounds"], 3)
        self.assertGreater(metrics["occupancy_ratio"], 0)
        locked = BoardState(1, 2, {0: Arrow(0, ((0, 0),), "R"), 1: Arrow(1, ((0, 1),), "L")})
        self.assertIsNone(level_metrics(locked)["unlock_rounds"])
        with patch("pathlib.Path.read_text", return_value='{"rows":1,"cols":2,"arrows":[{"id":0,"cells":[[0,0]],"direction":"R"},{"id":1,"cells":[[0,1]],"direction":"L"}]'):
            with self.assertRaises(ValueError):
                load_level("unused.json")
        with patch("pathlib.Path.read_text", return_value='{"rows":2,"cols":2,"arrows":[{"id":0,"cells":[[0,0]],"direction":"U"},{"id":0,"cells":[[1,0]],"direction":"D"}]}'):
            with self.assertRaises(ValueError):
                load_level("unused.json")


if __name__ == "__main__":
    unittest.main()
