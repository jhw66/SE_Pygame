"""用模拟鼠标事件运行实际主循环；使用离屏窗口，不代表人工试玩。

运行方法：.venv/Scripts/python.exe -X utf8 test_interaction.py
这一测试脚本使用 runpy 和 mock 驱动窗口代码，游戏本身不依赖这些工具。
"""

import os
from pathlib import Path
import runpy
from unittest.mock import patch

# 在导入 Pygame 前设置离屏显示和静音，测试无需弹出真实窗口。
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame


def run_game(clicks, idle_frames=0, same_frame=False):
    """默认每帧一次点击；也可等待空帧或将点击集中在同一帧。"""
    frames = []
    for pos, button in clicks:
        frames.append([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)
        ])
    if same_frame:
        events = []
        for frame in frames:
            events.extend(frame)
        frames = [events]
    for _ in range(idle_frames):
        frames.append([])
    frames.append([pygame.event.Event(pygame.QUIT)])

    with patch("pygame.event.get", side_effect=frames):
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


if __name__ == "__main__":
    run_tests()
