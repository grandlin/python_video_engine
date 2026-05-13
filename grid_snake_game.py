from __future__ import annotations

import random
import traceback
from pathlib import Path
from dataclasses import dataclass


GRID_SIZE = 100
APPLE_COUNT = 20
MOVE_INTERVAL_MS = 1000  # 1 cell per second
CELL_SIZE = 8
WINDOW_PADDING = 12
LOG_PATH = Path(__file__).with_name("grid_snake_game.log")


@dataclass(frozen=True)
class Point:
    x: int
    y: int


class GridSnakeGame:
    def __init__(self, root) -> None:
        self.root = root
        self.root.title("100x100 绿色方块吃苹果")
        canvas_size = GRID_SIZE * CELL_SIZE
        self.canvas = tk.Canvas(
            root,
            width=canvas_size,
            height=canvas_size,
            bg="#0f172a",
            highlightthickness=0,
        )
        self.canvas.pack(padx=WINDOW_PADDING, pady=(WINDOW_PADDING, 4))

        self.status_var = tk.StringVar(value="按 W/A/S/D 改变方向，每秒移动 1 格")
        self.status_label = tk.Label(root, textvariable=self.status_var, anchor="w")
        self.status_label.pack(fill="x", padx=WINDOW_PADDING, pady=(0, WINDOW_PADDING))

        center = GRID_SIZE // 2
        self.snake: list[Point] = [Point(center, center)]
        self.direction = Point(1, 0)
        self.pending_growth = 0
        self.game_over = False
        self.apples: set[Point] = set()
        self._spawn_apples(APPLE_COUNT)

        self.root.bind("<KeyPress>", self._on_keypress)
        self._draw()
        self._tick()

    def _on_keypress(self, event) -> None:
        if self.game_over:
            return

        key = (event.keysym or "").lower()
        key_to_direction = {
            "w": Point(0, -1),
            "a": Point(-1, 0),
            "s": Point(0, 1),
            "d": Point(1, 0),
        }
        new_direction = key_to_direction.get(key)
        if new_direction is None:
            return

        # Prevent reversing directly into the second segment.
        if len(self.snake) > 1:
            second = self.snake[1]
            would_hit_second = Point(
                self.snake[0].x + new_direction.x, self.snake[0].y + new_direction.y
            ) == second
            if would_hit_second:
                return
        self.direction = new_direction

    def _tick(self) -> None:
        if self.game_over:
            return
        self._move_once()
        self._draw()
        self.root.after(MOVE_INTERVAL_MS, self._tick)

    def _move_once(self) -> None:
        head = self.snake[0]
        new_head = Point(
            (head.x + self.direction.x) % GRID_SIZE,
            (head.y + self.direction.y) % GRID_SIZE,
        )

        # According to requirement: if first block touches any green block except
        # the second one, it dies.
        body_except_second = set(self.snake[2:]) if len(self.snake) > 2 else set()
        if new_head in body_except_second:
            self.game_over = True
            self.status_var.set(f"游戏结束！长度: {len(self.snake)}，按窗口关闭退出")
            return

        self.snake.insert(0, new_head)

        if new_head in self.apples:
            self.apples.remove(new_head)
            self.pending_growth += 1
            self.status_var.set(
                f"吃到苹果！当前长度: {len(self.snake)}，剩余苹果: {len(self.apples)}"
            )
            self._spawn_apples(1)
        elif self.pending_growth > 0:
            self.pending_growth -= 1
        else:
            self.snake.pop()

    def _spawn_apples(self, count: int) -> None:
        occupied = set(self.snake)
        free_cells = [
            Point(x, y)
            for x in range(GRID_SIZE)
            for y in range(GRID_SIZE)
            if Point(x, y) not in occupied and Point(x, y) not in self.apples
        ]
        if not free_cells:
            return

        random.shuffle(free_cells)
        for point in free_cells[:count]:
            self.apples.add(point)

    def _draw(self) -> None:
        self.canvas.delete("all")
        self._draw_grid()
        self._draw_apples()
        self._draw_snake()

    def _draw_grid(self) -> None:
        size = GRID_SIZE * CELL_SIZE
        color = "#1e293b"
        for i in range(GRID_SIZE + 1):
            pos = i * CELL_SIZE
            self.canvas.create_line(pos, 0, pos, size, fill=color)
            self.canvas.create_line(0, pos, size, pos, fill=color)

    def _draw_apples(self) -> None:
        for apple in self.apples:
            self._draw_cell(apple, "#ef4444")

    def _draw_snake(self) -> None:
        for idx, block in enumerate(self.snake):
            color = "#22c55e" if idx == 0 else "#16a34a"
            self._draw_cell(block, color)

    def _draw_cell(self, point: Point, color: str) -> None:
        x0 = point.x * CELL_SIZE
        y0 = point.y * CELL_SIZE
        x1 = x0 + CELL_SIZE
        y1 = y0 + CELL_SIZE
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")


def main() -> None:
    tk = _import_tkinter()
    root = tk.Tk()
    GridSnakeGame(root)
    root.mainloop()


def _import_tkinter():
    try:
        import tkinter as tk  # pylint: disable=import-outside-toplevel
    except Exception as exc:
        _log_exception("导入 tkinter 失败", exc)
        _show_fatal_error(
            "启动失败：当前 Python 环境缺少 tkinter。\n"
            "请安装带 Tk 的 Python，或重新安装官方 Python。"
        )
        raise SystemExit(1) from exc
    return tk


def _show_fatal_error(message: str) -> None:
    try:
        import ctypes  # pylint: disable=import-outside-toplevel

        ctypes.windll.user32.MessageBoxW(0, message, "游戏启动失败", 0x10)
    except Exception:
        # As a fallback for non-Windows/no-ctypes environments.
        print(message)


def _log_exception(context: str, exc: Exception) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    text = f"{context}\n{detail}\n"
    try:
        LOG_PATH.write_text(text, encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # Keep traceback visible even when launched by double-click.
        _log_exception("运行期间发生未处理异常", exc)
        _show_fatal_error(
            "程序发生异常，已写入日志：\n"
            f"{LOG_PATH}\n\n请把这个日志发给我，我继续修。"
        )
