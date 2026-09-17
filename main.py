import pygame

from game_logic import DIRECTIONS, can_exit, count_arrows
from levels import generate_level

pygame.init()

WINDOW_WIDTH=960
WINDOW_HEIGHT=640

screen=pygame.display.set_mode(
    (WINDOW_WIDTH,WINDOW_HEIGHT)
)

pygame.display.set_caption("一箭又一箭")

BACKGROUND_COLOR=(30,35,45)

# 棋盘数据：U/D/L/R 表示方向，None 表示空格。
# 绘图函数根据这些数据，决定每个格子显示什么箭头。
INITIAL_BOARD = generate_level()

ROWS = len(INITIAL_BOARD)
COLS = len(INITIAL_BOARD[0])
CELL_SIZE = 80
BOARD_X = 280
BOARD_Y = 140
GRID_COLOR = (85, 95, 115)
ARROW_COLOR = (100, 225, 190)
SELECTED_COLOR = (255, 210, 90)
TEXT_COLOR = (235, 240, 250)
MUTED_TEXT_COLOR = (170, 180, 200)
ERROR_COLOR = (255, 120, 120)
MAX_MISTAKES = 3
FLY_SPEED = 320  # 像素/秒：改变这个值，就能调整飞出速度。
ARROW_EXTENT = 24  # 箭头中心到最外侧的保守距离，包含线条宽度。
COLLISION_DURATION = 0.25  # 碰撞变红持续的秒数，与飞出共用每帧的 dt。
PLAYING = "playing"
FAILED = "failed"
WON = "won"
BUTTON_COLOR = (55, 75, 90)

DIRECTION_NAMES = {
    "U": "上",
    "D": "下",
    "L": "左",
    "R": "右",
}

# 这个矩形表示整个棋盘在窗口中占据的区域，用于判断鼠标是否点进棋盘。
board_rect = pygame.Rect(
    BOARD_X,
    BOARD_Y,
    COLS * CELL_SIZE,
    ROWS * CELL_SIZE,
)
restart_rect = pygame.Rect(720, 480, 160, 48)
new_puzzle_rect = pygame.Rect(720, 416, 160, 48)

# 优先使用支持中文的 Windows 系统字体。
font_path = pygame.font.match_font([
    "microsoftyahei",
    "simhei",
    "simsun",
])
title_font = pygame.font.Font(font_path, 38)
info_font = pygame.font.Font(font_path, 22)

