"""检查旧布局死锁、随机题目可解性，以及真实游戏循环的换题和通关。"""

import random

from game_logic import count_arrows, solve_board
from levels import generate_level
from test_interaction import FIXTURE_BOARD, run_game, pygame


def independent_replay(board, solution):
    """用同一行/列的位置关系验解，不调用游戏里的 can_exit。"""
    occupied = {
        (r, c): direction for r, row in enumerate(board)
        for c, direction in enumerate(row) if direction is not None
    }
    assert solution is not None
    assert len(solution) == len(occupied)
    for r, c in solution:
        direction = occupied[(r, c)]
        for rr, cc in occupied:
            assert not (
                (direction == "U" and cc == c and rr < r)
                or (direction == "D" and cc == c and rr > r)
                or (direction == "L" and rr == r and cc < c)
                or (direction == "R" and rr == r and cc > c)
            ), (r, c, direction, rr, cc)
        del occupied[(r, c)]
    assert not occupied


def seeded_factory(seed):
    rng = random.Random(seed)

    def create(**kwargs):
        return generate_level(rng=rng, **kwargs)

    return create


def center(game, cell):
    r, c = cell
    return (game["BOARD_X"] + c * game["CELL_SIZE"] + game["CELL_SIZE"] // 2,
            game["BOARD_Y"] + r * game["CELL_SIZE"] + game["CELL_SIZE"] // 2)


def assert_fresh(game, expected):
    assert game["board"] == game["INITIAL_BOARD"] == expected
    assert game["board"] is not game["INITIAL_BOARD"]
    assert all(a is not b for a, b in zip(game["board"], game["INITIAL_BOARD"]))
    assert game["game_state"] == game["PLAYING"]
    assert game["mistakes_remaining"] == 3
    assert game["remaining_arrows"] == 13
    assert game["flying_arrow"] is None
    assert game["collision_cell"] is None
    assert game["collision_remaining"] == 0
    assert game["selected_cell"] is None
    assert game["status_text"] == "点击一个箭头，检查它能否离开棋盘"


def run_tests():
    original = [row[:] for row in FIXTURE_BOARD]
    assert solve_board(FIXTURE_BOARD) is None
    assert FIXTURE_BOARD == original
    assert solve_board([["R", "L"]]) is None
    assert solve_board([]) == []
    independent_replay([["L", "R"]], solve_board([["L", "R"]]))
    print("PASS：识别旧棋盘和双箭头死锁，不修改原数据；空棋盘与可解棋盘结果正确")

    previous = None
    layouts = set()
    for seed in range(1000):
        before = None if previous is None else [row[:] for row in previous]
        board = generate_level(previous=previous, rng=random.Random(seed))
        assert len(board) == 5 and all(len(row) == 5 for row in board)
        assert count_arrows(board) == 13
        assert {d for row in board for d in row if d is not None} == set("UDLR")
        assert board != previous
        assert previous == before
        snapshot = [row[:] for row in board]
        independent_replay(board, solve_board(board))
        assert board == snapshot
        layouts.add(tuple(tuple(row) for row in board))
        previous = board
    assert len(layouts) > 950
    print(f"PASS：1000 个种子全部可解，含四方向和 13 个箭头，相邻不重复；不同布局 {len(layouts)} 个")

    duplicate = generate_level(rng=random.Random(42))
    assert duplicate == generate_level(rng=random.Random(42))
    changed = generate_level(previous=duplicate, rng=random.Random(42))
    assert changed != duplicate
    independent_replay(changed, solve_board(changed))
    for rows, cols, count in ((2, 3, 4), (3, 3, 8), (6, 6, 17)):
        board = generate_level(rows, cols, count, rng=random.Random(19))
        assert count_arrows(board) == count
        independent_replay(board, solve_board(board))
    for args in ((1, 5, 4), (5, 5, 3), (5, 5, 25)):
        try:
            generate_level(*args)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法参数未被拒绝：{args}")
    print("PASS：强制重复随机位置也能换题；其他尺寸、数量与非法参数处理正确")

    # 使用真实生成算法，只固定随机种子，不替换成手工布局。
    seed = 17
    initial = run_game([], level_factory=seeded_factory(seed))
    board = initial["INITIAL_BOARD"]
    solution = solve_board(board)
    clicks = [(center(initial, cell), 1) for cell in solution]
    header_seen = []

    def capture_win():
        screen = pygame.display.get_surface()
        rect = initial["won_title_rect"]
        header_seen.append(any(
            tuple(screen.get_at((x, y))[:3]) == initial["ARROW_COLOR"]
            for y in range(rect.top, rect.bottom, 2)
            for x in range(rect.left, rect.right, 2)
        ))

    for current_seed in (17, 29, 53):
        puzzle = generate_level(rng=random.Random(current_seed))
        path = solve_board(puzzle)
        result = run_game([(center(initial, cell), 1) for cell in path],
                          level_factory=seeded_factory(current_seed), on_frame=capture_win)
        assert result["remaining_arrows"] == 0
        assert result["game_state"] == result["WON"]
        assert result["mistakes_remaining"] == 3
        assert result["flying_arrow"] is None
        assert "通关" in result["status_text"]
        assert header_seen[-1]
    assert not header_seen[0]
    print("PASS：3 个真实随机题在游戏循环中逐箭头飞出并完整通关，画布显示绿色通关标题")

    # 最后一个箭头刚被点击时，还应处于飞出阶段，而不是提前宣布通关。
    frames = 0

    def last_arrow_events():
        nonlocal frames
        index, offset = divmod(frames, 91)
        frames += 1
        if index < len(solution) and offset == 0:
            return [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                    pos=center(initial, solution[index]), button=1)]
        if index == len(solution) - 1:
            return [pygame.event.Event(pygame.QUIT)]
        return []

    from unittest.mock import patch
    # run_game 内部会替换事件获取函数，因此直接复用其工具依赖执行程序。
    import runpy
    from pathlib import Path
    with (patch("pygame.event.get", side_effect=last_arrow_events),
          patch("pygame.time.Clock") as clock,
          patch("pygame.display.flip"),
          patch("levels.generate_level", side_effect=seeded_factory(seed))):
        clock.return_value.tick.return_value = 16
        last_moving = runpy.run_path(str(Path(__file__).with_name("main.py")))
    assert last_moving["game_state"] == last_moving["PLAYING"]
    assert last_moving["remaining_arrows"] == 1
    assert last_moving["flying_arrow"] is not None
    print("PASS：最后一个箭头尚在飞出时不提前通关")

    restart_pos = initial["restart_rect"].center
    new_pos = initial["new_puzzle_rect"].center
    won_restart = run_game(clicks + [(restart_pos, 1)], level_factory=seeded_factory(seed))
    assert_fresh(won_restart, board)
    frozen_win = run_game(clicks + [(center(initial, solution[0]), 1)], level_factory=seeded_factory(seed))
    assert frozen_win["game_state"] == frozen_win["WON"]
    assert "通关" in frozen_win["status_text"]

    expected_factory = seeded_factory(seed)
    first = expected_factory()
    second = expected_factory(previous=first)
    changed_game = run_game([(new_pos, 1)], level_factory=seeded_factory(seed))
    assert_fresh(changed_game, second)
    assert changed_game["board"] != board
    won_new = run_game(clicks + [(new_pos, 1)], level_factory=seeded_factory(seed))
    assert_fresh(won_new, second)
    new_restart = run_game([(new_pos, 1), (restart_pos, 1)], level_factory=seeded_factory(seed))
    assert_fresh(new_restart, second)
    print("PASS：通关后可以重玩原题或换新题；换题后重新开始仍恢复新题，不返回旧题")

    from game_logic import can_exit
    blocked = next((r, c) for r, row in enumerate(board) for c, d in enumerate(row)
                   if d is not None and not can_exit(board, r, c))
    prefixes = (
        [(center(initial, solution[0]), 1)],
        [(center(initial, blocked), 1)],
        [(center(initial, blocked), 1)] * 3,
    )
    for prefix in prefixes:
        changed_game = run_game(prefix + [(new_pos, 1)], settle_frames=0, idle_frames=100,
                                level_factory=seeded_factory(seed))
        assert_fresh(changed_game, second)
    queued = run_game([(new_pos, 1), (center(initial, blocked), 1)], same_frame=True,
                      level_factory=seeded_factory(seed))
    assert_fresh(queued, second)
    print("PASS：飞出中、碰撞中、失败后都能换题，旧动画和排队棋盘点击不会污染新题")

    for pos, button in ((new_pos, 3), ((initial["new_puzzle_rect"].right, new_pos[1]), 1)):
        ignored = run_game([(pos, button)], level_factory=seeded_factory(seed))
        assert ignored["INITIAL_BOARD"] == board
    print("PASS：右键及按钮边界外点击不会换题")
    print("随机题目与整盘通关测试全部通过（自动化模拟，不代替本人试玩）。")


if __name__ == "__main__":
    run_tests()
