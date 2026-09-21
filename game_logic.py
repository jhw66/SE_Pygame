"""纯数据规则：路径按尾到头排列，距离单位为格"""
from dataclasses import dataclass, field

Cell = tuple[int, int]
# 用行列增量统一表达四个方向，绘制与规则共用这张表。
DIRECTIONS = {"U": (-1, 0), "D": (1, 0), "L": (0, -1), "R": (0, 1)}
NOSE_EXTENT = 0.28
TAIL_EXTENT = 0.25


def positive_integer(value, name):
    # 配置只接受真正的正整数，排除布尔值和浮点数。
    if type(value) is not int or value < 1:
        raise ValueError(f"{name}必须是正整数")


# 不可变箭头对象：路径按尾到头排列，单格和弯曲箭头共用结构。
@dataclass(frozen=True)
class Arrow:
    id: int
    cells: tuple[Cell, ...]
    direction: str

    # 在自动初始化之后检查数据是否合法。
    def __post_init__(self):
        # 创建时统一路径格式，并检查相邻性、重复格及尖端方向。
        if type(self.id) is not int or self.id < 0:
            raise ValueError("箭头编号必须是非负整数")
        cells = tuple(tuple(cell) for cell in self.cells)
        object.__setattr__(self, "cells", cells)
        if not cells or any(len(c) != 2 or any(type(v) is not int for v in c) for c in cells):
            raise ValueError("路径必须包含整数行列坐标")
        if self.direction not in DIRECTIONS:
            raise ValueError("方向必须为 U/D/L/R")
        if len(set(cells)) != len(cells):
            raise ValueError("路径不能重叠或自交")
        for a, b in zip(cells, cells[1:]):
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                raise ValueError("路径必须逐格上下左右相连")
        if len(cells) > 1:
            a, b = cells[-2:]
            if (b[0] - a[0], b[1] - a[1]) != DIRECTIONS[self.direction]:
                raise ValueError("尖端方向必须与最后一段路径一致")

    @property
    def head(self):
        return self.cells[-1]


# 箭头字典保存完整对象，占用表负责快速查询每格属于谁
@dataclass
class BoardState:
    rows: int
    cols: int
    arrows: dict[int, Arrow] = field(default_factory=dict)
    occupancy: list[list[int | None]] = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        positive_integer(self.rows, "行数")
        positive_integer(self.cols, "列数")
        arrows = dict(self.arrows)
        self.arrows = {}
        self.occupancy = [[None] * self.cols for _ in range(self.rows)]
        for arrow_id, arrow in arrows.items():
            if arrow_id != arrow.id:
                raise ValueError("箭头字典的编号不一致")
            self.add(arrow)

    def inside(self, cell):
        r, c = cell
        return 0 <= r < self.rows and 0 <= c < self.cols

    def add(self, arrow):
        # 全部格子验证通过后，再同步写入对象和占用表。
        if arrow.id in self.arrows:
            raise ValueError("箭头编号重复")
        for cell in arrow.cells:
            if not self.inside(cell):
                raise ValueError("箭头路径超出棋盘")
            if self.occupancy[cell[0]][cell[1]] is not None:
                raise ValueError("不同箭头不能占用同一格")
        self.arrows[arrow.id] = arrow
        for r, c in arrow.cells:
            self.occupancy[r][c] = arrow.id

    def remove(self, arrow_id):
        # 按支删除箭头，同时清空它占用的所有身体格与头部格。
        arrow = self.arrows.pop(arrow_id)
        for r, c in arrow.cells:
            self.occupancy[r][c] = None
        return arrow

    def copy(self):
        # Arrow 和路径不可变，可安全共享；字典和占用表必须独立。
        return BoardState(self.rows, self.cols, self.arrows)

    def head_at(self, cell):
        # 占用不代表可点击：只有路径最后一格返回箭头编号。
        if not self.inside(cell):
            return None
        arrow_id = self.occupancy[cell[0]][cell[1]]
        if arrow_id is not None and self.arrows[arrow_id].head == cell:
            return arrow_id
        return None
    
    def signature(self):
        # 比较布局时忽略编号，避免只重编号也被当成换题
        return self.rows, self.cols, tuple(sorted((a.cells, a.direction) for a in self.arrows.values()))


