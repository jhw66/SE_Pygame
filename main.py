import pygame
from game_logic import DIRECTIONS, can_exit, count_arrows
from levels import generate_level

# pygame各模块初始化
pygame.init()

# 基础窗口设置
WINDOW_WIDTH=960
WINDOW_HEIGHT=640
screen=pygame.display.set_mode((WINDOW_WIDTH,WINDOW_HEIGHT))
pygame.display.set_caption("一箭又一箭")
# 窗口背景
BACKGROUND_COLOR=(30,35,45)
# 生成随机可解棋盘
INITIAL_BOARD = generate_level()
# 棋盘单格大小与格数
ROWS = len(INITIAL_BOARD)
COLS = len(INITIAL_BOARD[0])
CELL_SIZE = 80
# 棋盘位置
BOARD_X = 280
BOARD_Y = 140
# 棋盘内格、箭头箭体、选择箭头、文字、按钮颜色设置
GRID_COLOR = (85, 95, 115)
ARROW_COLOR = (100, 225, 190)
SELECTED_COLOR = (255, 210, 90)
TEXT_COLOR = (235, 240, 250)
MUTED_TEXT_COLOR = (170, 180, 200)
ERROR_COLOR = (255, 120, 120)
BUTTON_COLOR = (55, 75, 90)
# 最大失败次数
MAX_MISTAKES = 3
# 飞行相关参数
FLY_SPEED = 320  # 像素/秒：改变这个值，就能调整飞出速度
ARROW_EXTENT = 24  # 箭头中心到最外侧的保守距离，包含线条宽度
COLLISION_DURATION = 0.25  # 碰撞变红持续的秒数，与飞出共用每帧的 dt
# 游戏状态
PLAYING = "playing"
FAILED = "failed"
WON = "won"
# 箭头方向名字
DIRECTION_NAMES = {
    "U": "上",
    "D": "下",
    "L": "左",
    "R": "右",
}

# 可点击棋盘大小与位置设置
board_rect = pygame.Rect(BOARD_X,BOARD_Y,COLS * CELL_SIZE,ROWS * CELL_SIZE)

# 字体设置
font_path = pygame.font.match_font(["microsoftyahei","simhei","simsun"])
title_font = pygame.font.Font(font_path, 38) # 标题字体
info_font = pygame.font.Font(font_path, 22)  # 提示字体

