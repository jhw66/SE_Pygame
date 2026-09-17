"""用模拟鼠标事件运行实际主循环；使用离屏窗口，不代表人工试玩。

运行方法：.venv/Scripts/python.exe -X utf8 test_interaction.py
这一测试脚本使用 runpy 和 mock 驱动窗口代码，游戏本身不依赖这些工具。
"""

import os
from contextlib import nullcontext
from math import isclose
from pathlib import Path
import runpy
from unittest.mock import patch

# 在导入 Pygame 前设置离屏显示和静音，测试无需弹出真实窗口。
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame


# 旧布局作为固定的交互测试夹具：它本身有死锁，不再用作实际游戏题目。
# 固定它可以持续复查历史点击案例；真实随机生成与完整通关由 test_puzzles.py 检查。
FIXTURE_BOARD = [
    ["U", None, "R", None, "D"],
    [None, "L", None, "D", None],
    ["R", None, "U", None, "L"],
    [None, "D", None, "R", None],
    ["L", None, "U", None, "R"],
]


def fixed_level(**kwargs):
    return [row[:] for row in FIXTURE_BOARD]


def run_game(clicks, idle_frames=0, same_frame=False, settle_frames=90, on_frame=None,
             level_factory=fixed_level):
    """默认每次点击后等待动画完成；settle_frames=0 用于测试连点。"""
    frames = []
    for pos, button in clicks:
        frames.append([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)
        ])
        if not same_frame:
            frames.extend([[] for _ in range(settle_frames)])
    if same_frame:
        events = []
        for frame in frames:
            events.extend(frame)
        frames = [events]
        frames.extend([[] for _ in range(settle_frames)])
    for _ in range(idle_frames):
        frames.append([])
    frames.append([pygame.event.Event(pygame.QUIT)])

    # 固定每帧为 16 毫秒，让测试快速且不受电脑运行速度影响。
    with (
        patch("pygame.event.get", side_effect=frames),
        patch("pygame.time.Clock") as clock,
        patch("pygame.display.flip", side_effect=on_frame),
        patch("levels.generate_level", side_effect=level_factory)
        if level_factory is not None else nullcontext(),
    ):
        clock.return_value.tick.return_value = 16
        return runpy.run_path(str(Path(__file__).with_name("main.py")))


