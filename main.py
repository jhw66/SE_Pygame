"""Pygame 入口：关卡配置、窗口事件和异步生成。导入不会启动游戏。"""
import argparse
from pathlib import Path
import queue
import random
import threading
import time
import pygame

from board_view import BoardView, BACKGROUND, ARROW_COLOR, ERROR_COLOR
from game_state import GameSession, FAILED, WON
from levels import (GenerationCancelled, GenerationError, LevelConfig,
                    generate_level, level_metrics, load_level)

TEXT = (235, 240, 250)
MUTED = (170, 180, 200)
BUTTON = (55, 75, 90)


# 应用层连接窗口、游戏状态、棋盘视图和后台关卡任务。
class GameApp:
    def __init__(self, screen, config=None, board=None, seed=None, level_factory=None):
        self.screen = screen
        self.config = config if config is not None or board is not None else LevelConfig()
        self.level_factory = level_factory or generate_level
        # 允许测试替换生成函数，复现生成失败、取消与延迟返回等情况。
        self.rng = random.Random(seed)
        self.color_rng = random.Random(seed)  # 配色不消耗关卡生成的随机数序列
        self.session = None
        self.metrics = None
        self.running = True
        self.generating = False
        self.notice = ""
        self.dragging = False
        self.left_press = None
        self.results = queue.SimpleQueue()
        # 队列传递后台结果；任务编号用于识别已取消的旧结果。
        self.job_id = 0
        self.cancel_event = None
        self.worker = None
        font_path = pygame.font.match_font(["microsoftyahei", "simhei", "simsun"])
        self.font = pygame.font.Font(font_path, 20)
        self.small_font = pygame.font.Font(font_path, 17)
        self.compact_font = pygame.font.Font(font_path, 14)
        rows = board.rows if board is not None else self.config.rows
        cols = board.cols if board is not None else self.config.cols
        self.view = BoardView(self.layout_ui(rows, cols), rows, cols)
        if board is not None:
            self.install(board)
        else:
            self.request_new()

    def layout_ui(self, rows, cols):
        """棋盘在整窗居中；控件使用自然留白，不覆盖任何可玩格子。"""
        w, h = self.screen.get_size()

        def fitted(width, height):
            scale = min(width / cols, height / rows)
            rect = pygame.Rect(0, 0, round(cols * scale), round(rows * scale))
            rect.center = (w // 2, h // 2)
            return rect

        area = fitted(w - 16, h - 16)
        # 优先用棋盘左右的自然留白放控件，空间不足时改用上下窄栏。
        if area.left >= 104:
            self.hud_mode = "sides"
            panel_width = min(180, area.left - 24)
            left_x = (area.left - panel_width) // 2
            right_x = area.right + (w - area.right - panel_width) // 2
            self.summary_rect = pygame.Rect(left_x, h // 2 - 134, panel_width, 94)
            self.status_rect = pygame.Rect(left_x, h // 2 - 24, panel_width, min(240, h // 2 - 4))
            first_y = h // 2 - 106
            self.buttons = {
                key: pygame.Rect(right_x, first_y + i * 54, panel_width, 42)
                for i, key in enumerate(("new", "restart", "fit"))
            }
            self.help_rect = pygame.Rect(right_x, first_y + 176, panel_width, 110)
        else:
            # 无足够自然留白时，只预留两条窄边带，棋盘仍在窗口正中。
            if area.top < 56:
                area = fitted(w - 16, h - 112)
            self.hud_mode = "bars"
            self.summary_rect = pygame.Rect(16, area.top - 44, w // 2 - 24, 30)
            self.help_rect = pygame.Rect(w // 2, area.top - 44, w // 2 - 16, 30)
            self.buttons = {
                key: pygame.Rect(16 + i * 122, area.bottom + 8, 112, 40)
                for i, key in enumerate(("new", "restart", "fit"))
            }
            self.status_rect = pygame.Rect(392, area.bottom + 7, w - 408,
                                           min(110, h - area.bottom - 15))
        return area

    def install(self, board, metrics=None):
        # 新题统一加载布局、全景和配色，同时清理未结束的鼠标手势。
        if self.session is None:
            self.session = GameSession(board)
        else:
            self.session.load(board)
        self.view.rect = self.layout_ui(board.rows, board.cols)
        self.view.set_board(board.rows, board.cols)
        self.view.assign_colors(board, self.color_rng)
        self.metrics = level_metrics(board) if metrics is None else metrics
        self.notice = ""
        self.cancel_pointer()

    def cancel_pointer(self):
        # 清除拖动和待确认点击，防止重开后处理旧的松开事件。
        self.dragging = False
        self.left_press = None

    def cancel_generation(self):
        # 请求旧任务尽快停止，并立即让其编号失效，不阻塞窗口等待线程。
        if self.cancel_event is not None:
            self.cancel_event.set()
        self.job_id += 1
        self.generating = False

    def request_new(self):
        # 手工关卡不能换题；生成期间保留当前布局，只暂停棋盘操作。
        if self.config is None or self.generating:
            return
        self.cancel_generation()
        self.cancel_event = threading.Event()
        self.generating = True
        self.cancel_pointer()
        self.notice = "正在生成可解关卡……"
        if self.session is not None:
            self.session.motion = None
            if self.session.mistakes_remaining == 0:
                self.session.state = FAILED
        token = self.job_id
        cancel = self.cancel_event
        previous = self.session.initial.copy() if self.session is not None else None
        # 每个任务拥有独立 RNG，旧任务取消后不会与新任务争用随机数状态。
        rng = random.Random(self.rng.getrandbits(64))

        def work():
            # 后台只做数据计算，通过线程安全队列返回，不操作 Pygame 窗口。
            deadline = time.monotonic() + 5.0

            def checkpoint():
                if cancel.is_set():
                    raise GenerationCancelled("已取消生成")
                if time.monotonic() >= deadline:
                    raise GenerationError("生成超时，请调整关卡配置")

            try:
                board = self.level_factory(self.config, previous=previous, rng=rng, cancel_event=cancel)
                checkpoint()
                metrics = level_metrics(board, checkpoint)
                self.results.put((token, board, metrics, None))
            except Exception as exc:
                self.results.put((token, None, None, str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        # 启动后台任务后立刻返回，主循环继续处理关闭、缩放与绘制。
        self.worker.start()

    def restart(self):
        # 恢复同一道题，不重置视图和颜色，也不消耗关卡随机数。
        self.cancel_generation()
        if self.session is not None:
            self.session.restart()
        self.notice = ""
        self.cancel_pointer()

    def update(self, dt):
        # 主线程领取结果；旧任务即使晚到，也不能覆盖重开或新题。
        while True:
            try:
                token, board, metrics, error = self.results.get_nowait()
            except queue.Empty:
                break
            if token != self.job_id:
                continue
            self.generating = False
            if error is not None:
                self.notice = "生成失败：" + error
            else:
                self.install(board, metrics)
        if self.session is not None and not self.generating:
            self.session.update(dt)

    def handle_events(self, events):
        # 同一批事件中重开或换题后，忽略随后排队的棋盘点击。
        suppress_clicks = False
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
                self.cancel_generation()
                break
            if event.type == pygame.VIDEORESIZE:
                # 窗口变动后重新安排控件，再保持或调整原观察位置。
                self.cancel_pointer()
                self.screen = pygame.display.set_mode((max(800, event.w), max(600, event.h)), pygame.RESIZABLE)
                self.view.resize(self.layout_ui(self.view.rows, self.view.cols))
            elif event.type == pygame.MOUSEWHEEL:
                # 普通滚轮缩放，Shift 加滚轮或横向滚轮负责左右平移。
                pos = getattr(event, "pos", pygame.mouse.get_pos())
                if not self.view.rect.collidepoint(pos):
                    continue
                self.left_press = None
                dx = getattr(event, "precise_x", getattr(event, "x", 0))
                dy = getattr(event, "precise_y", getattr(event, "y", 0))
                mods = getattr(event, "mod", pygame.key.get_mods())
                step = self.view.cell_size * 2
                if dx:
                    # 触控板或横向滚轮：向右滚动时，棋盘内容向左移动。
                    self.view.pan(-dx * step, dy * step)
                elif mods & pygame.KMOD_SHIFT:
                    self.view.pan(dy * step, 0)
                else:
                    self.view.zoom(pos, dy)
            elif event.type == pygame.KEYDOWN:
                # 方向键移动观察区域，位移以当前格子大小为单位。
                moves = {pygame.K_LEFT: (1, 0), pygame.K_RIGHT: (-1, 0),
                         pygame.K_UP: (0, 1), pygame.K_DOWN: (0, -1)}
                if event.key in moves:
                    self.left_press = None
                    dx, dy = moves[event.key]
                    self.view.pan(dx * self.view.cell_size * 2, dy * self.view.cell_size * 2)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
                self.dragging = False
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                # 左键松开才确认点击；已经拖动或跨格的手势不会触发消除。
                press, self.left_press = self.left_press, None
                if press is None or press["dragged"] or not press["can_click"] or suppress_clicks:
                    continue
                dx, dy = event.pos[0] - press["start"][0], event.pos[1] - press["start"][1]
                if dx * dx + dy * dy >= 36:
                    continue
                cell = self.view.cell_at(event.pos)
                if cell is not None and cell == press["cell"] and not self.generating and self.session is not None:
                    if self.view.can_click:
                        if self.session.click(cell):
                            self.notice = ""
                    else:
                        self.notice = "当前为全景概览，请滚轮放大后点击头部格"
            elif event.type == pygame.MOUSEMOTION:
                # 位移达到六像素就认定为拖动，后续只平移而不点击。
                if self.dragging:
                    self.view.pan(*event.rel)
                elif self.left_press is not None:
                    press = self.left_press
                    pos = event.pos
                    dx, dy = pos[0] - press["start"][0], pos[1] - press["start"][1]
                    if not press["dragged"] and dx * dx + dy * dy >= 36:
                        press["dragged"] = True
                        self.view.pan(dx, dy)
                    elif press["dragged"]:
                        self.view.pan(pos[0] - press["last"][0], pos[1] - press["last"][1])
                    press["last"] = pos
            elif event.type == pygame.WINDOWFOCUSLOST:
                # 切出窗口时取消手势，避免回来后出现粘住拖动或误点击。
                self.cancel_pointer()
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 2:
                    self.left_press = None
                    self.dragging = self.view.rect.collidepoint(event.pos)
                    continue
                if event.button != 1:
                    continue
                self.left_press = None
                if self.buttons["fit"].collidepoint(event.pos):
                    self.cancel_pointer()
                    self.view.fit()
                elif self.buttons["restart"].collidepoint(event.pos):
                    if self.session is not None:
                        self.restart()
                        suppress_clicks = True
                elif self.buttons["new"].collidepoint(event.pos):
                    if self.config is not None and not self.generating:
                        self.request_new()
                        suppress_clicks = True
                elif not suppress_clicks and self.view.rect.collidepoint(event.pos):
                    # 按下时仅记录候选点击位置及资格，等待松开或转为拖动。
                    self.left_press = {
                        "start": event.pos, "last": event.pos,
                        "cell": self.view.cell_at(event.pos), "dragged": False,
                        "can_click": not self.generating and self.session is not None
                                     and self.session.motion is None,
                    }

    def draw_text(self, text, pos, color=TEXT, font=None):
        self.screen.blit((font or self.font).render(text, True, color), pos)

    def draw_fitted(self, text, rect, color=TEXT, centered=False):
        """窄边栏也能完整显示必要文字；不让文字越过棋盘边界。"""
        font = self.compact_font
        for candidate in (self.font, self.small_font, self.compact_font):
            if candidate.size(text)[0] <= rect.width:
                font = candidate
                break
        while text and font.size(text)[0] > rect.width:
            text = text[:-2] + "…" if len(text) > 2 else ""
        surface = font.render(text, True, color)
        pos = surface.get_rect(center=rect.center) if centered else rect.topleft
        self.screen.blit(surface, pos)

    def draw_wrapped(self, text, rect, color=MUTED):
        # 窄边栏按像素宽度换行，超出可用高度时截断并显示省略号。
        font = self.compact_font if rect.width < 110 else self.small_font
        lines, line = [], ""
        for char in text:
            if char == "\n":
                lines.append(line)
                line = ""
                continue
            if font.size(line + char)[0] > rect.width and line:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
        step = font.get_linesize() + 4
        limit = max(1, rect.height // step)
        if len(lines) > limit:
            lines = lines[:limit]
            lines[-1] = lines[-1][:-1] + "…"
        old_clip = self.screen.get_clip()
        self.screen.set_clip(rect.clip(old_clip))
        for i, line in enumerate(lines):
            self.draw_text(line, (rect.x, rect.y + i * step), color, font)
        self.screen.set_clip(old_clip)

    def draw(self):
        # 先画棋盘，再在独立区域显示必要状态、简短说明和三个按钮。
        screen = self.screen
        screen.fill(BACKGROUND)
        pygame.draw.rect(screen, (36, 43, 56), self.view.rect)
        if self.session is not None:
            self.view.draw(screen, self.session)
        else:
            message = "正在准备棋盘…" if self.generating else "请点击换一题重试"
            self.draw_fitted(message, self.view.rect, MUTED, centered=True)

        title, color = "一箭又一箭", TEXT
        remaining = len(self.session.board.arrows) if self.session is not None else "—"
        chances = self.session.mistakes_remaining if self.session is not None else "—"
        status = self.notice
        if self.session is not None:
            if self.session.state == FAILED:
                title, color = "本关失败", ERROR_COLOR
                status = status or "点击重新开始再试一次"
            elif self.session.state == WON:
                title, color = "本题通关", ARROW_COLOR
                status = status or "重新开始或换一题"
            elif self.session.motion is not None and self.session.motion.collided:
                status = status or "碰撞后原路返回"
        if not self.view.can_click:
            status = status or "请滚轮放大后点击头部格"

        rect = self.summary_rect
        if self.hud_mode == "sides":
            self.draw_fitted(title, pygame.Rect(rect.x, rect.y, rect.width, 26), color)
            self.draw_fitted(f"箭头 {remaining}", pygame.Rect(rect.x, rect.y + 40, rect.width, 26))
            self.draw_fitted(f"机会 {chances}", pygame.Rect(rect.x, rect.y + 72, rect.width, 26))
            self.draw_wrapped("点击头部格\n滚轮缩放\n左键拖动\n← → 平移", self.help_rect)
        else:
            self.draw_fitted(f"{title}  ·  剩余 {remaining}  ·  机会 {chances}", rect, color)
            self.draw_fitted("点击头部 · 滚轮缩放 · 拖动/←→平移", self.help_rect, MUTED)
        self.draw_wrapped(status, self.status_rect,
                          ERROR_COLOR if "失败" in status or color == ERROR_COLOR else MUTED)

        labels = {"new": "生成中…" if self.generating else "换一题",
                  "restart": "重新开始", "fit": "全景"}
        for key, rect in self.buttons.items():
            enabled = not ((key == "new" and (self.config is None or self.generating))
                           or (key == "restart" and self.session is None))
            pygame.draw.rect(screen, BUTTON if enabled else (39, 43, 52), rect, border_radius=8)
            pygame.draw.rect(screen, (82, 133, 126) if enabled else GRID_DISABLED,
                             rect, width=1, border_radius=8)
            self.draw_fitted(labels[key], rect.inflate(-12, -8),
                             TEXT if enabled else MUTED, centered=True)

    def close(self):
        self.cancel_generation()
        self.running = False


GRID_DISABLED = (75, 80, 90)


def parse_args(argv=None):
    # 命令行参数或 JSON 二选一创建关卡来源，错误配置在启动窗口前报告。
    parser = argparse.ArgumentParser(description="可配置的箭头消除游戏")
    parser.add_argument("--level", type=Path, help="随机配置或手工布局 JSON")
    parser.add_argument("--seed", type=int, help="复现同一系列随机题")
    for name in ("rows", "cols", "arrow-count", "min-length", "max-length"):
        parser.add_argument("--" + name, type=int)
    parser.add_argument("--turn-probability", type=float)
    args = parser.parse_args(argv)
    overrides = {name: getattr(args, name) for name in
                 ("rows", "cols", "arrow_count", "min_length", "max_length", "turn_probability")
                 if getattr(args, name) is not None}
    if args.level is not None and overrides:
        parser.error("--level 与行列/形状参数不能同时使用")
    try:
        source = load_level(args.level) if args.level is not None else LevelConfig(**overrides)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.error(str(exc))
    return args, source


def main(argv=None):
    # 初始化窗口并进入事件、状态更新、绘制的逐帧循环。
    args, source = parse_args(argv)
    pygame.init()
    pygame.key.set_repeat(250, 40)
    pygame.display.set_caption("一箭又一箭")
    screen = pygame.display.set_mode((960, 640), pygame.RESIZABLE)
    if isinstance(source, LevelConfig):
        app = GameApp(screen, config=source, seed=args.seed)
    else:
        app = GameApp(screen, board=source, seed=args.seed)
    clock = pygame.time.Clock()
    try:
        while app.running:
            dt = clock.tick(60) / 1000
            # tick 返回毫秒，换算为秒交给动画；速度不依赖实际帧数。
            app.handle_events(pygame.event.get())
            if not app.running:
                break
            app.update(dt)
            app.draw()
            pygame.display.flip()
    finally:
        app.close()
        pygame.quit()


if __name__ == "__main__":
    # 直接运行才启动游戏；测试导入 main 时不会弹窗。
    main()
