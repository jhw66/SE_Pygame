"""随机可解棋盘：先构造一条合法的消除顺序，再得到最终布局"""
import random
from game_logic import DIRECTIONS, can_exit, solve_board

# 生成随机可解棋盘，previous用于保证相邻两题布局不同
def generate_level(rows=5, cols=5, arrow_count=13, previous=None, rng=None):
    if rows < 2 or cols < 2 or not 4 <= arrow_count < rows * cols:
        raise ValueError("行列至少为 2,箭头至少 4 个且必须保留一个空格")
    if rng is None:
        rng = random.Random()

    # 选中占位格子
    cells = [(row, col) for row in range(rows) for col in range(cols)]
    # Chooses k unique random elements from a population sequence
    positions = rng.sample(cells, arrow_count)
    if previous is not None:
        old_positions = {
            (row, col) for row, line in enumerate(previous)
            for col, direction in enumerate(line) if direction is not None
        }
        if set(positions) == old_positions:
            # 极少数随机位置重复的情况，移动一个占位格，确保换题真的换布局
            positions[0] = rng.choice([cell for cell in cells if cell not in positions])

    # working 只记录尚未移除的占位格，暂用 U 表示“这里有箭头”
    working = [[None for _ in range(cols)] for _ in range(rows)]
    result = [[None for _ in range(cols)] for _ in range(rows)]
    for row, col in positions:
        working[row][col] = "U"

    unused_directions = list(DIRECTIONS)
    for _ in range(arrow_count):
        # 前四次优先选择未使用的方向，保证最终四种方向都有
        direction = rng.choice(unused_directions or list(DIRECTIONS))  # 左边列表非空，就使用左边；左边列表为空，就使用右边
        candidates = []
        for row, col in positions:
            if working[row][col] is None:
                continue
            working[row][col] = direction
            if can_exit(working, row, col):
                candidates.append((row, col))
            working[row][col] = "U"

        # 非空棋盘沿任一方向都有最外侧箭头，因此候选列表不会为空。
        row, col = rng.choice(candidates)
        result[row][col] = direction
        working[row][col] = None
        if direction in unused_directions:
            unused_directions.remove(direction)

    # 用完成后的真实布局复核；生成过程中使用的临时方向不参与这里的判断。
    if solve_board(result) is None:
        raise RuntimeError("生成棋盘未通过可解性检查")
    return result
