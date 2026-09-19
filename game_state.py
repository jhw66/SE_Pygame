"""游戏状态和动画计时：不依赖窗口，便于确定性测试。"""
from dataclasses import dataclass
from game_logic import MovementPlan, plan_movement

PLAYING, FAILED, WON = "playing", "failed", "won"
BASE_MOVE_SPEED = 4.0  # 小棋盘的基础速度，单位格/秒
MAX_ACTION_DURATION = 1.0  # 包含碰撞停顿和返回的完整动作上限
COLLISION_PAUSE = 0.1
MAX_MISTAKES = 3


# 一次动画的运行数据：预判结果、固定速度、阶段和当前路程。
@dataclass
class Motion:
    plan: MovementPlan
    speed: float
    phase: str = "forward"
    progress: float = 0.0
    pause_remaining: float = COLLISION_PAUSE

    @property
    def collided(self):
        return self.phase in ("pause", "return")


# 管理一局游戏的规则状态，时间推进不依赖 Pygame 窗口。
class GameSession:
    def __init__(self, board):
        self.load(board)

    def load(self, board):
        # 保存原始布局快照，供重玩同一题使用。
        self.initial = board.copy()
        self.restart()

    def restart(self):
        # 恢复布局和机会，并丢弃旧动画；视图位置由界面层保留。
        self.board = self.initial.copy()
        self.state = PLAYING if self.board.arrows else WON
        self.mistakes_remaining = MAX_MISTAKES
        self.motion = None
        self.status = "点击头部所在格；身体点击无效"

    def click(self, cell):
        # 只在可操作且没有动画时接受头部点击，身体与空格直接忽略。
        if self.state != PLAYING or self.motion is not None:
            return False
        arrow_id = self.board.head_at(cell)
        if arrow_id is None:
            return False
        plan = plan_movement(self.board, arrow_id)
        # 棋盘越大基础速度越快；长路径另外加速，完整动作不超过一秒。
        scaled_speed = BASE_MOVE_SPEED * max(1.0, max(self.board.rows, self.board.cols) / 5)
        travel_budget = (MAX_ACTION_DURATION if plan.outcome == "exit"
                         else (MAX_ACTION_DURATION - COLLISION_PAUSE) / 2)
        self.motion = Motion(plan, max(scaled_speed, plan.distance / travel_budget))
        self.status = "箭头正在前进"
        return True

    def update(self, dt):
        if dt < 0:
            raise ValueError("时间增量不能为负数")
        # 消耗跨越状态边界的剩余 dt，保证大帧和多个小帧结果一致。
        while self.motion is not None and dt > 0:
            motion = self.motion
            if motion.phase == "forward":
                # 前进到预判终点之前，保持逻辑棋盘和剩余数量不变。
                needed = (motion.plan.distance - motion.progress) / motion.speed
                elapsed = min(dt, needed)
                motion.progress = min(motion.plan.distance, motion.progress + elapsed * motion.speed)
                dt -= elapsed
                if elapsed + 1e-10 < needed:
                    break
                motion.progress = motion.plan.distance
                if motion.plan.outcome == "exit":
                    # 完整离场才提交删除；最后一支删除后才通关。
                    self.board.remove(motion.plan.arrow_id)
                    self.motion = None
                    self.status = "箭头已消除"
                    if not self.board.arrows:
                        self.state = WON
                        self.status = "本题通关！可以重玩，或换一题"
                else:
                    # 只在首次接触障碍、切入停顿阶段时扣一次机会。
                    motion.phase = "pause"
                    self.mistakes_remaining -= 1
                    self.status = "发生碰撞，机会减 1，正在返回"
            elif motion.phase == "pause":
                # 碰撞变红后短暂停顿，再反向播放同一条轨迹。
                elapsed = min(dt, motion.pause_remaining)
                motion.pause_remaining -= elapsed
                dt -= elapsed
                if motion.pause_remaining > 1e-10:
                    break
                motion.phase = "return"
            else:
                # 减小路程直到回原位，第三次碰撞也要返回结束才失败。
                needed = motion.progress / motion.speed
                elapsed = min(dt, needed)
                motion.progress = max(0.0, motion.progress - elapsed * motion.speed)
                dt -= elapsed
                if elapsed + 1e-10 < needed:
                    break
                self.motion = None
                if self.mistakes_remaining == 0:
                    self.state = FAILED
                    self.status = "失误机会已用尽，本关失败"
                else:
                    self.status = "已回到原位，请选择其他箭头"
