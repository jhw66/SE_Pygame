"""棋盘视图：浮点格子坐标与屏幕坐标转换、缩放、裁剪和绘制"""
import math
import pygame
from game_logic import DIRECTIONS, NOSE_EXTENT, moving_shape

BACKGROUND = (30, 35, 45)
GRID_COLOR = (70, 80, 99)
ARROW_COLOR = (100, 225, 190)
# 普通箭头使用十色调色板，碰撞红色单独保留为反馈色。
ARROW_PALETTE = (
    ARROW_COLOR,          # 薄荷绿
    (105, 180, 255),      # 天蓝
    (250, 211, 110),      # 金黄
    (190, 160, 255),      # 淡紫
    (245, 165, 215),      # 樱粉
    (182, 226, 122),      # 青柠
    (90, 220, 235),       # 湖蓝
    (245, 180, 105),      # 杏橙
    (135, 155, 250),      # 蓝紫
    (235, 229, 186),      # 米白
)
ERROR_COLOR = (255, 120, 120)
MIN_CLICK_SIZE = 24
MAX_CELL_SIZE = 80


# 视图只管理像素、缩放和平移，不改变棋盘的逻辑行列坐标。
class BoardView:
    def __init__(self, rect, rows, cols):
        self.rect = pygame.Rect(rect)       # 棋盘的可视区域
        self.rows, self.cols = rows, cols   # 逻辑棋盘的行数、列数
        self.arrow_colors = {}              # 箭头编号到颜色的映射
        self.fit()                          # cell_size	当前每格显示多少像素，由 fit() 初始化
                                            # x、y	当前棋盘左上角在屏幕上的位置，由 fit() 初始化

    @property
    def fit_size(self):
        # 全景应铺满可用区域，取宽度允许值和高度允许值中较小的一个像素每格
        return min(self.rect.width / self.cols, self.rect.height / self.rows)

    @property
    def max_zoom_size(self):
        return max(MAX_CELL_SIZE, self.fit_size * 4)

    @property
    def can_click(self):
        # 过小的格子仅用于概览，放大到可辨认尺寸后才允许点击
        return self.cell_size >= MIN_CLICK_SIZE - 1e-8

    def assign_colors(self, board, rng):
        # 随机洗牌十色后逐支分配；当前关卡不随帧刷新或重开换色
        self.arrow_colors = {}
        bag = []
        for arrow_id in board.arrows:
            # 每用完一袋十色就重新洗牌，减少纯随机抽样造成的颜色集中
            if not bag:
                bag = list(ARROW_PALETTE)
                rng.shuffle(bag)
            self.arrow_colors[arrow_id] = bag.pop()

    def fit(self):
        # 根据视口计算完整展示比例，并将棋盘居中
        self.cell_size = self.fit_size
        self.x = self.rect.centerx - self.cols * self.cell_size / 2 # 棋盘左边 = 视口中心横坐标 - 棋盘宽度的一半
        self.y = self.rect.centery - self.rows * self.cell_size / 2 # 棋盘顶部 = 视口中心纵坐标 - 棋盘高度的一半

    def set_board(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.fit()

    def to_screen(self, cell):
        # 逻辑格中心转屏幕像素，动画中的浮点坐标也使用同一转换
        r, c = cell
        return self.x + (c + 0.5) * self.cell_size, self.y + (r + 0.5) * self.cell_size

    def cell_at(self, pos):
        # 先挡住视口外点击，再反算行列，避免缩放或平移后误选格子。
        if not self.rect.collidepoint(pos):
            return None
        c = math.floor((pos[0] - self.x) / self.cell_size)
        r = math.floor((pos[1] - self.y) / self.cell_size)
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return r, c
        return None

    def _clamp(self):
        # 小于视口时居中，大于视口时限制拖动，防止把整张棋盘拖走
        width, height = self.cols * self.cell_size, self.rows * self.cell_size
        # 棋盘左边 ≤ 视口左边；棋盘右边 ≥ 视口右边
        # 换成对 x 的限制：视口右边 - 棋盘宽度 ≤ x ≤ 视口左边
        self.x = (self.rect.centerx - width / 2 if width <= self.rect.width
                  else min(self.rect.left, max(self.rect.right - width, self.x)))
        self.y = (self.rect.centery - height / 2 if height <= self.rect.height
                  else min(self.rect.top, max(self.rect.bottom - height, self.y)))


    def zoom(self, pos, steps):
        # 记录鼠标下的逻辑位置，缩放后调整偏移，让该位置尽量保持不动
        if not self.rect.collidepoint(pos):
            return
        wx = (pos[0] - self.x) / self.cell_size
        wy = (pos[1] - self.y) / self.cell_size
        # 最小不能小于全景尺寸，最大不能超过 max_zoom_size。
        self.cell_size = min(
            self.max_zoom_size,
            max(
                self.fit_size,
                self.cell_size * 1.2 ** max(-20, min(20, steps))
            )
        )

        # 鼠标屏幕位置 = 棋盘偏移 + 鼠标下的逻辑位置 × 格子大小
        self.x = pos[0] - wx * self.cell_size
        self.y = pos[1] - wy * self.cell_size
        self._clamp()

    def pan(self, dx, dy):
        self.x += dx
        self.y += dy
        self._clamp()

    # 窗口改变大小后，尽量保持原来的观察位置
    def resize(self, rect):
        old_center = ((self.rect.centerx - self.x) / self.cell_size,
                      (self.rect.centery - self.y) / self.cell_size)
        was_fit = abs(self.cell_size - self.fit_size) < 1e-8
        self.rect = pygame.Rect(rect)
        if was_fit:
            self.fit()
        else:
            self.cell_size = min(self.max_zoom_size, max(self.fit_size, self.cell_size))
            self.x = self.rect.centerx - old_center[0] * self.cell_size
            self.y = self.rect.centery - old_center[1] * self.cell_size
            self._clamp()

    # 先计算当前形状，再画身体和三角尖端
    def draw_arrow(self, surface, arrow, progress, color):
        # 路径画折线，尖端画三角形，所有尺寸都按当前格子大小缩放
        path, head = moving_shape(arrow, progress)
        points = [self.to_screen(point) for point in path]
        width = max(1, round(self.cell_size * 0.08))
        pygame.draw.lines(surface, color, False, points, width)    # 将多个点连成折线且不闭合
        for a, point, b in zip(points, points[1:], points[2:]):    # 修饰转角
            # 叉积非零表示发生转弯，只在折角补圆点使线条连接平滑
            if abs((point[0] - a[0]) * (b[1] - point[1])
                   - (point[1] - a[1]) * (b[0] - point[0])) > 1e-8:
                pygame.draw.circle(surface, color, point, max(1, width // 2))   # 拐角处补一个小圆
        dr, dc = DIRECTIONS[arrow.direction]
        r, c = head
        triangle = [
            (r + NOSE_EXTENT * dr, c + NOSE_EXTENT * dc),
            (r + 0.1 * dr + 0.15 * dc, c + 0.1 * dc - 0.15 * dr),
            (r + 0.1 * dr - 0.15 * dc, c + 0.1 * dc + 0.15 * dr),
        ]
        pygame.draw.polygon(surface, color, [self.to_screen(point) for point in triangle])

    # 控制绘制范围，并组织整个棋盘的绘制顺序
    def draw(self, surface, session):
        # 视口 ∩ 棋盘矩形 ∩ 原裁剪范围
        old_clip = surface.get_clip()
        board_rect = pygame.Rect(math.floor(self.x), math.floor(self.y),
                                 math.ceil(self.cols * self.cell_size),
                                 math.ceil(self.rows * self.cell_size))
        #.clip(old_clip) 是为了让这个函数也能适用于外层已经设置了更小裁剪区域的情况，比如：外层要求只更新屏幕中的一小块区域 surface.set_clip(dirty_rect)
        surface.set_clip(self.rect.clip(board_rect).clip(old_clip))
        # 只绘制可见网格线，放大后不会遍历整张巨大棋盘的格子。
        first_col = max(0, math.floor((self.rect.left - self.x) / self.cell_size))
        last_col = min(self.cols, math.ceil((self.rect.right - self.x) / self.cell_size))
        first_row = max(0, math.floor((self.rect.top - self.y) / self.cell_size))
        last_row = min(self.rows, math.ceil((self.rect.bottom - self.y) / self.cell_size))
        # 画竖线
        for c in range(first_col, last_col + 1):
            x = self.x + c * self.cell_size
            pygame.draw.line(surface, GRID_COLOR, (x, self.y), (x, self.y + self.rows * self.cell_size))
        # 画横线
        for r in range(first_row, last_row + 1):
            y = self.y + r * self.cell_size
            pygame.draw.line(surface, GRID_COLOR, (self.x, y), (self.x + self.cols * self.cell_size, y))
        # 画外边框
        pygame.draw.rect(surface, GRID_COLOR, board_rect, width=1)
        # 绘制静止箭头
        motion = session.motion
        for arrow in session.board.arrows.values():
            # 没有动画 → 所有箭头都画在原位；存在动画 → 跳过正在移动的那一支
            if motion is None or arrow.id != motion.plan.arrow_id:
                self.draw_arrow(surface, arrow, 0, self.arrow_colors.get(arrow.id, ARROW_COLOR))
        # 单独绘制运动对象
        if motion is not None:
            self.draw_arrow(surface, session.board.arrows[motion.plan.arrow_id], motion.progress,
                            ERROR_COLOR if motion.collided else self.arrow_colors.get(motion.plan.arrow_id, ARROW_COLOR))
        # 恢复进入函数前的裁剪状态。否则后续绘制侧栏、按钮和文字时，仍然会受到棋盘裁剪范围限制，导致部分界面无法显示
        surface.set_clip(old_clip)
