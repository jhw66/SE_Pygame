"""Pygame 入口：关卡配置、窗口事件和异步生成"""
import argparse
import math
import queue
import random
import threading
import pygame

from board_view import BoardView, BACKGROUND, ARROW_COLOR, ERROR_COLOR
from game_state import GameSession, FAILED, WON
from levels import generate_level
from campaign import Campaign, LEVEL_COUNT, read_admin_password

TEXT = (235, 240, 250)
MUTED = (170, 180, 200)
BUTTON = (55, 75, 90)
HEART_RED = (240, 76, 100)
HEART_GREY = (91, 98, 112)
HOME, GAME, ADMIN = "home", "game", "admin"


# 应用层连接窗口、游戏状态、棋盘视图和后台关卡任务。
class GameApp:
    def __init__(self, screen, seed=None, admin_path=None, config_path=None):
        self.screen = screen
        self.campaign = Campaign(admin_path, config_path)
        self.page = HOME
        self.current_level = None  # 首页尚未选择关卡
        self.previous_boards = {}
        self.admin_input = ""
        self.admin_message = ""
        # 选择关卡后，从五关 JSON 配置取得生成参数。
        self.config = None
        self.rng = random.Random(seed)
        self.color_rng = random.Random(seed)  # 配色不消耗关卡生成的随机数序列
        self.session = None
        self.running = True
        self.generating = False
        self.notice = self.campaign.config_error
        self.dragging = False
        self.left_press = None
        self.results = queue.SimpleQueue()
        # 队列传递后台结果；任务编号用于识别已取消的旧结果。
        self.job_id = 0
        self.cancel_event = None
        font_path = pygame.font.match_font(["microsoftyahei", "simhei", "simsun"])
        self.font = pygame.font.Font(font_path, 20)
        self.small_font = pygame.font.Font(font_path, 17)
        self.compact_font = pygame.font.Font(font_path, 14)
        # 配置缺失时只显示首页错误提示，视图使用不可游玩的占位尺寸。
        first = self.campaign.levels[0].config if self.campaign.levels else None
        rows, cols = (first.rows, first.cols) if first is not None else (1, 1)
        self.view = BoardView(self.layout_ui(rows, cols), rows, cols)
        self.layout_menu()

    def layout_ui(self, rows, cols):
        """棋盘在整窗居中；控件使用自然留白，不覆盖任何可玩格子。"""
        w, h = self.screen.get_size()

        def fitted(width, height):
            scale = min(width / cols, height / rows)
            rect = pygame.Rect(0, 0, round(cols * scale), round(rows * scale))
            rect.center = (w // 2, h // 2)
            return rect

        keys = ("new", "restart", "fit", "next", "home")
        area = fitted(w - 16, h - 16)
        # 优先用棋盘左右的自然留白放控件，空间不足时改用上下窄栏。
        if area.left >= 104:
            self.hud_mode = "sides"
            panel_width = min(180, area.left - 24)
            left_x = (area.left - panel_width) // 2
            right_x = area.right + (w - area.right - panel_width) // 2
            self.summary_rect = pygame.Rect(left_x, h // 2 - 134, panel_width, 130)
            self.health_rect = pygame.Rect(left_x, h // 2 - 6, panel_width, 54)
            self.status_rect = pygame.Rect(left_x, h // 2 + 66, panel_width, min(190, h // 2 - 86))
            first_y = h // 2 - 150
            self.buttons = {
                key: pygame.Rect(right_x, first_y + i * 54, panel_width, 42)
                for i, key in enumerate(keys)
            }
            self.help_rect = pygame.Rect(right_x, first_y + len(keys) * 54 + 10, panel_width, 110)
        else:
            # 无足够自然留白时，只预留两条窄边带，棋盘仍在窗口正中。
            if area.top < 84:
                area = fitted(w - 16, h - 168)
            self.hud_mode = "bars"
            self.summary_rect = pygame.Rect(16, area.top - 44, w // 2 - 24, 30)
            self.health_rect = pygame.Rect(w // 2 + 12, area.top - 64, w // 2 - 28, 26)
            self.help_rect = pygame.Rect(w // 2, area.top - 32, w // 2 - 16, 26)
            self.buttons = {
                key: pygame.Rect(16 + i * ((w - 32) // len(keys)), area.bottom + 8,
                                 (w - 32) // len(keys) - 8, 40)
                for i, key in enumerate(keys)
            }
            self.status_rect = pygame.Rect(16, area.bottom + 54, w - 32, 26)
        return area

    def layout_menu(self):
        w, h = self.screen.get_size()
        width = min(680, w - 64)
        left = (w - width) // 2
        button_width = (width - 12) // 2
        self.menu_buttons = {
            name: pygame.Rect(left + i * (button_width + 12), 122, button_width, 42)
            for i, name in enumerate(("admin", "reload"))
        }
        spacing = min(66, (h - 270) // LEVEL_COUNT)
        self.level_buttons = [pygame.Rect(left, 184 + i * spacing, width, spacing - 8)
                              for i in range(LEVEL_COUNT)]
        self.password_rect = pygame.Rect(w // 2 - 240, h // 2 - 26, 480, 52)
        self.admin_buttons = {
            "submit": pygame.Rect(w // 2 - 190, h // 2 + 46, 180, 42),
            "cancel": pygame.Rect(w // 2 + 10, h // 2 + 46, 180, 42),
        }
        self.failure_rect = pygame.Rect(w // 2 - 260, h // 2 - 140, 520, 280)
        self.failure_buttons = {
            "restart": pygame.Rect(w // 2 - 224, h // 2 + 50, 212, 48),
            "home": pygame.Rect(w // 2 + 12, h // 2 + 50, 212, 48),
        }

    @property
    def current_max_lives(self):
        return self.campaign.levels[self.current_level].lives

    @property
    def failure_visible(self):
        return (self.page == GAME and self.session is not None
                and self.session.mistakes_remaining == 0 and not self.generating)

    def reload_campaign(self):
        changed, message = self.campaign.reload_config()
        if changed:
            self.previous_boards.clear()
        self.notice = message + ("；继续使用上次有效配置" if self.campaign.config_error
                                and self.campaign.levels else "")

    def open_level(self, index):
        if not self.campaign.can_enter(index):
            self.notice = self.campaign.config_error or "请先通过前一关，或使用管理员入口解锁"
            return
        self.cancel_generation()
        self.cancel_pointer()
        self.current_level = index
        self.config = self.campaign.levels[index].config
        self.session = None  # 旧关卡即使已通关，也不能被记入新关卡
        self.page = GAME
        self.view.rect = self.layout_ui(self.config.rows, self.config.cols)
        self.view.set_board(self.config.rows, self.config.cols)
        self.request_new()

    def return_home(self):
        self.cancel_generation()
        self.cancel_pointer()
        self.session = None
        self.current_level = None
        self.config = None
        self.page = HOME
        self.admin_input = ""
        self.notice = "选关会生成新题；本次运行的通关进度已保留"
        pygame.key.stop_text_input()

    def open_admin(self):
        self.cancel_pointer()
        self.page = ADMIN
        self.admin_input = ""
        _, error = read_admin_password(self.campaign.admin_path)
        self.admin_message = error or "输入本地 JSON 中设置的密码"
        pygame.key.set_text_input_rect(self.password_rect)
        pygame.key.start_text_input()

    def submit_admin(self):
        success, message = self.campaign.authenticate(self.admin_input)
        self.admin_input = ""
        if success:
            self.return_home()
            self.notice = message
        else:
            self.admin_message = message
        return success

    def handle_menu_event(self, event):
        """返回 True 时，本批后续操作不再穿透到新的页面。"""
        if self.page == ADMIN:
            if event.type == pygame.TEXTINPUT:
                self.admin_input += event.text
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.return_home()
                    return True
                if event.key == pygame.K_BACKSPACE:
                    self.admin_input = self.admin_input[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return self.submit_admin()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.admin_buttons["cancel"].collidepoint(event.pos):
                    self.return_home()
                    return True
                if self.admin_buttons["submit"].collidepoint(event.pos):
                    return self.submit_admin()
            return False
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        if self.menu_buttons["admin"].collidepoint(event.pos):
            self.open_admin()
            return True
        if self.menu_buttons["reload"].collidepoint(event.pos):
            self.reload_campaign()
            return True
        for index, rect in enumerate(self.level_buttons):
            if rect.collidepoint(event.pos):
                self.open_level(index)
                return self.page == GAME
        return False

    def can_advance(self):
        return (self.current_level is not None and not self.generating
                and self.session is not None and not self.failure_visible
                and (self.campaign.admin_unlocked or self.current_level in self.campaign.completed
                     or self.session.state == WON)
                and (self.current_level + 1 < LEVEL_COUNT
                     or self.campaign.all_completed))

    def install(self, board):
        # 新题统一加载布局、全景和配色，同时清理未结束的鼠标手势。
        if self.session is None:
            self.session = GameSession(board, self.current_max_lives)
        else:
            self.session.max_lives = self.current_max_lives
            self.session.load(board)
        self.view.rect = self.layout_ui(board.rows, board.cols)
        self.view.set_board(board.rows, board.cols)
        self.view.assign_colors(board, self.color_rng)
        if self.current_level is not None:
            self.previous_boards[self.current_level] = board.copy()
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
        # 生成期间保留当前布局，只暂停棋盘操作。
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
        previous = (self.session.initial.copy() if self.session is not None
                    else self.previous_boards.get(self.current_level))
        config = self.config  # 固定任务参数，切换关卡不能改变已启动线程的配置
        # 每个任务拥有独立 RNG，旧任务取消后不会与新任务争用随机数状态。
        rng = random.Random(self.rng.getrandbits(64))

        def work():
            # 后台只做数据计算，通过线程安全队列返回，不操作 Pygame 窗口。
            try:
                # 时间预算与取消检查统一由生成器负责。
                board = generate_level(config, previous=previous, rng=rng, cancel_event=cancel)
                self.results.put((token, board, None))
            except Exception as exc:
                self.results.put((token, None, str(exc)))

        # 启动后台任务后立刻返回，主循环继续处理关闭、缩放与绘制。
        threading.Thread(target=work, daemon=True).start()

    def restart(self):
        # 恢复同一道题，不重置视图和颜色，也不消耗关卡随机数。
        self.cancel_generation()
        if self.session is not None:
            self.session.restart()
        self.notice = ""
        self.cancel_pointer()

    def update(self, dt):
        # 主线程领取结果；旧任务即使晚到，也不能覆盖重开或新题
        while True:
            try:
                token, board, error = self.results.get_nowait()
            except queue.Empty:
                break
            if token != self.job_id:
                continue
            self.generating = False
            if error is not None:
                self.notice = "生成失败：" + error
            else:
                self.install(board)
        if self.page == GAME and self.session is not None and not self.generating:
            self.session.update(dt)
            if self.failure_visible:
                self.cancel_pointer()
            if self.current_level is not None and self.session.state == WON:
                self.campaign.record_win(self.current_level)

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
                self.layout_menu()
                if self.page == ADMIN:
                    pygame.key.set_text_input_rect(self.password_rect)
                continue
            if suppress_clicks:
                continue
            if self.page != GAME:
                suppress_clicks = self.handle_menu_event(event)
                continue
            if self.failure_visible:
                # 失败弹窗独占输入，点击不能穿透到棋盘或其他按钮。
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.failure_buttons["restart"].collidepoint(event.pos):
                        self.restart()
                        suppress_clicks = True
                    elif self.failure_buttons["home"].collidepoint(event.pos):
                        self.return_home()
                        suppress_clicks = True
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self.restart()
                        suppress_clicks = True
                    elif event.key == pygame.K_ESCAPE:
                        self.return_home()
                        suppress_clicks = True
                continue
            if event.type == pygame.MOUSEWHEEL:
                # 普通滚轮缩放，Shift 加滚轮或横向滚轮负责左右平移。
                pos = pygame.mouse.get_pos()
                if not self.view.rect.collidepoint(pos):
                    continue
                self.left_press = None
                dx = getattr(event, "precise_x", getattr(event, "x", 0))
                dy = getattr(event, "precise_y", getattr(event, "y", 0))
                mods = pygame.key.get_mods()
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
                if self.buttons["home"].collidepoint(event.pos):
                    self.return_home()
                    suppress_clicks = True
                elif "next" in self.buttons and self.buttons["next"].collidepoint(event.pos):
                    if self.can_advance():
                        self.open_level(0 if self.current_level == LEVEL_COUNT - 1
                                        else self.current_level + 1)
                        suppress_clicks = True
                elif self.buttons["fit"].collidepoint(event.pos):
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

    def draw_button(self, rect, label, enabled=True):
        pygame.draw.rect(self.screen, BUTTON if enabled else (39, 43, 52), rect, border_radius=8)
        pygame.draw.rect(self.screen, (82, 133, 126) if enabled else GRID_DISABLED,
                         rect, width=1, border_radius=8)
        self.draw_fitted(label, rect.inflate(-12, -8), TEXT if enabled else MUTED, centered=True)

    def draw_health(self):
        total = self.session.max_lives if self.session is not None else self.current_max_lives
        remaining = self.session.mistakes_remaining if self.session is not None else total
        rect = self.health_rect.copy()
        if self.hud_mode == "sides":
            self.draw_fitted(f"生命值 {remaining}/{total}", pygame.Rect(rect.x, rect.y, rect.w, 20))
            rect.y += 24
            rect.height -= 24
        else:
            self.draw_fitted(f"生命值 {remaining}/{total}", pygame.Rect(rect.x, rect.y, 100, rect.h))
            rect.x += 108
            rect.width -= 108
        # 自绘心形，不依赖系统字体是否包含爱心字符。
        size = 22
        while size > 5:
            columns = max(1, rect.width // (size + 4))
            if math.ceil(total / columns) * (size + 4) <= rect.height:
                break
            size -= 1
        columns = max(1, rect.width // (size + 4))
        for i in range(total):
            x = rect.x + (i % columns) * (size + 4)
            y = rect.y + (i // columns) * (size + 4)
            points = []
            for step in range(48):
                angle = step * math.tau / 48
                px = 16 * math.sin(angle) ** 3
                py = (13 * math.cos(angle) - 5 * math.cos(2 * angle)
                      - 2 * math.cos(3 * angle) - math.cos(4 * angle))
                points.append((round(x + (px + 16) / 32 * size),
                               round(y + (12 - py) / 29 * size)))
            pygame.draw.polygon(self.screen, HEART_RED if i < remaining else HEART_GREY, points)

    def draw_failure(self):
        shade = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 175))
        self.screen.blit(shade, (0, 0))
        rect = self.failure_rect
        pygame.draw.rect(self.screen, (35, 43, 57), rect, border_radius=18)
        pygame.draw.rect(self.screen, HEART_RED, rect, width=2, border_radius=18)
        self.draw_fitted("生命值已耗尽", pygame.Rect(rect.x + 24, rect.y + 30, rect.w - 48, 34),
                         HEART_RED, centered=True)
        self.draw_fitted("重新开始本题，或回到主页选择关卡",
                         pygame.Rect(rect.x + 24, rect.y + 82, rect.w - 48, 30), centered=True)
        self.draw_fitted("Enter 重新开始 · Esc 返回主页",
                         pygame.Rect(rect.x + 24, rect.y + 125, rect.w - 48, 26), MUTED, centered=True)
        self.draw_button(self.failure_buttons["restart"], "重新开始")
        self.draw_button(self.failure_buttons["home"], "回到主页选关")

    def draw_menu(self):
        w, h = self.screen.get_size()
        if self.page == ADMIN:
            self.draw_fitted("管理员解锁", pygame.Rect(32, 40, w - 64, 44), centered=True)
            self.draw_fitted("密码读取 config/admin.json · 解锁仅本次运行有效",
                             pygame.Rect(32, 94, w - 64, 32), MUTED, centered=True)
            pygame.draw.rect(self.screen, BUTTON, self.password_rect, border_radius=8)
            pygame.draw.rect(self.screen, ARROW_COLOR, self.password_rect, width=1, border_radius=8)
            available = self.password_rect.width - 24
            stars = "*" * min(len(self.admin_input), available // max(1, self.font.size("*")[0]))
            self.draw_fitted(stars or "请输入密码", self.password_rect.inflate(-24, -16), TEXT)
            self.draw_fitted(self.admin_message,
                             pygame.Rect(24, self.password_rect.top - 42, w - 48, 30), MUTED, centered=True)
            self.draw_button(self.admin_buttons["submit"], "验证并解锁")
            self.draw_button(self.admin_buttons["cancel"], "返回首页")
            self.draw_fitted("Enter 提交 · Backspace 删除 · Esc 返回",
                             pygame.Rect(24, self.password_rect.bottom + 90, w - 48, 30), MUTED, centered=True)
            return
        self.draw_fitted("一箭又一箭 · 五关挑战", pygame.Rect(32, 32, w - 64, 40), centered=True)
        self.draw_fitted("点击箭头头部 · 沿路径抽出 · 碰撞原路返回 · 滚轮缩放与拖动",
                         pygame.Rect(24, 78, w - 48, 30), MUTED, centered=True)
        for name, label in (("admin", "管理员入口"), ("reload", "重载配置")):
            self.draw_button(self.menu_buttons[name], label)
        for i, rect in enumerate(self.level_buttons):
            if i >= len(self.campaign.levels):
                self.draw_button(rect, f"第 {i + 1} 关 · 请修正 config/campaign.json 后重载配置", False)
                continue
            level = self.campaign.levels[i]
            config = level.config
            state = "已通关" if i in self.campaign.completed else "可挑战" if self.campaign.can_enter(i) else "未解锁"
            label = f"第 {i + 1} 关 · {level.name} · {config.rows}×{config.cols} · {config.arrow_count} 支 · {level.lives} 生命 · {state}"
            self.draw_button(rect, label, self.campaign.can_enter(i))
        self.draw_fitted("管理员已解锁全部关卡" if self.campaign.admin_unlocked else "普通模式：通关后解锁下一关",
                         pygame.Rect(24, h - 80, w - 48, 26), ARROW_COLOR, centered=True)
        self.draw_fitted(self.notice or "点击关卡直接挑战；关闭游戏后进度与管理员权限重置",
                         pygame.Rect(24, h - 44, w - 48, 26), MUTED, centered=True)

    def draw(self):
        # 先画棋盘，再在独立区域显示状态、简短说明和当前模式的按钮。
        screen = self.screen
        screen.fill(BACKGROUND)
        if self.page != GAME:
            self.draw_menu()
            return
        pygame.draw.rect(screen, (36, 43, 56), self.view.rect)
        if self.session is not None:
            self.view.draw(screen, self.session)
        else:
            message = "正在准备棋盘…" if self.generating else "请点击换一题重试"
            self.draw_fitted(message, self.view.rect, MUTED, centered=True)

        title, color = "一箭又一箭", TEXT
        remaining = len(self.session.board.arrows) if self.session is not None else "—"
        status = self.notice
        if self.session is not None:
            if self.session.state == FAILED:
                title, color = "本关失败", ERROR_COLOR
                status = status or "点击重新开始再试一次"
            elif self.session.state == WON:
                title, color = "本关通关", ARROW_COLOR
                if self.campaign.all_completed:
                    title, status = "全部五关通关", status or "重新挑战或返回首页"
                elif self.current_level == LEVEL_COUNT - 1:
                    status = status or "本关已完成，其他关卡尚未全部通关，请返回首页继续挑战"
                else:
                    status = status or "点击下一关继续挑战"
            elif self.session.motion is not None and self.session.motion.collided:
                status = status or "碰撞后原路返回"
        if not self.view.can_click:
            status = status or "请滚轮放大后点击头部格"

        rect = self.summary_rect
        level_label = f"第 {self.current_level + 1} / {LEVEL_COUNT} 关"
        if self.hud_mode == "sides":
            self.draw_fitted(title, pygame.Rect(rect.x, rect.y, rect.width, 26), color)
            self.draw_fitted(level_label, pygame.Rect(rect.x, rect.y + 34, rect.width, 26), MUTED)
            self.draw_fitted(f"箭头 {remaining}", pygame.Rect(rect.x, rect.y + 68, rect.width, 26))
            self.draw_wrapped("点击头部格\n滚轮缩放\n左键拖动\n← → 平移", self.help_rect)
        else:
            self.draw_fitted(f"{level_label} · {title} · 剩余 {remaining}", rect, color)
            self.draw_fitted("点击头部 · 滚轮缩放 · 拖动/←→平移", self.help_rect, MUTED)
        self.draw_health()
        self.draw_wrapped(status, self.status_rect,
                          ERROR_COLOR if "失败" in status or color == ERROR_COLOR else MUTED)

        labels = {"new": "生成中…" if self.generating else "换一题",
                  "restart": "重新开始", "fit": "全景", "home": "返回首页",
                  "next": "重新挑战" if self.current_level == LEVEL_COUNT - 1
                          and self.campaign.all_completed else "下一关"}
        for key, rect in self.buttons.items():
            enabled = not ((key == "new" and (self.config is None or self.generating))
                           or (key == "restart" and self.session is None)
                           or (key == "next" and not self.can_advance()))
            self.draw_button(rect, labels[key], enabled)
        if self.failure_visible:
            self.draw_failure()

    def close(self):
        self.cancel_generation()
        self.admin_input = ""
        pygame.key.stop_text_input()
        self.running = False


GRID_DISABLED = (75, 80, 90)


def parse_args():
    parser = argparse.ArgumentParser(description="五关箭头消除游戏；关卡参数在 config/campaign.json 中设置")
    parser.add_argument("--seed", type=int, help="复现同一系列随机题")
    return parser.parse_args()


def main():
    # 初始化窗口并进入事件、状态更新、绘制的逐帧循环。
    args = parse_args()
    pygame.init()
    pygame.key.set_repeat(250, 40)
    pygame.display.set_caption("一箭又一箭")
    screen = pygame.display.set_mode((960, 640), pygame.RESIZABLE)
    app = GameApp(screen, seed=args.seed)
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
    # 直接运行才启动游戏；作为模块导入时不会弹窗。
    main()
