"""棋盘规则：只处理数据，可以独立于 Pygame 窗口运行。"""


# 每个方向对应 (行的变化量, 列的变化量)。
# 行号向下增加，列号向右增加。
DIRECTIONS = {
    "U": (-1, 0),
    "D": (1, 0),
    "L": (0, -1),
    "R": (0, 1),
}


def can_exit(board, row, col):
    """返回指定箭头能否飞出棋盘，不修改棋盘。

    棋盘的每一行应当等长，格子只能是 None 或 U/D/L/R。
    空棋盘、棋盘外坐标和空格返回 False。
    """
    if not board or not board[0]:
        return False

    rows = len(board)
    cols = len(board[0])

    # 先检查坐标，再访问列表，避免越界或误用 Python 的负下标。
    if not (0 <= row < rows and 0 <= col < cols):
        return False

    direction = board[row][col]
    if direction is None:
        return False

    dr, dc = DIRECTIONS[direction]

    # 从前方第一格开始，不能把箭头自己当成阻挡物。
    r = row + dr
    c = col + dc

    while 0 <= r < rows and 0 <= c < cols:
        # 任意方向的箭头都能阻挡；空格则继续向前检查。
        if board[r][c] is not None:
            return False

        r += dr
        c += dc

    # 已经走出棋盘，说明整条前方路径都没有阻挡。
    return True