# 将预判结果交给动画使用，让规则判定和显示共享距离与障碍。
@dataclass(frozen=True)
class MovementPlan:
    arrow_id: int
    outcome: str  # exit / collision
    distance: float
    obstacle: Cell | None = None

# 只读扫描头部前方，计算完整离场或首次碰撞所需的逻辑距离
def plan_movement(board, arrow_id):
    arrow = board.arrows[arrow_id]
    dr, dc = DIRECTIONS[arrow.direction]  # 头部方向
    r, c = arrow.head                     # 头部位置
    own_indices = {cell: i for i, cell in enumerate(arrow.cells)}
    step = 0
    while True:
        step += 1
        cell = r + dr * step, c + dc * step
        if not board.inside(cell):
            # 等尾部到达棋盘外格子的中心，给尾端和线宽保留余量。
            return MovementPlan(arrow_id, "exit", step + len(arrow.cells) - 1 + TAIL_EXTENT)
        occupant = board.occupancy[cell[0]][cell[1]]
        blocked = occupant is not None and (                   # 其他箭头占用的格子，直接阻挡
            occupant != arrow_id or own_indices[cell] >= step  # 自己的身体格，检查到达时是否已经腾空
        )
        if blocked:
            # 从障碍格中心退半格，再减尖端长度，保证尖端不穿入障碍。
            return MovementPlan(arrow_id, "collision", step - 0.5 - NOSE_EXTENT, cell)

# 求解器与玩家点击复用同一个运动预判入口
def can_exit(board, arrow_id):
    return arrow_id in board.arrows and plan_movement(board, arrow_id).outcome == "exit"


# 移除只会减少阻挡，因此可逐轮贪心求解；不修改输入
def solve_board(board, checkpoint=None):
    working = board.copy()
    solution = []
    while working.arrows:
        # 每轮移除当前可退出的箭头；整轮无进展说明余下部分死锁
        progressed = False
        for arrow_id in list(working.arrows):
            if checkpoint:
                checkpoint()
            if can_exit(working, arrow_id):
                working.remove(arrow_id)
                solution.append(arrow_id)
                progressed = True
        if not progressed:
            return None
    return solution


# 折线路径上的浮点行列坐标；两端按首段和尖端方向延伸
def path_point(arrow, distance):
    cells = arrow.cells
    if distance < 0:
        if len(cells) == 1:
            dr, dc = DIRECTIONS[arrow.direction]
        else:
            dr, dc = cells[1][0] - cells[0][0], cells[1][1] - cells[0][1]
        return cells[0][0] + distance * dr, cells[0][1] + distance * dc
    if distance >= len(cells) - 1:
        dr, dc = DIRECTIONS[arrow.direction]
        extra = distance - (len(cells) - 1)
        return arrow.head[0] + extra * dr, arrow.head[1] + extra * dc
    i = int(distance)
    # 在相邻格中心之间线性插值，使按格计算的路径能平滑移动。
    fraction = distance - i
    a, b = cells[i:i + 2]
    return a[0] + fraction * (b[0] - a[0]), a[1] + fraction * (b[1] - a[1])


# 沿路径截取身体；回退减小同一个 progress，形状不会漂移
def moving_shape(arrow, progress=0.0):
    start = progress - TAIL_EXTENT
    # 在固定轨迹上滑动一个定长区间，身体便会逐段跟随头部抽出。
    end = len(arrow.cells) - 1 + progress + 0.12
    distances = [start] + [i for i in range(len(arrow.cells)) if start < i < end] + [end]
    return [path_point(arrow, s) for s in distances], path_point(arrow, len(arrow.cells) - 1 + progress)
