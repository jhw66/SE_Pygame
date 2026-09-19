"""纯规则测试，含独立的逐格移动模拟器。"""
import random
import unittest
from game_logic import (Arrow, BoardState, DIRECTIONS, NOSE_EXTENT, can_exit,
                        count_arrows, from_legacy_grid, moving_shape, plan_movement, solve_board)


def independent_motion(board, arrow_id):
    """实际更新整条坐标队列，不复用生产规则的射线/尾部下标算法。"""
    arrow = board.arrows[arrow_id]
    body = list(arrow.cells)
    # 测试用身体队列逐格推进，与正式实现的射线扫描交叉验证。
    other = {cell for i, a in board.arrows.items() if i != arrow_id for cell in a.cells}
    delta = {"U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1)}[arrow.direction]
    for step in range(1, board.rows + board.cols + len(body) + 2):
        head = body[-1][0] + delta[0], body[-1][1] + delta[1]
        if head in other or head in body[1:]:
            return False, step, head
        body = body[1:] + [head]
        if all(not (0 <= r < board.rows and 0 <= c < board.cols) for r, c in body):
            return True, step, None
    raise AssertionError("模拟未结束")


def independent_replay(board, solution):
    # 按给定解逐支独立验证，并确认最后真的清空整盘。
    if solution is None or len(solution) != len(board.arrows):
        raise AssertionError("没有完整解")
    working = board.copy()
    for arrow_id in solution:
        if not independent_motion(working, arrow_id)[0]:
            raise AssertionError(f"错误消除步骤：{arrow_id}")
        working.remove(arrow_id)
    if working.arrows:
        raise AssertionError("棋盘没有清空")


class LogicTests(unittest.TestCase):
    # 覆盖占位、头部点击、自身阻挡、复制隔离和运动轨迹等纯规则。
    def test_original_single_cell_rules(self):
        for direction, (dr, dc) in DIRECTIONS.items():
            for gap in (1, 2):
                head = (2, 2)
                a = Arrow(0, (head,), direction)
                block = (2 + dr * gap, 2 + dc * gap)
                board = BoardState(5, 5, {0: a, 1: Arrow(1, (block,), "U")})
                before = board.copy()
                self.assertFalse(can_exit(board, 0))
                self.assertEqual(plan_movement(board, 0).obstacle, block)
                self.assertAlmostEqual(plan_movement(board, 0).distance, gap - 0.5 - NOSE_EXTENT)
                self.assertEqual(board, before)
                board.remove(1)
                self.assertTrue(can_exit(board, 0))
            behind = (2 - dr, 2 - dc)
            board = BoardState(5, 5, {0: a, 1: Arrow(1, (behind,), "R")})
            self.assertTrue(can_exit(board, 0))
        self.assertFalse(can_exit(BoardState(1, 1), -1))
        self.assertEqual(solve_board(BoardState(1, 1)), [])

    def test_body_blocks_but_only_head_is_clickable(self):
        a = Arrow(0, ((3, 1), (3, 2), (2, 2), (2, 3)), "R")
        block = Arrow(1, ((2, 5), (1, 5)), "U")
        board = BoardState(7, 8, {0: a, 1: block})
        self.assertEqual(count_arrows(board), 2)
        for cell in a.cells[:-1]:
            self.assertIsNone(board.head_at(cell))
        self.assertEqual(board.head_at(a.head), 0)
        self.assertIsNone(board.head_at((-1, 0)))
        self.assertIsNone(board.head_at((7, 0)))
        self.assertFalse(can_exit(board, 0))
        self.assertEqual(plan_movement(board, 0).obstacle, (2, 5))
        board.remove(1)
        self.assertTrue(can_exit(board, 0))

    def test_self_obstacle_and_vacating_tail(self):
        cells = ((5, 4), (4, 4), (3, 4), (2, 4), (2, 3), (2, 2), (2, 1), (3, 1), (3, 2))
        board = BoardState(6, 6, {0: Arrow(0, cells, "R")})
        self.assertEqual(plan_movement(board, 0).obstacle, (3, 4))
        self.assertFalse(independent_motion(board, 0)[0])
        # 缩短尾部后，头部到达前方格时该处身体已经腾空。
        board = BoardState(6, 6, {0: Arrow(0, cells[1:], "R")})
        self.assertTrue(can_exit(board, 0))
        loop = Arrow(0, ((0, 0), (0, 1), (1, 1), (2, 1), (2, 0), (1, 0)), "U")
        board = BoardState(3, 3, {0: loop})
        self.assertTrue(can_exit(board, 0))
        self.assertTrue(independent_motion(board, 0)[0])

    def test_random_paths_against_independent_simulator(self):
        rng = random.Random(710)
        inverse = {v: k for k, v in DIRECTIONS.items()}
        for _ in range(1000):
            cells = [(rng.randrange(7), rng.randrange(7))]
            for _ in range(rng.randrange(1, 18)):
                r, c = cells[-1]
                options = [(r + dr, c + dc) for dr, dc in DIRECTIONS.values()
                           if 0 <= r + dr < 7 and 0 <= c + dc < 7
                           and (r + dr, c + dc) not in cells]
                if not options:
                    break
                cells.append(rng.choice(options))
            direction = inverse[(cells[-1][0] - cells[-2][0], cells[-1][1] - cells[-2][1])]
            arrows = {0: Arrow(0, tuple(cells), direction)}
            free = [(r, c) for r in range(7) for c in range(7) if (r, c) not in cells]
            for i, cell in enumerate(rng.sample(free, min(len(free), 8)), 1):
                arrows[i] = Arrow(i, (cell,), "U")
            board = BoardState(7, 7, arrows)
            actual = plan_movement(board, 0)
            success, step, obstacle = independent_motion(board, 0)
            self.assertEqual(actual.outcome == "exit", success)
            self.assertEqual(actual.obstacle, obstacle)
            if not success:
                self.assertAlmostEqual(actual.distance, step - 0.5 - NOSE_EXTENT)

    def test_validation_and_copy(self):
        invalid = [
            lambda: Arrow(0, (), "R"),
            lambda: Arrow(0, ((0, 0), (1, 1)), "R"),
            lambda: Arrow(0, ((0, 0), (0, 1), (0, 0)), "L"),
            lambda: Arrow(0, ((0, 0), (0, 1)), "U"),
            lambda: BoardState(0, 2),
            lambda: BoardState(2, 2, {0: Arrow(0, ((2, 0),), "U")}),
            lambda: BoardState(2, 2, {0: Arrow(0, ((0, 0),), "U"), 1: Arrow(1, ((0, 0),), "R")}),
        ]
        for factory in invalid:
            with self.assertRaises(ValueError):
                factory()
        board = from_legacy_grid([["L", "R"]])
        copied = board.copy()
        copied.remove(0)
        self.assertEqual(len(board.arrows), 2)
        self.assertEqual(board.occupancy[0][0], 0)
        independent_replay(board, solve_board(board))
        self.assertIsNone(solve_board(from_legacy_grid([["R", "L"]])))

    def test_moving_shape_returns_exactly_to_original(self):
        a = Arrow(0, ((3, 1), (3, 2), (2, 2), (2, 3)), "R")
        initial = moving_shape(a, 0)
        path, head = moving_shape(a, 0.5)
        self.assertEqual(head, (2, 3.5))
        self.assertEqual(path[0], (3, 1.25))
        self.assertIn((2.0, 2.0), path)
        moving_shape(a, 4.75)
        self.assertEqual(moving_shape(a, 0), initial)


if __name__ == "__main__":
    unittest.main()
