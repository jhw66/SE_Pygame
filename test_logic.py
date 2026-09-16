"""运行本文件检查路径规则和箭头数量，不启动游戏窗口。"""

from game_logic import can_exit, count_arrows


def run_tests():
    # 每项依次为：名称、棋盘、点击行、点击列、预期能否飞出。
    # 每个案例都由题目规则指定预期结果。
    cases = [
        ("向上：前方空格", [[None], ["U"]], 1, 0, True),
        ("向下：前方空格", [["D"], [None]], 0, 0, True),
        ("向左：前方空格", [[None, "L"]], 0, 1, True),
        ("向右：前方空格", [["R", None]], 0, 0, True),

        ("向上：相邻阻挡", [["R"], ["U"]], 1, 0, False),
        ("向下：相邻阻挡", [["D"], ["L"]], 0, 0, False),
        ("向左：相邻阻挡", [["U", "L"]], 0, 1, False),
        ("向右：相邻阻挡", [["R", "D"]], 0, 0, False),

        ("向上：隔空阻挡", [["R"], [None], [None], ["U"]], 3, 0, False),
        ("向下：隔空阻挡", [["D"], [None], [None], ["L"]], 0, 0, False),
        ("向左：隔空阻挡", [["U", None, None, "L"]], 0, 3, False),
        ("向右：隔空阻挡", [["R", None, None, "D"]], 0, 0, False),

        # 对面边界放置箭头，检查是否错误地绕到另一端。
        ("上边缘朝外", [["U"], ["D"]], 0, 0, True),
        ("下边缘朝外", [["U"], ["D"]], 1, 0, True),
        ("左边缘朝外", [["L", "R"]], 0, 0, True),
        ("右边缘朝外", [["L", "R"]], 0, 1, True),

        ("向上：后方箭头不阻挡", [[None], ["U"], ["L"]], 1, 0, True),
        ("向下：后方箭头不阻挡", [["R"], ["D"], [None]], 1, 0, True),
        ("向左：后方箭头不阻挡", [[None, "L", "U"]], 0, 1, True),
        ("向右：后方箭头不阻挡", [["D", "R", None]], 0, 1, True),

        ("其他行的箭头不阻挡", [["R", None], [None, "U"]], 0, 0, True),
        ("其他列的箭头不阻挡", [["D", None], [None, "L"]], 0, 0, True),
        ("点击空格", [[None, "R"]], 0, 0, False),
        ("空棋盘", [], 0, 0, False),
        ("空行棋盘", [[]], 0, 0, False),
        ("负行号", [["U"]], -1, 0, False),
        ("负列号", [["L"]], 0, -1, False),
        ("行号超过边界", [["D"]], 1, 0, False),
        ("列号超过边界", [["R"]], 0, 1, False),
    ]

    for name, board, row, col, expected in cases:
        # 逐行复制，保存调用前的数据，用于检查判断函数没有修改棋盘。
        before = [line[:] for line in board]
        actual = can_exit(board, row, col)

        assert actual is expected, (
            f"{name}：预期 {expected}，实际 {actual}"
        )
        assert board == before, f"{name}：判断函数不应修改棋盘"
        print(f"PASS：{name}")

    print(f"\n全部 {len(cases)} 个案例通过，每个案例均确认棋盘未被修改。")

    count_cases = [
        ("空棋盘数量", [], 0),
        ("全空格数量", [[None, None], [None, None]], 0),
        ("四方向数量", [["U", "D"], ["L", "R"]], 4),
        ("箭头与空格混合", [["U", None, "R"], [None, "L", None]], 3),
    ]
    for name, board, expected in count_cases:
        assert count_arrows(board) == expected, name
        print(f"PASS：{name}")
    print(f"全部 {len(count_cases)} 个数量统计案例通过。")


if __name__ == "__main__":
    run_tests()
