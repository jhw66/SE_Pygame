import pygame

from game_logic import can_exit, count_arrows

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
board = [
    ["U", None, "R", None, "D"],
    [None, "L", None, "D", None],
    ["R", None, "U", None, "L"],
    [None, "D", None, "R", None],
    ["L", None, "U", None, "R"],
]

ROWS = len(board)
COLS = len(board[0])
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


def draw_grid(surface):
    """根据行列数，在指定画布上绘制网格。"""
    for row in range(ROWS):
        for col in range(COLS):
            # 列号决定横坐标，行号决定纵坐标。
            x = BOARD_X + col * CELL_SIZE
            y = BOARD_Y + row * CELL_SIZE

            cell_rect = pygame.Rect(x, y, CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(surface, GRID_COLOR, cell_rect, width=1)


def draw_arrow(surface, cx, cy, direction):
    """以 (cx, cy) 为中心，用线段和三角形绘制一个箭头。"""
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

    pygame.draw.line(surface, ARROW_COLOR, start, end, width=5)
    pygame.draw.polygon(surface, ARROW_COLOR, points)


def draw_arrows(surface):
    """遍历棋盘，跳过空格，在每个有方向的格子中心绘制箭头。"""
    for row in range(ROWS):
        for col in range(COLS):
            direction = board[row][col]
            if direction is None:
                continue

            # 格子左上角加上半个格子的边长，就是格子中心。
            cx = BOARD_X + col * CELL_SIZE + CELL_SIZE // 2
            cy = BOARD_Y + row * CELL_SIZE + CELL_SIZE // 2
            draw_arrow(surface, cx, cy, direction)


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


clock=pygame.time.Clock()

running=True
selected_cell = None
mistakes_remaining = MAX_MISTAKES
status_text = "点击一个箭头，检查它能否离开棋盘"

while running:
    for event in pygame.event.get():
        if event.type==pygame.QUIT:
            running=False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # 次数耗尽后只跳过点击处理，窗口仍然绘制并响应关闭事件。
            if mistakes_remaining <= 0:
                continue

            if board_rect.collidepoint(event.pos):
                mouse_x, mouse_y = event.pos
                col = (mouse_x - BOARD_X) // CELL_SIZE
                row = (mouse_y - BOARD_Y) // CELL_SIZE

                if board[row][col] is not None:
                    # 在消除前保存方向，用于显示本次操作的结果。
                    direction_name = DIRECTION_NAMES[board[row][col]]
                    if can_exit(board, row, col):
                        board[row][col] = None
                        selected_cell = None
                        status_text = (
                            f"已消除：第 {row + 1} 行，第 {col + 1} 列，"
                            f"方向：{direction_name}"
                        )
                    else:
                        selected_cell = (row, col)
                        # 只在本次左键点击确实被阻挡时扣一次。
                        mistakes_remaining -= 1
                        if mistakes_remaining == 0:
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
    screen.fill(BACKGROUND_COLOR)
    screen.blit(title_surface, title_rect)
    screen.blit(hint_surface, hint_rect)
    draw_grid(screen)
    draw_arrows(screen)
    draw_selection(screen, selected_cell)

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
    status_color = ERROR_COLOR if mistakes_remaining == 0 else TEXT_COLOR
    status_surface = info_font.render(status_text, True, status_color)
    status_rect = status_surface.get_rect(
        center=(WINDOW_WIDTH // 2, 605)
    )
    screen.blit(status_surface, status_rect)
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