# 游玩画面
title_surface = title_font.render("一箭又一箭", True, TEXT_COLOR)
title_rect = title_surface.get_rect(center=(WINDOW_WIDTH // 2, 50))
hint_surface = info_font.render("无阻挡即可消除，点击受阻箭头消耗 1 次机会",True,MUTED_TEXT_COLOR)
hint_rect = hint_surface.get_rect(center=(WINDOW_WIDTH // 2, 100))
# 失败画面
failed_title_surface = title_font.render("本关失败", True, ERROR_COLOR)
failed_title_rect = failed_title_surface.get_rect(center=(WINDOW_WIDTH // 2, 50))
failed_hint_surface = info_font.render("失误机会已用尽，点击右侧按钮重新开始", True, MUTED_TEXT_COLOR)
failed_hint_rect = failed_hint_surface.get_rect(center=(WINDOW_WIDTH // 2, 100))
# 通关画面
won_title_surface = title_font.render("本题通关", True, ARROW_COLOR)
won_title_rect = won_title_surface.get_rect(center=(WINDOW_WIDTH // 2, 50))
won_hint_surface = info_font.render("所有箭头已清空！点击换一题继续挑战", True, MUTED_TEXT_COLOR,)
won_hint_rect = won_hint_surface.get_rect(center=(WINDOW_WIDTH // 2, 100))
# 重新开始按钮
restart_rect = pygame.Rect(720, 480, 160, 48)
restart_surface = info_font.render("重新开始", True, TEXT_COLOR)
restart_text_rect = restart_surface.get_rect(center=restart_rect.center)
# 换题按钮
new_puzzle_rect = pygame.Rect(720, 416, 160, 48)
new_puzzle_surface = info_font.render("换一题", True, TEXT_COLOR)
new_puzzle_text_rect = new_puzzle_surface.get_rect(center=new_puzzle_rect.center)


# 绘制棋盘内格逻辑
def draw_grid(surface):
    for row in range(ROWS):
        for col in range(COLS):
            # 列号决定横坐标，行号决定纵坐标。
            x = BOARD_X + col * CELL_SIZE
            y = BOARD_Y + row * CELL_SIZE

            cell_rect = pygame.Rect(x, y, CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(surface, GRID_COLOR, cell_rect, width=1)

# 绘制箭头(直线＋箭头)逻辑
def draw_arrow(surface, cx, cy, direction, color=ARROW_COLOR):
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

# 在棋盘上绘制箭头逻辑
def draw_arrows(surface, flying_arrow, collision_cell):
    for row in range(ROWS):
        for col in range(COLS):
            direction = board[row][col]
            if direction is None:
                continue

            # 动画结束前，棋盘仍保留原箭头；绘图时跳过它，避免画出两个
            if flying_arrow is not None:
                if (row, col) == (flying_arrow["row"], flying_arrow["col"]):
                    continue

            # 格子左上角加上半个格子的边长，才是格子中心。
            cx = BOARD_X + col * CELL_SIZE + CELL_SIZE // 2
            cy = BOARD_Y + row * CELL_SIZE + CELL_SIZE // 2

            # 设置箭头颜色（根据是否为选择错误的箭头）
            color = ERROR_COLOR if (row, col) == collision_cell else ARROW_COLOR
            draw_arrow(surface, cx, cy, direction, color)

# 箭头飞行逻辑
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

# 箭头被选择绘制逻辑（不论是否可以飞出）
def draw_selection(surface, selected):
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

# 重新开始逻辑
def reset_game():
    # 全局变量绑定
    global board, game_state, mistakes_remaining, status_text, flying_arrow
    global collision_cell, collision_remaining, selected_cell, selected_remaining

    # 不仅复制外层列表，还要复制每一行，防止消除时改坏初始布局
    board = [row[:] for row in INITIAL_BOARD]
    # 重开游戏状态、失误次数、状态文字、飞行状态、碰撞状态、选中状态
    game_state = PLAYING
    mistakes_remaining = MAX_MISTAKES
    status_text = "点击一个箭头，检查它能否离开棋盘"
    flying_arrow = None
    collision_cell = None
    collision_remaining = 0.0
    selected_cell = None
    selected_remaining = 0.0


clock=pygame.time.Clock()
running=True  
reset_game()
while running:
    # tick 每帧调用一次：限制帧率，并将经过的毫秒转换成秒
    dt = clock.tick(60) / 1000
    restarted_this_frame = False

    # 选错箭头颜色变化持续事件
    if collision_cell is not None:
        collision_remaining = max(0.0, collision_remaining - dt)
        if collision_remaining == 0:
            collision_cell = None
    # 选择箭头颜色变化持续事件
    if selected_cell is not None:
        selected_remaining = max(0.0, selected_remaining - dt)
        if selected_remaining == 0:
            selected_cell = None

    for event in pygame.event.get():
        if event.type==pygame.QUIT:
            running=False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not running:
                continue

            # 触发重开事件
            if restart_rect.collidepoint(event.pos):
                reset_game()
                restarted_this_frame = True
                continue

            # 触发换题事件
            if new_puzzle_rect.collidepoint(event.pos):
                INITIAL_BOARD = generate_level(previous=INITIAL_BOARD)
                reset_game()
                restarted_this_frame = True
                continue

            # 游戏重开、成功、失败、箭头飞行期间不进行棋盘内点击事件
            if restarted_this_frame or game_state != PLAYING or flying_arrow is not None:
                continue

            # 触发棋盘内点击事件
            if board_rect.collidepoint(event.pos):
                mouse_x, mouse_y = event.pos
                col = (mouse_x - BOARD_X) // CELL_SIZE
                row = (mouse_y - BOARD_Y) // CELL_SIZE

                # 点击的是箭头
                if board[row][col] is not None:
                    direction_name = DIRECTION_NAMES[board[row][col]]
                    # 点击箭头可以飞出
                    if can_exit(board, row, col):
                        flying_arrow = {
                            "row": row,
                            "col": col,
                            "direction": board[row][col],
                            "x": BOARD_X + col * CELL_SIZE + CELL_SIZE / 2,
                            "y": BOARD_Y + row * CELL_SIZE + CELL_SIZE / 2,
                        }
                        selected_cell = (row, col)
                        selected_remaining = COLLISION_DURATION
                        status_text = (
                            f"正在飞出：第 {row + 1} 行，第 {col + 1} 列，"
                            f"方向：{direction_name}"
                        )
                    # 点击箭头不可飞出
                    else:
                        selected_cell = (row, col)
                        selected_remaining = COLLISION_DURATION
                        collision_cell = (row, col)
                        collision_remaining = COLLISION_DURATION
                        mistakes_remaining -= 1
                        if mistakes_remaining == 0:
                            game_state = FAILED
                            status_text = "失误次数已耗尽，本关失败"
                        else:
                            status_text = (
                                f"第 {row + 1} 行，第 {col + 1} 列："
                                "前方有阻挡，失误机会减 1"
                            )
                    print(status_text)
                # 点击的是空格
                else:
                    selected_cell = None
                    status_text = "这里是空格，请点击箭头"
            # 点击的是棋盘外且非重开换题
            else:
                selected_cell = None
                status_text = "请点击棋盘内的箭头"

    # 当游戏可以继续运行并且有飞行箭头时
    if running and game_state == PLAYING and flying_arrow is not None:
        if update_flying_arrow(flying_arrow, dt):
            # 完全飞出去以后的处理
            row, col = flying_arrow["row"], flying_arrow["col"]
            direction_name = DIRECTION_NAMES[flying_arrow["direction"]]
            board[row][col] = None
            flying_arrow = None
            status_text = (
                f"已消除：第 {row + 1} 行，第 {col + 1} 列，"
                f"方向：{direction_name}"
            )
            # 完全飞出之后成功处理
            if count_arrows(board) == 0:
                game_state = WON
                selected_cell = None
                selected_remaining = 0.0
                collision_cell = None
                collision_remaining = 0.0
                status_text = "本题通关！可以换一题，或重新开始练习本题"

    # 画面整体颜色
    screen.fill(BACKGROUND_COLOR)

    # 游戏失败画面
    if game_state == FAILED:
        screen.blit(failed_title_surface, failed_title_rect)
        screen.blit(failed_hint_surface, failed_hint_rect)
    # 游戏成功画面
    elif game_state == WON:
        screen.blit(won_title_surface, won_title_rect)
        screen.blit(won_hint_surface, won_hint_rect)
    # 游戏游玩画面
    else:
        screen.blit(title_surface, title_rect)
        screen.blit(hint_surface, hint_rect)

    # 绘制棋盘内格
    draw_grid(screen)

    # 绘制箭头
    draw_arrows(screen, flying_arrow, collision_cell)

    # 绘制飞行箭头
    if flying_arrow is not None:
        screen.set_clip(board_rect)
        draw_arrow(screen, flying_arrow["x"], flying_arrow["y"],flying_arrow["direction"])
        screen.set_clip(None)

    # 绘制箭头选择
    draw_selection(screen, selected_cell)

    # 重开按钮
    pygame.draw.rect(screen, BUTTON_COLOR, restart_rect, border_radius=8)
    pygame.draw.rect(screen, ARROW_COLOR, restart_rect, width=2, border_radius=8)
    screen.blit(restart_surface, restart_text_rect)

    # 换题按钮
    pygame.draw.rect(screen, BUTTON_COLOR, new_puzzle_rect, border_radius=8)
    pygame.draw.rect(screen, ARROW_COLOR, new_puzzle_rect, width=2, border_radius=8)
    screen.blit(new_puzzle_surface, new_puzzle_text_rect)

    # 剩余箭头与机会提示
    remaining_arrows = count_arrows(board)
    count_surface = info_font.render(
        f"剩余箭头：{remaining_arrows}    剩余失误次数：{mistakes_remaining}",
        True,
        TEXT_COLOR,
    )
    count_rect = count_surface.get_rect(center=(WINDOW_WIDTH // 2, 565))
    screen.blit(count_surface, count_rect)

    # 状态文字提示
    status_color = ERROR_COLOR if game_state == FAILED else TEXT_COLOR
    status_surface = info_font.render(status_text, True, status_color)
    status_rect = status_surface.get_rect(center=(WINDOW_WIDTH // 2, 605))
    screen.blit(status_surface, status_rect)

    # 刷新显示
    pygame.display.flip()

pygame.quit()