def run_tests():
    initial = run_game([])
    initial_board = initial["board"]
    assert initial["remaining_arrows"] == 13
    assert initial["mistakes_remaining"] == 3

    def cell_center(row, col):
        # 读取主程序的布局参数，避免测试里另写一套棋盘像素坐标。
        size = initial["CELL_SIZE"]
        return (
            initial["BOARD_X"] + col * size + size // 2,
            initial["BOARD_Y"] + row * size + size // 2,
        )

    # 第 1 行第 1 列朝上且位于边缘，可消除。
    clear_pos = cell_center(0, 0)
    blocked_pos = cell_center(0, 2)
    empty_pos = cell_center(0, 1)
    expected_removed = [row[:] for row in initial_board]
    expected_removed[0][0] = None

    removed = run_game([(clear_pos, 1)])
    assert removed["board"] == expected_removed
    assert removed["remaining_arrows"] == 12
    assert removed["selected_cell"] is None
    assert removed["mistakes_remaining"] == 3
    assert "已消除" in removed["status_text"]
    print("PASS：成功点击只消除目标箭头，数量减 1，清除选中框")

    blocked = run_game([(blocked_pos, 1)])
    assert blocked["board"] == initial_board
    assert blocked["remaining_arrows"] == 13
    assert blocked["selected_cell"] == (0, 2)
    assert blocked["mistakes_remaining"] == 2
    assert "前方有阻挡" in blocked["status_text"]
    print("PASS：阻挡点击保留棋盘与数量，显示原因")

    empty = run_game([(empty_pos, 1)])
    assert empty["board"] == initial_board
    assert empty["remaining_arrows"] == 13
    assert empty["selected_cell"] is None
    assert empty["mistakes_remaining"] == 3
    print("PASS：空格点击不改变棋盘和数量")

    outside_pos = (
        initial["BOARD_X"] + initial["COLS"] * initial["CELL_SIZE"],
        initial["BOARD_Y"],
    )
    outside = run_game([(blocked_pos, 1), (outside_pos, 1)])
    assert outside["board"] == initial_board
    assert outside["remaining_arrows"] == 13
    assert outside["selected_cell"] is None
    assert outside["mistakes_remaining"] == 2  # 只有前面的受阻点击扣了一次。
    print("PASS：点击棋盘右边界外不越界，并清除旧选中框")

    repeated = run_game([(clear_pos, 1), (clear_pos, 1)])
    assert repeated["board"] == expected_removed
    assert repeated["remaining_arrows"] == 12
    assert repeated["mistakes_remaining"] == 3
    assert "空格" in repeated["status_text"]
    print("PASS：重复点击已消除位置不会重复减数")

    right_click = run_game([(clear_pos, 3)])
    assert right_click["board"] == initial_board
    assert right_click["remaining_arrows"] == 13
    assert right_click["mistakes_remaining"] == 3
    print("PASS：鼠标右键不会消除箭头")

    # 初始 (1, 3) 向下，被 (3, 3) 阻挡，而 (3, 3) 可直接向右消除。
    # 移除阻挡物后，再点击同一个箭头，验证使用更新后的棋盘。
    unlocked = run_game([
        (cell_center(1, 3), 1),
        (cell_center(3, 3), 1),
        (cell_center(1, 3), 1),
    ])
    expected_unlocked = [row[:] for row in initial_board]
    expected_unlocked[1][3] = None
    expected_unlocked[3][3] = None
    assert unlocked["board"] == expected_unlocked
    assert unlocked["remaining_arrows"] == 11
    assert unlocked["mistakes_remaining"] == 2
    print("PASS：移除阻挡物后，原先被阻挡的箭头可以消除")

    still_playing = run_game([(blocked_pos, 1)] * 2 + [(clear_pos, 1)])
    assert still_playing["mistakes_remaining"] == 1
    assert still_playing["board"] == expected_removed
    assert still_playing["remaining_arrows"] == 12
    print("PASS：两次失误后仍可消除安全箭头，成功点击不扣机会")

    failed = run_game([(blocked_pos, 1)] * 3)
    assert failed["mistakes_remaining"] == 0
    assert failed["board"] == initial_board
    assert failed["remaining_arrows"] == 13
    assert "失败" in failed["status_text"]
    assert failed["status_color"] == failed["ERROR_COLOR"]
    assert failed["running"] is False  # 失败后仍能处理关闭事件。
    print("PASS：第三次失误耗尽机会，保留棋盘并显示失败，可关闭窗口")

    frozen = run_game(
        [(blocked_pos, 1)] * 5
        + [(clear_pos, 1), (empty_pos, 1), (outside_pos, 1), (clear_pos, 3)]
    )
    assert frozen["mistakes_remaining"] == 0
    assert frozen["board"] == initial_board
    assert frozen["remaining_arrows"] == 13
    assert frozen["status_text"] == failed["status_text"]
    assert frozen["selected_cell"] == failed["selected_cell"]
    print("PASS：失败后的各种点击不会改棋盘、覆盖失败提示或扣成负数")

    queued = run_game(
        [(blocked_pos, 1)] * 3 + [(clear_pos, 1)], same_frame=True
    )
    assert queued["mistakes_remaining"] == 0
    assert queued["board"] == initial_board
    assert "失败" in queued["status_text"]
    print("PASS：同一帧内耗尽机会后，后续排队点击也无法消除箭头")

    held = run_game([(blocked_pos, 1)], idle_frames=10)
    assert held["mistakes_remaining"] == 2
    assert held["board"] == initial_board
    print("PASS：一次按下后等待多个绘制帧，不会每帧重复扣机会")
    print("全部 12 个点击交互场景通过（离屏模拟）。")

    # 动画刚开始时应移动显示位置，但不能立刻清空棋盘或减少数量。
    moving = run_game([(clear_pos, 1)], idle_frames=1, settle_frames=0)
    assert moving["board"] == initial_board
    assert moving["remaining_arrows"] == 13
    assert moving["flying_arrow"]["direction"] == "U"
    assert isclose(moving["flying_arrow"]["x"], clear_pos[0])
    assert isclose(moving["flying_arrow"]["y"], clear_pos[1] - 320 * 0.032)
    assert "正在飞出" in moving["status_text"]
    assert moving["running"] is False
    print("PASS：空帧仍推进动画，飞出中保留数据与数量，并可响应关闭")

    # 包含同一帧多个点击和后续帧点击；整个动画中都只接受第一个。
    for same_frame in (False, True):
        busy = run_game(
            [(clear_pos, 1), (blocked_pos, 1), (cell_center(4, 4), 1)],
            same_frame=same_frame, settle_frames=0,
        )
        assert busy["mistakes_remaining"] == 3
        assert busy["board"] == initial_board
        assert (busy["flying_arrow"]["row"], busy["flying_arrow"]["col"]) == (0, 0)
    print("PASS：动画期间同帧及跨帧连点不会扣机会或启动第二个箭头")

    for row, col, direction in ((0, 0, "U"), (3, 1, "D"), (4, 0, "L"), (4, 4, "R")):
        finished = run_game([(cell_center(row, col), 1)])
        expected = [line[:] for line in initial_board]
        expected[row][col] = None
        assert finished["board"] == expected, direction
        assert finished["flying_arrow"] is None, direction
        assert finished["remaining_arrows"] == 12, direction
        assert finished["mistakes_remaining"] == 3, direction
    print("PASS：四方向动画均完成，并且只清空对应格子一次")

    # 同一总时长，不同帧数应该有相同位移；独立验证行列与像素轴没有混淆。
    update = initial["update_flying_arrow"]
    for direction, dx, dy in (("U", 0, -32), ("D", 0, 32), ("L", -32, 0), ("R", 32, 0)):
        one_step = {"direction": direction, "x": 480.0, "y": 340.0}
        ten_steps = one_step.copy()
        assert update(one_step, 0.1) is False
        for _ in range(10):
            assert update(ten_steps, 0.01) is False
        assert isclose(one_step["x"], 480 + dx)
        assert isclose(one_step["y"], 340 + dy)
        assert isclose(one_step["x"], ten_steps["x"])
        assert isclose(one_step["y"], ten_steps["y"])
    print("PASS：四方向在不同帧数下，相同时间产生相同位移")

    # 中心刚到边缘时，尾部还在棋盘里，不能提前结束。
    for direction, x, y in (("U", 480, 140), ("D", 480, 540), ("L", 280, 340), ("R", 680, 340)):
        arrow = {"direction": direction, "x": x, "y": y}
        assert update(arrow, 0) is False
        assert update(arrow, 0.1) is True  # 再移动 32 像素，尾部也已离开。
    print("PASS：四边界均等待整支箭头离开，不在中心越界时提前删除")
    print("新增 5 组飞出动画检查通过（离屏模拟）。")

    # 从真实绘制的画布读取颜色，确认不只是变量变了，箭杆与箭头也真的变红。
    other_blocked_pos = cell_center(0, 4)
    normal_color = initial["ARROW_COLOR"]
    red_color = initial["ERROR_COLOR"]

    def capture_collision(clicks, **options):
        samples = []

        def capture():
            surface = pygame.display.get_surface()
            samples.append({
                "shaft": tuple(surface.get_at(blocked_pos)[:3]),
                "tip": tuple(surface.get_at((blocked_pos[0] + 14, blocked_pos[1]))[:3]),
                "other": tuple(surface.get_at(other_blocked_pos)[:3]),
                "safe": tuple(surface.get_at(clear_pos)[:3]),
            })

        result = run_game(clicks, on_frame=capture, **options)
        return result, samples

    red, samples = capture_collision([(blocked_pos, 1)], settle_frames=0)
    assert samples[0]["shaft"] == samples[0]["tip"] == red_color
    assert samples[0]["other"] == samples[0]["safe"] == normal_color
    assert red["collision_cell"] == (0, 2)
    assert red["board"] == initial_board
    assert red["remaining_arrows"] == 13
    assert red["mistakes_remaining"] == 2
    assert red["running"] is False
    print("PASS：受阻箭杆和箭头立即变红，其他箭头原色，保留棋盘并可关闭")

    restored, samples = capture_collision([(blocked_pos, 1)], settle_frames=0, idle_frames=20)
    assert samples[15]["shaft"] == samples[15]["tip"] == red_color  # 0.240 秒
    assert samples[16]["shaft"] == samples[16]["tip"] == normal_color  # 0.256 秒
    assert restored["collision_cell"] is None
    assert restored["collision_remaining"] == 0
    assert restored["board"] == initial_board
    assert restored["mistakes_remaining"] == 2
    print("PASS：没有新事件时仍计时，约 0.25 秒后恢复，等待不会重复扣次数")

    renewed, samples = capture_collision([(blocked_pos, 1)] * 2, settle_frames=8, idle_frames=20)
    assert samples[16]["shaft"] == red_color  # 第二次点击在第 9 帧，重置倒计时。
    assert samples[25]["shaft"] == normal_color
    assert renewed["mistakes_remaining"] == 1
    assert renewed["collision_cell"] is None
    assert renewed["board"] == initial_board
    print("PASS：再次受阻重新计时，两次有效点击扣两次，计时不累计延长")

    changed, samples = capture_collision(
        [(blocked_pos, 1), (other_blocked_pos, 1)], settle_frames=0, idle_frames=20,
    )
    assert samples[0]["shaft"] == red_color
    assert samples[1]["shaft"] == normal_color
    assert samples[1]["other"] == red_color
    assert samples[-1]["other"] == normal_color
    assert changed["mistakes_remaining"] == 1
    assert changed["board"] == initial_board
    print("PASS：切换到另一个受阻箭头时只标记最新碰撞，不残留旧红色")

    final_hit, samples = capture_collision(
        [(blocked_pos, 1)] * 3 + [(clear_pos, 1)],
        same_frame=True, settle_frames=0, idle_frames=20,
    )
    assert samples[0]["shaft"] == red_color
    assert samples[-1]["shaft"] == normal_color
    assert final_hit["mistakes_remaining"] == 0
    assert final_hit["board"] == initial_board
    assert "失败" in final_hit["status_text"]
    assert final_hit["collision_cell"] is None
    assert final_hit["status_color"] == red_color
    print("PASS：最后一次失误也有红色反馈，到时恢复且保留失败文字和操作限制")

    concurrent, samples = capture_collision(
        [(blocked_pos, 1), (cell_center(3, 3), 1)], settle_frames=0, idle_frames=100,
    )
    expected = [line[:] for line in initial_board]
    expected[3][3] = None
    assert samples[1]["shaft"] == red_color
    assert samples[16]["shaft"] == normal_color
    assert concurrent["board"] == expected
    assert concurrent["mistakes_remaining"] == 2
    assert concurrent["collision_cell"] is None
    assert concurrent["flying_arrow"] is None
    print("PASS：碰撞反馈不阻止下一次安全点击，变色计时与飞出动画独立完成")

    for pos, button in ((empty_pos, 1), (outside_pos, 1), (blocked_pos, 3)):
        ignored, samples = capture_collision([(pos, button)], settle_frames=0)
        assert ignored["collision_cell"] is None
        assert ignored["collision_remaining"] == 0
        assert ignored["mistakes_remaining"] == 3
        assert samples[0]["shaft"] == normal_color
    print("PASS：空格、棋盘外和右键点击不会触发碰撞变色")
    print("新增 7 组碰撞反馈检查通过（离屏模拟，含像素颜色检查）。")

    # 游戏状态与窗口是否运行分开：退出窗口后仍能查看最终游戏阶段。
    for result in (initial, removed, blocked, still_playing, restored, concurrent):
        assert result["game_state"] == result["PLAYING"]
    assert still_playing["mistakes_remaining"] == 1
    print("PASS：启动、成功消除和前两次失误都保持游戏中状态")

    for result in (failed, frozen, queued, final_hit):
        assert result["game_state"] == result["FAILED"]
        assert result["mistakes_remaining"] == 0
        assert result["flying_arrow"] is None
        assert result["board"] == initial_board
    print("PASS：第三次失误进入失败，同帧和后续点击均不能启动飞出或继续扣次数")

    # 先消除再失败：保留失败时的局面，不自动重开，也不接受失败后的安全点击。
    partial_failure = run_game(
        [(clear_pos, 1)] + [(blocked_pos, 1)] * 3 + [(cell_center(3, 3), 1)],
    )
    assert partial_failure["game_state"] == partial_failure["FAILED"]
    assert partial_failure["board"] == expected_removed
    assert partial_failure["remaining_arrows"] == 12
    assert partial_failure["mistakes_remaining"] == 0
    assert partial_failure["flying_arrow"] is None
    assert "失败" in partial_failure["status_text"]
    print("PASS：已有消除进度在失败后保留，不自动恢复或被后续安全点击修改")

    header_red = []
    header_rect = initial["failed_title_rect"]

    def capture_failure_header():
        surface = pygame.display.get_surface()
        # 标题区域应在第三次失误后实际绘出红字，前两次仍显示普通标题。
        header_red.append(any(
            tuple(surface.get_at((x, y))[:3]) == red_color
            for y in range(header_rect.top, header_rect.bottom, 2)
            for x in range(header_rect.left, header_rect.right, 2)
        ))

    visible_failure = run_game(
        [(blocked_pos, 1)] * 3, settle_frames=0, idle_frames=20,
        on_frame=capture_failure_header,
    )
    assert header_red[:2] == [False, False]
    assert len(header_red) == 24  # 三次点击、二十个空帧以及最后的关闭帧都已处理。
    assert all(header_red[2:])
    assert visible_failure["game_state"] == visible_failure["FAILED"]
    assert visible_failure["running"] is False
    assert visible_failure["collision_cell"] is None
    assert "失败" in visible_failure["status_text"]
    print("PASS：第三次失误切换红色结果标题，失败后持续绘制、反馈恢复并正常关闭")
    print("新增 4 组游戏状态检查通过（离屏模拟，含失败标题像素检查）。")

    restart_pos = initial["restart_rect"].center

    def assert_reset(result):
        assert result["board"] == initial_board
        assert result["INITIAL_BOARD"] == initial_board
        assert result["board"] is not result["INITIAL_BOARD"]
        assert all(a is not b for a, b in zip(result["board"], result["INITIAL_BOARD"]))
        assert result["remaining_arrows"] == 13
        assert result["mistakes_remaining"] == 3
        assert result["game_state"] == result["PLAYING"]
        assert result["selected_cell"] is None
        assert result["flying_arrow"] is None
        assert result["collision_cell"] is None
        assert result["collision_remaining"] == 0
        assert result["status_text"] == initial["status_text"]
        assert result["status_color"] == result["TEXT_COLOR"]

    # 真正消除后再恢复，既检查复制内容，也检查各行没有共享可变列表。
    assert removed["INITIAL_BOARD"] == initial_board
    restarted = run_game([(clear_pos, 1), (blocked_pos, 1), (restart_pos, 1)])
    assert_reset(restarted)
    print("PASS：消除并失误后重开，恢复完整布局和次数，初始棋盘没有被修改")

    retry = run_game([(blocked_pos, 1)] * 3 + [(restart_pos, 1)])
    assert_reset(retry)
    playable = run_game([(blocked_pos, 1)] * 3 + [(restart_pos, 1), (clear_pos, 1)])
    assert playable["game_state"] == playable["PLAYING"]
    assert playable["board"] == expected_removed
    assert playable["mistakes_remaining"] == 3
    assert "已消除" in playable["status_text"]
    print("PASS：失败后按钮仍可重开，重开后下一帧起可以正常消除")

    for clicks in (
        [(cell_center(3, 3), 1), (restart_pos, 1)],
        [(blocked_pos, 1), (cell_center(3, 3), 1), (restart_pos, 1)],
    ):
        cancelled = run_game(clicks, settle_frames=0, idle_frames=100)
        assert_reset(cancelled)
    print("PASS：飞出中或飞出与变红并存时重开，等待后也没有旧动画误删新棋盘")

    cleared, samples = capture_collision(
        [(blocked_pos, 1), (restart_pos, 1)], settle_frames=0,
    )
    assert samples[0]["shaft"] == red_color
    assert samples[1]["shaft"] == normal_color
    assert_reset(cleared)
    print("PASS：碰撞变红期间重开，当帧恢复原色并清空选中框、计时和旧提示")

    cycles = [(clear_pos, 1), (blocked_pos, 1), (restart_pos, 1)] * 3
    assert_reset(run_game(cycles))
    assert_reset(run_game([(restart_pos, 1)] * 3, same_frame=True))
    print("PASS：连续三轮游玩重开与同帧连点重开都恢复一致的初始状态")

    # 右键、矩形的右边界与下边界不属于有效重开点击。
    for pos, button in (
        (restart_pos, 3),
        ((initial["restart_rect"].right, restart_pos[1]), 1),
        ((restart_pos[0], initial["restart_rect"].bottom), 1),
    ):
        not_restarted = run_game([(blocked_pos, 1)] * 3 + [(pos, button)])
        assert not_restarted["game_state"] == not_restarted["FAILED"]
        assert not_restarted["mistakes_remaining"] == 0
        assert not_restarted["board"] == initial_board
    print("PASS：右键及按钮边界外点击不能误触发重开")

    queued_restart = run_game(
        [(blocked_pos, 1)] * 3 + [(restart_pos, 1), (clear_pos, 1), (blocked_pos, 1)],
        same_frame=True,
    )
    assert_reset(queued_restart)
    print("PASS：重开当帧排队的后续棋盘点击被丢弃，窗口仍可正常处理关闭")
    print("新增 7 组重开检查通过（离屏模拟，含棋盘副本及颜色检查）。")


if __name__ == "__main__":
    run_tests()