# 标题和提示不会变化，可以在进入主循环前只渲染一次。
title_surface = title_font.render("一箭又一箭", True, TEXT_COLOR)
title_rect = title_surface.get_rect(center=(WINDOW_WIDTH // 2, 50))

hint_surface = info_font.render(
    "无阻挡即可消除，点击受阻箭头消耗 1 次机会",
    True,
    MUTED_TEXT_COLOR,
)
hint_rect = hint_surface.get_rect(center=(WINDOW_WIDTH // 2, 100))

# 失败画面保留棋盘，只切换顶部的结果标题和说明。
failed_title_surface = title_font.render("本关失败", True, ERROR_COLOR)
failed_title_rect = failed_title_surface.get_rect(center=(WINDOW_WIDTH // 2, 50))
failed_hint_surface = info_font.render(
    "失误机会已用尽，点击右侧按钮重新开始", True, MUTED_TEXT_COLOR,
)
failed_hint_rect = failed_hint_surface.get_rect(center=(WINDOW_WIDTH // 2, 100))
restart_surface = info_font.render("重新开始", True, TEXT_COLOR)
restart_text_rect = restart_surface.get_rect(center=restart_rect.center)
new_puzzle_surface = info_font.render("换一题", True, TEXT_COLOR)
new_puzzle_text_rect = new_puzzle_surface.get_rect(center=new_puzzle_rect.center)
won_title_surface = title_font.render("本题通关", True, ARROW_COLOR)
won_title_rect = won_title_surface.get_rect(center=(WINDOW_WIDTH // 2, 50))
won_hint_surface = info_font.render(
    "所有箭头已清空！点击换一题继续挑战", True, MUTED_TEXT_COLOR,
)
won_hint_rect = won_hint_surface.get_rect(center=(WINDOW_WIDTH // 2, 100))


def draw_grid(surface):
    """根据行列数，在指定画布上绘制网格。"""
    for row in range(ROWS):
        for col in range(COLS):
            # 列号决定横坐标，行号决定纵坐标。
            x = BOARD_X + col * CELL_SIZE
            y = BOARD_Y + row * CELL_SIZE

            cell_rect = pygame.Rect(x, y, CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(surface, GRID_COLOR, cell_rect, width=1)


def draw_arrow(surface, cx, cy, direction, color=ARROW_COLOR):
    """以 (cx, cy) 为中心绘制箭头；未传颜色时使用正常颜色。"""
    if direction == "R":
        start = (cx - 20, cy)
        end = (cx + 10, cy)
        points = [
            (cx + 22, cy),
            (cx + 8, cy - 12),
            (cx + 8, cy + 12),
        ]
    elif direction == "L":
        start = (cx + 20, cy)
        end = (cx - 10, cy)
        points = [
            (cx - 22, cy),
            (cx - 8, cy - 12),
            (cx - 8, cy + 12),
        ]
    elif direction == "U":
        start = (cx, cy + 20)
        end = (cx, cy - 10)
        points = [
            (cx, cy - 22),
            (cx - 12, cy - 8),
            (cx + 12, cy - 8),
        ]
    elif direction == "D":
        start = (cx, cy - 20)
        end = (cx, cy + 10)
        points = [
            (cx, cy + 22),
            (cx - 12, cy + 8),
            (cx + 12, cy + 8),
        ]
    else:
        return

    pygame.draw.line(surface, color, start, end, width=5)
    pygame.draw.polygon(surface, color, points)


def draw_arrows(surface, flying_arrow, collision_cell):
    """遍历棋盘，跳过空格，在每个有方向的格子中心绘制箭头。"""
    for row in range(ROWS):
        for col in range(COLS):
            direction = board[row][col]
            if direction is None:
                continue

            # 动画结束前，棋盘仍保留原箭头；绘图时跳过它，避免画出两个。
            if flying_arrow is not None:
                if (row, col) == (flying_arrow["row"], flying_arrow["col"]):
                    continue

            # 格子左上角加上半个格子的边长，就是格子中心。
            cx = BOARD_X + col * CELL_SIZE + CELL_SIZE // 2
            cy = BOARD_Y + row * CELL_SIZE + CELL_SIZE // 2
            # 颜色属于显示反馈，不改变棋盘中的方向或路径判断。
            color = ERROR_COLOR if (row, col) == collision_cell else ARROW_COLOR
            draw_arrow(surface, cx, cy, direction, color)


def update_flying_arrow(arrow, dt):
    """更新显示坐标；整个箭头离开棋盘时返回 True，不修改棋盘。"""
    dr, dc = DIRECTIONS[arrow["direction"]]
    # dc 对应横向 x，dr 对应纵向 y；dt 的单位是秒。
    arrow["x"] += dc * FLY_SPEED * dt
    arrow["y"] += dr * FLY_SPEED * dt

    # 中心越界还不够，要等尾部也离开，避免箭头突然消失。
    if dc == 1:
        return arrow["x"] - ARROW_EXTENT >= board_rect.right
    if dc == -1:
        return arrow["x"] + ARROW_EXTENT <= board_rect.left
    if dr == 1:
        return arrow["y"] - ARROW_EXTENT >= board_rect.bottom
    return arrow["y"] + ARROW_EXTENT <= board_rect.top


def draw_selection(surface, selected):
    """如果有箭头被选中，就在对应格子内绘制黄色边框。"""
    if selected is None:
        return

    row, col = selected
    selected_rect = pygame.Rect(
        BOARD_X + col * CELL_SIZE,
        BOARD_Y + row * CELL_SIZE,
        CELL_SIZE,
        CELL_SIZE,
    )
    pygame.draw.rect(surface, SELECTED_COLOR, selected_rect, width=4)


def reset_game():
    """启动和重开共用：复制初始棋盘，恢复数据并清空临时反馈。"""
    global board, game_state, selected_cell, mistakes_remaining, status_text
    global flying_arrow, collision_cell, collision_remaining

    # 不仅复制外层列表，还要复制每一行，防止消除时改坏初始布局。
    board = [row[:] for row in INITIAL_BOARD]
    game_state = PLAYING
    selected_cell = None
    mistakes_remaining = MAX_MISTAKES
    status_text = "点击一个箭头，检查它能否离开棋盘"
    flying_arrow = None
    collision_cell = None
    collision_remaining = 0.0


clock=pygame.time.Clock()
running=True  # 只负责窗口是否继续运行，重开不会重新进入一个主循环。
reset_game()

while running:
    # tick 每帧调用一次：限制帧率，并将经过的毫秒转换成秒。
    dt = clock.tick(60) / 1000
    restarted_this_frame = False
    # 先消耗上一帧到现在的时间，再处理新点击，保证新反馈从完整时长开始。
    # 即使机会耗尽，也继续更新视觉反馈，不把计时放进点击事件中。
    if collision_cell is not None:
        collision_remaining = max(0.0, collision_remaining - dt)
        if collision_remaining == 0:
            collision_cell = None
    for event in pygame.event.get():
        if event.type==pygame.QUIT:
            running=False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not running:
                continue

            # 重开优先于棋盘限制：失败后和飞出期间也可以点击按钮。
            if restart_rect.collidepoint(event.pos):
                reset_game()
                restarted_this_frame = True
                continue

            if new_puzzle_rect.collidepoint(event.pos):
                INITIAL_BOARD = generate_level(previous=INITIAL_BOARD)
                reset_game()
                restarted_this_frame = True
                continue

            # 状态统一决定是否允许操作棋盘；关闭窗口事件不受此限制。
            # 重开这一帧的后续棋盘点击也跳过，避免排队的旧点击影响新一局。
            if restarted_this_frame or game_state != PLAYING or flying_arrow is not None:
                continue

            if board_rect.collidepoint(event.pos):
                mouse_x, mouse_y = event.pos
                col = (mouse_x - BOARD_X) // CELL_SIZE
                row = (mouse_y - BOARD_Y) // CELL_SIZE

                if board[row][col] is not None:
                    # 在消除前保存方向，用于显示本次操作的结果。
                    direction_name = DIRECTION_NAMES[board[row][col]]
                    if can_exit(board, row, col):
                        # 先播放动画，结束后才清空格子。显示位置使用像素坐标。
                        flying_arrow = {
                            "row": row,
                            "col": col,
                            "direction": board[row][col],
                            "x": BOARD_X + col * CELL_SIZE + CELL_SIZE / 2,
                            "y": BOARD_Y + row * CELL_SIZE + CELL_SIZE / 2,
                        }
                        selected_cell = None
                        status_text = (
                            f"正在飞出：第 {row + 1} 行，第 {col + 1} 列，"
                            f"方向：{direction_name}"
                        )
                    else:
                        selected_cell = (row, col)
                        # 再次受阻就记录最新格子，并重新开始 0.25 秒倒计时。
                        collision_cell = (row, col)
                        collision_remaining = COLLISION_DURATION
                        # 只在本次左键点击确实被阻挡时扣一次。
                        mistakes_remaining -= 1
                        if mistakes_remaining == 0:
                            # 次数是数据；归零这个事件让游戏从进行中进入失败。
                            game_state = FAILED
                            status_text = "失误次数已耗尽，本关失败"
                        else:
                            status_text = (
                                f"第 {row + 1} 行，第 {col + 1} 列："
                                "前方有阻挡，失误机会减 1"
                            )
                    print(status_text)
                else:
                    selected_cell = None
                    status_text = "这里是空格，请点击箭头"
            else:
                selected_cell = None
                status_text = "请点击棋盘内的箭头"

    # 每一帧都会执行更新，即使这一帧没有鼠标事件，箭头也会继续移动。
    if running and game_state == PLAYING and flying_arrow is not None:
        if update_flying_arrow(flying_arrow, dt):
            row, col = flying_arrow["row"], flying_arrow["col"]
            direction_name = DIRECTION_NAMES[flying_arrow["direction"]]
            board[row][col] = None
            flying_arrow = None
            status_text = (
                f"已消除：第 {row + 1} 行，第 {col + 1} 列，"
                f"方向：{direction_name}"
            )
            if count_arrows(board) == 0:
                game_state = WON
                selected_cell = None
                collision_cell = None
                collision_remaining = 0.0
                status_text = "本题通关！可以换一题，或重新开始练习本题"

    screen.fill(BACKGROUND_COLOR)
    if game_state == FAILED:
        screen.blit(failed_title_surface, failed_title_rect)
        screen.blit(failed_hint_surface, failed_hint_rect)
    elif game_state == WON:
        screen.blit(won_title_surface, won_title_rect)
        screen.blit(won_hint_surface, won_hint_rect)
    else:
        screen.blit(title_surface, title_rect)
        screen.blit(hint_surface, hint_rect)
    draw_grid(screen)
    draw_arrows(screen, flying_arrow, collision_cell)
    if flying_arrow is not None:
        # 只显示仍在棋盘内的部分，飞出的箭头不会盖住标题或状态栏。
        screen.set_clip(board_rect)
        draw_arrow(
            screen, flying_arrow["x"], flying_arrow["y"],
            flying_arrow["direction"],
        )
        screen.set_clip(None)
    draw_selection(screen, selected_cell)
    pygame.draw.rect(screen, BUTTON_COLOR, restart_rect, border_radius=8)
    pygame.draw.rect(screen, ARROW_COLOR, restart_rect, width=2, border_radius=8)
    screen.blit(restart_surface, restart_text_rect)
    pygame.draw.rect(screen, BUTTON_COLOR, new_puzzle_rect, border_radius=8)
    pygame.draw.rect(screen, ARROW_COLOR, new_puzzle_rect, width=2, border_radius=8)
    screen.blit(new_puzzle_surface, new_puzzle_text_rect)

    # 直接根据当前棋盘统计，避免单独维护数量时漏减或重复扣减。
    remaining_arrows = count_arrows(board)
    count_surface = info_font.render(
        f"剩余箭头：{remaining_arrows}    剩余失误次数：{mistakes_remaining}",
        True,
        TEXT_COLOR,
    )
    count_rect = count_surface.get_rect(center=(WINDOW_WIDTH // 2, 565))
    screen.blit(count_surface, count_rect)

    # 状态文字会随选择变化，因此需要在主循环中重新渲染。
    status_color = ERROR_COLOR if game_state == FAILED else TEXT_COLOR
    status_surface = info_font.render(status_text, True, status_color)
    status_rect = status_surface.get_rect(
        center=(WINDOW_WIDTH // 2, 605)
    )
    screen.blit(status_surface, status_rect)
    pygame.display.flip()

pygame.quit()
