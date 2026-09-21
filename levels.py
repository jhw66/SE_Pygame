"""可配置的随机关卡、手工 JSON 关卡和设计指标"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
import time

from game_logic import Arrow, BoardState, DIRECTIONS, can_exit, positive_integer, solve_board


# 关卡设计参数集中管理，默认值不代表棋盘尺寸的规则限制。
@dataclass(frozen=True)
class LevelConfig:
    rows: int = 5
    cols: int = 5
    arrow_count: int = 13
    min_length: int = 1
    max_length: int = 1
    turn_probability: float = 0.0

    def __post_init__(self):
        # 行列数、支数和长度必须是正整数
        for name in ("rows", "cols", "arrow_count", "min_length", "max_length"):
            positive_integer(getattr(self, name), name)
        # 最小长度不能大于最大长度
        if self.min_length > self.max_length:
            raise ValueError("最小长度不能大于最大长度")
        # 棋盘至少能容纳所有箭头的最小长度
        if self.arrow_count * self.min_length > self.rows * self.cols:
            raise ValueError("空间不足：箭头支数 × 最小长度不能超过棋盘总格数")
        # 转弯概率必须是 0～1 之间的有限数值
        if (isinstance(self.turn_probability, bool)
                or not isinstance(self.turn_probability, (int, float))
                or not math.isfinite(self.turn_probability)
                or not 0 <= self.turn_probability <= 1):
            raise ValueError("转弯概率必须在 0 到 1 之间")


# 区分生成失败与主动取消，让调用方决定提示还是丢弃任务
class GenerationError(RuntimeError):
    pass


class GenerationCancelled(GenerationError):
    pass

# 构造可解的单格布局
def _singletons(config, rng, checkpoint):
    # 随机抽取不重复的位置
    positions = [divmod(i, config.cols) for i in rng.sample(
        range(config.rows * config.cols), config.arrow_count)]
    occupied = set(positions)   # 构造过程中，尚未虚拟移除的位置
    result = {}                 # 已经确定方向、最终要放回棋盘的箭头
    unused = list(DIRECTIONS)
    while occupied:
        checkpoint()
        direction = rng.choice(unused or list(DIRECTIONS))
        dr, dc = DIRECTIONS[direction]
        candidates = []
        for r, c in positions:
            checkpoint()
            if (r, c) not in occupied:
                continue
            rr, cc = r + dr, c + dc
            while 0 <= rr < config.rows and 0 <= cc < config.cols:
                checkpoint()
                if (rr, cc) in occupied:
                    break
                rr, cc = rr + dr, cc + dc
            # while 正常走出边界才进入 else，遇到障碍 break 则不会进入
            else:     
                candidates.append((r, c))
        cell = rng.choice(candidates)
        arrow_id = len(result)
        result[arrow_id] = Arrow(arrow_id, (cell), direction)
        # 构造时的虚拟移除顺序，本身就是最终布局的一条解
        # 第一支箭头时，后面所有箭头的位置都已经被检查过了；
        # 如果它们会挡住第一支，这个方向就无法通过检查；所以说从本质上构成了防止死锁的前提
        occupied.remove(cell)
        if direction in unused:
            unused.remove(direction)
    return BoardState(config.rows, config.cols, result)

# 从箭尾逐格扩展
def _grow(board, arrow_id, probability, rng, checkpoint):
    # 每次只向箭尾加一格；第一次反向延长，之后按权重选择直行或转弯
    arrow = board.arrows[arrow_id]
    if len(arrow.cells) == 1:
        dr, dc = DIRECTIONS[arrow.direction]
        choices = [((-dr, -dc), 1.0)]
    else:
        a, b = arrow.cells[:2]
        dr, dc = a[0] - b[0], a[1] - b[1]    # 尾巴的方向
        # 继续直行以及两个垂直转向
        choices = [((dr, dc), 1 - probability),  
                   ((-dc, dr), probability / 2),
                   ((dc, -dr), probability / 2)]
    choices = [(delta, weight) for delta, weight in choices if weight > 0]
    while choices:
        checkpoint()
        # 按权重抽取候选
        index = rng.choices(range(len(choices)), weights=[w for _, w in choices])[0]
        (dr, dc), _ = choices.pop(index)
        r, c = arrow.cells[0]
        cell = r + dr, c + dc
        # 新增位置在棋盘内，而且没有任何箭头占用，包括该箭头自身
        if not board.inside(cell) or board.occupancy[cell[0]][cell[1]] is not None:
            continue
        # 箭头路径按“尾部 → 头部”排列，因此扩展时在路径最前面加坐标
        extended = Arrow(arrow.id, (cell,) + arrow.cells, arrow.direction)
        board.remove(arrow_id)
        board.add(extended)
        accepted = False
        # 暂时应用扩展并验解，失败或中途异常时都在 finally 中恢复旧箭头
        try:
            accepted = solve_board(board, checkpoint) is not None
        finally:
            if not accepted:
                board.remove(arrow_id)
                board.add(arrow)
        if accepted:
            return True
    return False

# 先满足最小长度，再尝试增加长度，只返回满足配置且已验解的布局；失败不修改 previous
def generate_level(config=None, previous=None, rng=None, *, max_attempts=100, time_budget=5.0, cancel_event=None):
    # 检查参数、设置预算
    config = config or LevelConfig()
    positive_integer(max_attempts, "尝试次数")
    if not math.isfinite(time_budget) or time_budget <= 0:
        raise ValueError("生成时间预算必须大于零")
    rng = rng if rng is not None else random.Random()
    deadline = time.monotonic() + time_budget
    # 闭包检查取消和超时
    def checkpoint():
        # 在生成和求解循环中协作检查截止时间及取消信号
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled("已取消生成")
        if time.monotonic() >= deadline:
            raise GenerationError("生成超时，请减少支数、最小长度或扩大棋盘")

    old_signature = previous.signature() if previous is not None else None
    for _ in range(max_attempts):
        checkpoint()
        board = _singletons(config, rng, checkpoint)
        ids = list(board.arrows)
        minimum_ok = True
        # 先逐轮满足所有箭头的最小长度，任何一支失败就重新布局
        for _ in range(1, config.min_length):
            rng.shuffle(ids)
            for arrow_id in ids:
                if not _grow(board, arrow_id, config.turn_probability, rng, checkpoint):
                    minimum_ok = False
                    break
            if not minimum_ok:
                break
        if not minimum_ok:
            continue
        # 最大长度是上界，不是承诺；扩展失败时保留已合法的较短路径
        rng.shuffle(ids)
        cap = min(config.max_length, 
                  config.rows * config.cols - (config.arrow_count - 1) * config.min_length) # 表示扣除其他箭头至少需要的空间后，单支箭头理论上最多能占多少格
        for arrow_id in ids:
            target = rng.randint(config.min_length, cap)
            while len(board.arrows[arrow_id].cells) < target:
                if not _grow(board, arrow_id, config.turn_probability, rng, checkpoint):
                    break
        checkpoint()
        # 返回前确认整盘可解，而且不是上一题仅换了编号；再次确认最终布局可以全部消除
        if board.signature() != old_signature and solve_board(board, checkpoint) is not None:
            checkpoint()
            return board
    raise GenerationError("已达到生成尝试上限，请调整尺寸、支数或长度范围")

# 没有 arrows 字段时读取随机配置；有具体箭头时创建手工棋盘并验解
def load_level(path):
    # Path 负责路径和文件读取
    # json.loads() 将 JSON 文本解析成 Python 对象
    # utf-8-sig 同时兼容普通 UTF-8 和带 BOM 的 UTF-8 文件
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("关卡文件必须是 JSON 对象")
    
    # 没有具体箭头时返回随机配置，有具体箭头时按手工布局加载。
    if "arrows" not in data:
        return LevelConfig(**data)   # **data 是字典解包；{"rows": 7, "cols": 10} -> LevelConfig(rows=7, cols=10)
    if set(data) != {"rows", "cols", "arrows"}:
        raise ValueError("手工关卡只包含 rows、cols、arrows")
    arrows = {}
    for item in data["arrows"]:
        arrow = Arrow(**item)
        if arrow.id in arrows:
            raise ValueError("手工关卡箭头编号重复")
        arrows[arrow.id] = arrow
    board = BoardState(data["rows"], data["cols"], arrows)
    if solve_board(board) is None:
        raise ValueError("手工关卡无法完整消除，请调整路径或方向")
    return board

# 统计占用率、开局可消除支数和解除阻挡的轮数
def level_metrics(board):
    working = board.copy()
    first_choices = 0
    rounds = 0
    while working.arrows:
        # 先收集一整轮可消除对象再统一删除，用于统计解除阻挡的轮数。
        removable = []
        for arrow_id in working.arrows:
            if can_exit(working, arrow_id):
                removable.append(arrow_id)
        if rounds == 0:
            first_choices = len(removable)
        if not removable:
            rounds = None
            break
        for arrow_id in removable:
            working.remove(arrow_id)
        rounds += 1
    return {
        # 所有箭头占用格数 ÷ 棋盘总格数
        "occupancy_ratio": sum(len(a.cells) for a in board.arrows.values()) / (board.rows * board.cols),
        # 初始状态能够直接退出的箭头支数
        "initial_choices": first_choices,
        # 每轮同时移除当前全部可退出箭头，需要多少轮清空
        "unlock_rounds": rounds,                                                                         
    }
