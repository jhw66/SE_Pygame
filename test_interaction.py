"""离屏 Pygame 交互、状态机、实际事件循环和绘制回归测试。"""
import os
# 用虚拟视频和音频驱动运行真实 Pygame 事件与绘制，不弹出测试窗口。
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

from pathlib import Path
import random
import threading
import time
import unittest
from unittest.mock import patch
import pygame

from board_view import BoardView, ARROW_PALETTE, ERROR_COLOR
from game_logic import Arrow, BoardState, DIRECTIONS, moving_shape, solve_board
from game_state import COLLISION_PAUSE, FAILED, GameSession, PLAYING, WON
from levels import GenerationError, LevelConfig, generate_level, load_level
from main import GameApp, main

ROOT = Path(__file__).parent


def click(pos, button=1):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)


def send(app, events):
    """历史点击场景补齐左键松开事件；拖动测试直接发送原始事件。"""
    expanded = []
    for event in events:
        expanded.append(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            expanded.append(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=event.pos, button=1))
    app.handle_events(expanded)


def fixture():
    return load_level(ROOT / "examples/manual.json")


class SessionTests(unittest.TestCase):
    # 直接推进时间，验证一秒上限、扣机会时机、精确回退与重开取消。
    def test_complete_exit_and_collision_roundtrip_within_one_second(self):
        speeds = []
        for size in (4, 8, 16, 25, 50):
            for blocked in (False, True):
                arrows = {0: Arrow(0, ((0, 0),), "R")}
                if blocked:
                    arrows[1] = Arrow(1, ((0, size - 1),), "U")
                board = BoardState(size, size, arrows)
                for increments in ([1.0], [1 / 120] * 120):
                    game = GameSession(board)
                    game.click((0, 0))
                    if not blocked and len(increments) == 1:
                        speeds.append(game.motion.speed)
                    for dt in increments:
                        game.update(dt)
                    self.assertIsNone(game.motion, (size, blocked))
                    if blocked:
                        self.assertEqual(game.board, board)
                        self.assertEqual(game.mistakes_remaining, 2)
                    else:
                        self.assertEqual(game.state, WON)
                        self.assertFalse(game.board.arrows)
        self.assertTrue(all(a < b for a, b in zip(speeds, speeds[1:])))

    def test_long_bent_body_also_completes_within_one_second(self):
        cells = tuple((r, c) for r in range(5)
                      for c in (range(25) if r % 2 == 0 else range(24, -1, -1)))
        game = GameSession(BoardState(25, 25, {0: Arrow(0, cells, "R")}))
        game.click(cells[-1])
        game.update(0.999)
        self.assertEqual(len(game.board.arrows), 1)
        self.assertIsNotNone(game.motion)
        game.update(0.001)
        self.assertEqual(game.state, WON)
        self.assertIsNone(game.motion)

    def test_collision_progress_pause_return_and_charge_once(self):
        game = GameSession(fixture())
        before = game.board.copy()
        self.assertTrue(game.click((2, 3)))
        distance = game.motion.plan.distance
        game.update(distance / game.motion.speed / 2)
        self.assertGreater(game.motion.progress, 0)
        self.assertEqual(game.mistakes_remaining, 3)
        self.assertEqual(game.board, before)
        self.assertFalse(game.click((0, 0)))
        game.update(distance / game.motion.speed / 2 + 0.01)
        self.assertEqual(game.motion.phase, "pause")
        self.assertEqual(game.mistakes_remaining, 2)
        game.update(COLLISION_PAUSE)
        self.assertEqual(game.motion.phase, "return")
        self.assertLess(game.motion.progress, distance)
        self.assertEqual(game.mistakes_remaining, 2)
        game.update(5)
        self.assertIsNone(game.motion)
        self.assertEqual(game.board, before)
        self.assertEqual(game.mistakes_remaining, 2)
        self.assertEqual(moving_shape(game.board.arrows[0]), moving_shape(before.arrows[0]))

    def test_third_collision_fails_only_after_return(self):
        game = GameSession(fixture())
        for _ in range(2):
            game.click((2, 3))
            game.update(10)
        game.click((2, 3))
        game.update(game.motion.plan.distance / game.motion.speed + 0.01)
        self.assertEqual(game.mistakes_remaining, 0)
        self.assertEqual(game.state, PLAYING)
        self.assertIsNotNone(game.motion)
        self.assertFalse(game.click((0, 0)))
        game.update(10)
        self.assertEqual(game.state, FAILED)
        self.assertFalse(game.click((0, 0)))
        game.update(20)
        self.assertEqual(game.mistakes_remaining, 0)
        game.restart()
        self.assertEqual(game.state, PLAYING)
        self.assertEqual(game.mistakes_remaining, 3)

    def test_four_directions_adjacent_distant_straight_and_bent(self):
        # 将同一个右向夹具旋转四次，覆盖四方向弯曲/直线/单格。
        def rotate(cell, turns):
            r, c = cell
            for _ in range(turns):
                r, c = c, 6 - r
            return r, c
        for cells in (((3, 2),), ((3, 0), (3, 1), (3, 2)),
                      ((4, 0), (4, 1), (3, 1), (3, 2))):
            for turns, direction in enumerate(("R", "D", "L", "U")):
                for col in (3, 5):
                    a = Arrow(0, tuple(rotate(cell, turns) for cell in cells), direction)
                    blocker = Arrow(1, (rotate((3, col), turns),), "U")
                    game = GameSession(BoardState(7, 7, {0: a, 1: blocker}))
                    before = game.board.copy()
                    game.click(a.head)
                    distance = game.motion.plan.distance
                    self.assertGreater(distance, 0)
                    game.update(distance / game.motion.speed + 0.001)
                    self.assertEqual(game.motion.phase, "pause")
                    self.assertEqual(game.mistakes_remaining, 2)
                    game.update(10)
                    self.assertEqual(game.board, before)
                    game.board.remove(1)
                    game.click(a.head)
                    game.update(20)
                    self.assertEqual(game.state, WON)
                    self.assertEqual(game.mistakes_remaining, 2)

    def test_self_collision_returns(self):
        cells = ((5, 4), (4, 4), (3, 4), (2, 4), (2, 3), (2, 2), (2, 1), (3, 1), (3, 2))
        board = BoardState(6, 6, {0: Arrow(0, cells, "R")})
        game = GameSession(board)
        game.click((3, 2))
        game.update(10)
        self.assertEqual(game.board, board)
        self.assertEqual(game.mistakes_remaining, 2)

    def test_dt_partition_and_complete_exit_before_win(self):
        a, b = GameSession(fixture()), GameSession(fixture())
        a.click((2, 3))
        b.click((2, 3))
        a.update(0.45)
        for _ in range(45):
            b.update(0.01)
        self.assertEqual(a.motion.phase, b.motion.phase)
        self.assertAlmostEqual(a.motion.progress, b.motion.progress)
        self.assertEqual(a.mistakes_remaining, b.mistakes_remaining)
        game = GameSession(BoardState(1, 1, {0: Arrow(0, ((0, 0),), "R")}))
        game.click((0, 0))
        duration = game.motion.plan.distance / game.motion.speed
        game.update(duration - 0.01)
        self.assertEqual(game.state, PLAYING)
        self.assertEqual(len(game.board.arrows), 1)
        game.update(0.02)
        self.assertEqual(game.state, WON)
        self.assertFalse(game.board.arrows)

    def test_restart_load_cancel_every_phase(self):
        for phase in ("forward", "pause", "return"):
            for load in (False, True):
                game = GameSession(fixture())
                game.click((2, 3))
                duration = game.motion.plan.distance / game.motion.speed
                elapsed = {"forward": duration / 2, "pause": duration + 0.01,
                           "return": duration * 1.5 + COLLISION_PAUSE}[phase]
                game.update(elapsed)
                self.assertEqual(game.motion.phase, phase)
                if load:
                    replacement = BoardState(4, 4, {10: Arrow(10, ((0, 0),), "U")})
                    game.load(replacement)
                else:
                    replacement = fixture()
                    game.restart()
                game.update(20)
                self.assertEqual(game.board, replacement)
                self.assertEqual(game.mistakes_remaining, 3)
                self.assertIsNone(game.motion)


class InteractionTests(unittest.TestCase):
    # 通过实际事件和画面像素验证点击、拖动、配色、布局与异步任务隔离。
    def setUp(self):
        pygame.init()
        self.screen = pygame.display.set_mode((960, 640))
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            app.close()
            if app.worker is not None:
                app.worker.join(timeout=1)
        pygame.quit()

    def app(self, **kwargs):
        app = GameApp(self.screen, **kwargs)
        self.apps.append(app)
        return app

    def test_left_drag_moves_both_ways_without_accidental_arrow_click(self):
        board = BoardState(25, 25, {0: Arrow(0, ((12, 12),), "R")})
        app = self.app(board=board)
        app.view.zoom(app.view.rect.center, 4)
        for dx in (80, -110):
            start = app.view.to_screen((12, 12))
            end = start[0] + dx, start[1]
            before_x = app.view.x
            app.handle_events([click(start)])
            self.assertIsNone(app.session.motion)
            app.handle_events([
                pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(dx, 0)),
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end, button=1),
            ])
            self.assertAlmostEqual(app.view.x, before_x + dx)
            self.assertIsNone(app.session.motion)
            self.assertEqual(app.session.mistakes_remaining, 3)
        head = app.view.to_screen((12, 12))
        app.handle_events([click(head)])
        self.assertIsNone(app.session.motion)
        app.handle_events([pygame.event.Event(pygame.MOUSEBUTTONUP, pos=head, button=1)])
        self.assertIsNotNone(app.session.motion)

    def test_horizontal_wheel_shift_wheel_keys_and_pan_limits(self):
        app = self.app(board=BoardState(25, 25, {0: Arrow(0, ((12, 12),), "U")}))
        center = app.view.rect.center
        app.view.zoom(center, 4)
        scale = app.view.cell_size
        for event in (
            pygame.event.Event(pygame.MOUSEWHEEL, x=1, y=0, pos=center),
            pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1, mod=pygame.KMOD_SHIFT, pos=center),
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT),
        ):
            before = app.view.x
            app.handle_events([event])
            self.assertLess(app.view.x, before)
            self.assertEqual(app.view.cell_size, scale)
        before = app.view.x
        app.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT)])
        self.assertGreater(app.view.x, before)
        app.view.pan(1e6, 1e6)
        self.assertAlmostEqual(app.view.x, app.view.rect.left)
        app.view.pan(-1e6, -1e6)
        self.assertAlmostEqual(app.view.x + app.view.cols * scale, app.view.rect.right)
        before = app.view.x
        app.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=-2, y=0, pos=(0, 0))])
        self.assertEqual(app.view.x, before)

    def test_pending_click_cancels_on_restart_focus_loss_or_view_change(self):
        app = self.app(board=fixture())
        for action in (lambda: app.restart(),
                       lambda: app.handle_events([pygame.event.Event(pygame.WINDOWFOCUSLOST)]),
                       lambda: app.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, y=1, pos=app.view.rect.center)])):
            pos = app.view.to_screen((2, 3))
            app.handle_events([click(pos)])
            action()
            app.handle_events([pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)])
            self.assertIsNone(app.session.motion)
            self.assertEqual(app.session.mistakes_remaining, 3)

    def test_ten_random_colors_are_visible_stable_and_restored_on_restart(self):
        board = BoardState(4, 5, {i: Arrow(i, (divmod(i, 5),), "U") for i in range(20)})
        app = self.app(board=board, seed=42)
        colors = app.view.arrow_colors.copy()
        self.assertEqual(len(set(ARROW_PALETTE)), 10)
        self.assertNotIn(ERROR_COLOR, ARROW_PALETTE)
        self.assertEqual(set(colors.values()), set(ARROW_PALETTE))
        app.draw()
        for arrow_id, arrow in board.arrows.items():
            x, y = app.view.to_screen(arrow.head)
            self.assertEqual(tuple(self.screen.get_at((round(x), round(y)))[:3]), colors[arrow_id])
        pixels = pygame.image.tobytes(self.screen.subsurface(app.view.rect), "RGB")
        app.draw()
        self.assertEqual(pygame.image.tobytes(self.screen.subsurface(app.view.rect), "RGB"), pixels)
        send(app, [click(app.view.to_screen((0, 0)))])
        app.update(1)
        app.restart()
        app.draw()
        self.assertEqual(app.view.arrow_colors, colors)
        self.assertEqual(pygame.image.tobytes(self.screen.subsurface(app.view.rect), "RGB"), pixels)
        app.install(board)
        self.assertNotEqual(app.view.arrow_colors, colors)

    def test_head_cell_blank_and_body_clicks(self):
        for offset in ((0.05, 0.05), (0.5, 0.5), (0.95, 0.95)):
            app = self.app(board=fixture())
            r, c = (2, 3)
            pos = app.view.x + (c + offset[0]) * app.view.cell_size, app.view.y + (r + offset[1]) * app.view.cell_size
            send(app, [click(pos)])
            self.assertIsNotNone(app.session.motion)
            self.assertEqual(app.session.motion.plan.arrow_id, 0)
        app = self.app(board=fixture())
        for cell in ((3, 1), (3, 2), (2, 2), (2, 5), (6, 2), (0, 7)):
            before = app.session.status
            send(app, [click(app.view.to_screen(cell))])
            self.assertIsNone(app.session.motion)
            self.assertEqual(app.session.status, before)
            self.assertEqual(app.session.mistakes_remaining, 3)
        send(app, [click(app.view.to_screen((0, 0)), 3), click((0, 0))])
        self.assertIsNone(app.session.motion)

    def test_zoom_pan_hit_mapping_and_overview(self):
        # 沉浸布局下 25×25 已足够直接点击；用更大棋盘验证概览保护。
        board = BoardState(40, 40, {0: Arrow(0, ((20, 18), (20, 19), (20, 20)), "R")})
        app = self.app(board=board)
        self.assertFalse(app.view.can_click)
        send(app, [click(app.view.to_screen((20, 20)))])
        self.assertIsNone(app.session.motion)
        anchor = app.view.rect.center
        send(app, [pygame.event.Event(pygame.MOUSEWHEEL, y=5, pos=anchor)])
        self.assertTrue(app.view.can_click)
        send(app, [click(anchor, 2), pygame.event.Event(pygame.MOUSEMOTION, rel=(30, -25)),
                           pygame.event.Event(pygame.MOUSEBUTTONUP, button=2, pos=anchor)])
        self.assertEqual(app.view.cell_at(app.view.to_screen((20, 20))), (20, 20))
        send(app, [click(app.view.to_screen((20, 19)))])
        self.assertIsNone(app.session.motion)
        send(app, [click(app.view.to_screen((20, 20)))])
        self.assertIsNotNone(app.session.motion)
        progress = app.session.motion.progress
        send(app, [pygame.event.Event(pygame.MOUSEWHEEL, y=1, pos=anchor)])
        app.draw()
        self.assertEqual(app.session.motion.progress, progress)
        saved = (app.view.x, app.view.y, app.view.cell_size)
        send(app, [click(app.buttons["restart"].center)])
        self.assertEqual((app.view.x, app.view.y, app.view.cell_size), saved)
        send(app, [click(app.buttons["fit"].center)])
        self.assertFalse(app.view.can_click)
        self.assertIsNone(app.view.cell_at((app.view.rect.right, app.view.rect.centery)))

    def test_click_and_restart_queued_events(self):
        app = self.app(board=fixture())
        send(app, [click(app.view.to_screen((2, 3))), click(app.view.to_screen((0, 0)))])
        self.assertEqual(app.session.motion.plan.arrow_id, 0)
        app.update(0.4)
        send(app, [click(app.buttons["restart"].center), click(app.view.to_screen((2, 3)))])
        app.update(10)
        self.assertEqual(app.session.board, fixture())
        self.assertEqual(app.session.mistakes_remaining, 3)
        self.assertIsNone(app.session.motion)

    def test_actual_pixels_collision_and_return(self):
        app = self.app(board=fixture())
        app.draw()
        original = pygame.image.tobytes(self.screen.subsurface(app.view.rect), "RGB")
        send(app, [click(app.view.to_screen((2, 3)))])
        distance = app.session.motion.plan.distance
        app.update(distance / app.session.motion.speed + 0.001)
        app.draw()
        path, _ = moving_shape(app.session.board.arrows[0], distance)
        x, y = app.view.to_screen(path[0])
        # 首点处可能受整数端点取整影响，检查其附近是否真正绘出红色。
        self.assertTrue(any(tuple(self.screen.get_at((round(x) + dx, round(y) + dy))[:3]) == ERROR_COLOR
                            for dx in range(-2, 3) for dy in range(-2, 3)))
        app.update(10)
        app.draw()
        restored = pygame.image.tobytes(self.screen.subsurface(app.view.rect), "RGB")
        self.assertEqual(original, restored)
        self.assertEqual(self.screen.get_clip(), self.screen.get_rect())

    def test_whole_game_win_restart_and_manual_new_disabled(self):
        app = self.app(board=fixture())
        original = app.session.initial.copy()
        for arrow_id in solve_board(original):
            send(app, [click(app.view.to_screen(app.session.board.arrows[arrow_id].head))])
            app.update(50)
        app.draw()
        self.assertEqual(app.session.state, WON)
        self.assertEqual(app.session.mistakes_remaining, 3)
        send(app, [click(app.buttons["new"].center)])
        self.assertFalse(app.generating)
        self.assertEqual(app.session.state, WON)
        send(app, [click(app.buttons["restart"].center)])
        self.assertEqual(app.session.board, original)

    def wait_job(self, app):
        deadline = time.monotonic() + 3
        while app.generating and time.monotonic() < deadline:
            app.update(0)
            time.sleep(0.001)
        self.assertFalse(app.generating, "生成线程未按时完成")

    def test_generation_failure_success_and_stale_result(self):
        def fail(*args, **kwargs):
            raise GenerationError("测试预算耗尽")
        app = self.app(config=LevelConfig(7, 8, 5), board=fixture(), level_factory=fail)
        before = app.session.board.copy()
        app.request_new()
        self.wait_job(app)
        self.assertEqual(app.session.board, before)
        self.assertIn("失败", app.notice)
        app.level_factory = generate_level
        app.request_new()
        self.wait_job(app)
        self.assertNotEqual(app.session.board.signature(), before.signature())
        expected = app.session.initial.copy()
        app.session.click(next(iter(expected.arrows.values())).head)
        app.restart()
        self.assertEqual(app.session.board, expected)
        # 旧任务即使不遵守取消信号，结果也不能覆盖重开后的棋盘。
        release = threading.Event()
        def delayed(*args, **kwargs):
            release.wait(1)
            return fixture()
        app.level_factory = delayed
        app.request_new()
        worker = app.worker
        app.restart()
        release.set()
        worker.join(1)
        app.update(20)
        self.assertEqual(app.session.board, expected)

    def test_responsive_generation_and_quit_during_motion(self):
        release = threading.Event()
        def delayed(*args, **kwargs):
            release.wait(1)
            return fixture()
        app = self.app(config=LevelConfig(), board=fixture(), level_factory=delayed)
        app.request_new()
        send(app, [pygame.event.Event(pygame.MOUSEWHEEL, y=1, pos=app.view.rect.center)])
        app.draw()
        send(app, [pygame.event.Event(pygame.QUIT)])
        self.assertFalse(app.running)
        self.assertTrue(app.cancel_event.is_set())
        release.set()
        app.worker.join(1)
        moving = self.app(board=fixture())
        moving.session.click((2, 3))
        send(moving, [pygame.event.Event(pygame.QUIT)])
        self.assertFalse(moving.running)

    def test_real_main_loop_closes(self):
        with patch("pygame.event.get", side_effect=[[], [pygame.event.Event(pygame.QUIT)]]):
            main(["--level", str(ROOT / "examples/manual.json")])

    def test_generated_games_complete_through_head_clicks(self):
        config = LevelConfig(8, 8, 18, 1, 5, 0.4)
        for seed in (18, 29, 53):
            board = generate_level(config, rng=random.Random(seed))
            app = self.app(config=config, board=board)
            for arrow_id in solve_board(board):
                before = len(app.session.board.arrows)
                head = app.session.board.arrows[arrow_id].head
                send(app, [click(app.view.to_screen(head))])
                self.assertIsNotNone(app.session.motion)
                self.assertEqual(len(app.session.board.arrows), before)
                app.update(100)
                self.assertEqual(len(app.session.board.arrows), before - 1)
            self.assertEqual(app.session.state, WON)
            self.assertEqual(app.session.mistakes_remaining, 3)

    def test_resize_and_nonpreset_dimensions(self):
        for rows, cols in ((4, 4), (7, 10), (16, 16), (25, 25), (27, 31)):
            head = rows // 2, cols // 2
            board = BoardState(rows, cols, {0: Arrow(0, (head,), "U")})
            app = self.app(board=board)
            send(app, [pygame.event.Event(pygame.VIDEORESIZE, w=800, h=600)])
            app.view.zoom(app.view.to_screen(head), 10)
            self.assertEqual(app.view.cell_at(app.view.to_screen(head)), head)
            send(app, [click(app.view.to_screen(head))])
            self.assertIsNotNone(app.session.motion)
            app.draw()

    def test_seeded_async_puzzle_sequence(self):
        config = LevelConfig(4, 4, 6, 1, 4, 0.5)
        a = self.app(config=config, seed=42)
        b = self.app(config=config, seed=42)
        self.wait_job(a)
        self.wait_job(b)
        first = a.session.initial.signature()
        self.assertEqual(first, b.session.initial.signature())
        for app in (a, b):
            app.request_new()
            self.wait_job(app)
        self.assertEqual(a.session.initial.signature(), b.session.initial.signature())
        self.assertNotEqual(first, a.session.initial.signature())

    def test_immersive_layout_centers_board_without_controls_covering_cells(self):
        for size in ((800, 600), (960, 640), (1920, 1080), (960, 960), (800, 1200)):
            self.screen = pygame.display.set_mode(size)
            for rows, cols in ((4, 4), (25, 25), (7, 10), (4, 25), (25, 4)):
                with self.subTest(size=size, board=(rows, cols)):
                    head = rows // 2, cols // 2
                    app = self.app(board=BoardState(rows, cols, {0: Arrow(0, (head,), "U")}))
                    self.assertEqual(app.view.rect.center, self.screen.get_rect().center)
                    controls = [*app.buttons.values(), app.summary_rect, app.status_rect, app.help_rect]
                    for rect in controls:
                        self.assertFalse(rect.colliderect(app.view.rect))
                        self.assertTrue(self.screen.get_rect().contains(rect))
                    app.view.zoom(app.view.rect.center, 5)
                    app.view.pan(200, -200)
                    app.draw()
                    app.view.fit()
                    self.assertEqual(app.view.cell_at(app.view.to_screen(head)), head)

    def test_small_board_fills_window_height_and_zoom_can_return_to_fit(self):
        board = BoardState(4, 4, {0: Arrow(0, ((2, 2),), "U")})
        app = self.app(board=board)
        self.assertEqual(app.hud_mode, "sides")
        self.assertEqual(app.view.rect.height, self.screen.get_height() - 16)
        self.assertAlmostEqual(app.view.rows * app.view.cell_size, app.view.rect.height)
        self.assertGreater(app.view.cell_size, 80)
        initial_size = app.view.cell_size
        app.view.zoom(app.view.rect.center, 1)
        self.assertGreater(app.view.cell_size, initial_size)
        app.view.zoom(app.view.rect.center, -20)
        self.assertAlmostEqual(app.view.cell_size, initial_size)
        send(app, [click(app.view.to_screen((2, 2)))])
        self.assertIsNotNone(app.session.motion)


if __name__ == "__main__":
    unittest.main()
