"""Small Tk renderer that demonstrates observer and replace mode wiring."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Any

from .protocol import JsonlTransport, geometry_message, pointer_message
from .state import OverlayState


class OverlayApp:
    WIDTH = 180
    HEIGHT = 180

    def __init__(self, transport: JsonlTransport, *, mode: str = "observer") -> None:
        self.transport = transport
        self.mode = mode
        self.state = OverlayState()
        self.inbox: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.root = tk.Tk()
        self.root.title("Engram Custom Overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+100+100")
        self.canvas = tk.Canvas(self.root, width=self.WIDTH, height=self.HEIGHT, highlightthickness=0, bg="#111827")
        self.canvas.pack(fill="both", expand=True)
        self.body = self.canvas.create_oval(20, 20, 160, 160, fill="#86a8e7", outline="#e5e7eb", width=3)
        self.label = self.canvas.create_text(90, 90, text="IDLE", fill="#111827", font=("Segoe UI", 15, "bold"))
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._bind_pointer_events()

    def _bind_pointer_events(self) -> None:
        self.canvas.bind("<Enter>", lambda event: self._send_pointer("pointer_enter"))
        self.canvas.bind("<Leave>", lambda event: self._send_pointer("pointer_leave"))
        self.canvas.bind("<Button-1>", self._drag_begin)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Button-3>", self._right_click)

    def run(self) -> None:
        threading.Thread(target=self._read_messages, name="engram-jsonl-reader", daemon=True).start()
        if self.mode == "replace":
            self.root.after_idle(self._send_geometry)
        self.root.after(20, self._drain_messages)
        self.root.mainloop()

    def _read_messages(self) -> None:
        for message in self.transport.messages():
            self.inbox.put(message)
        self.inbox.put(None)

    def _drain_messages(self) -> None:
        while True:
            try:
                message = self.inbox.get_nowait()
            except queue.Empty:
                break
            if message is None:
                self.root.destroy()
                return
            self.state.apply(message)
            if self.state.x is not None and self.state.y is not None:
                self.root.geometry(f"+{self.state.x}+{self.state.y}")
                self.state.x = self.state.y = None
            color, label = self.state.appearance
            self.canvas.itemconfigure(self.body, fill=color)
            self.canvas.itemconfigure(self.label, text=label)
        self.root.after(20, self._drain_messages)

    def _send_pointer(self, action: str, *, x: int | None = None, y: int | None = None) -> None:
        if self.mode == "replace":
            self.transport.send(pointer_message(action, screen_x=x, screen_y=y))

    def _send_geometry(self) -> None:
        self.root.update_idletasks()
        self.transport.send(
            geometry_message(self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height())
        )

    def _drag_begin(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        if self.mode != "replace" or self._drag_origin is None:
            return
        start_x, start_y, window_x, window_y = self._drag_origin
        self.root.geometry(f"+{window_x + event.x_root - start_x}+{window_y + event.y_root - start_y}")
        self._send_pointer("drag_move", x=event.x_root, y=event.y_root)

    def _drag_end(self, event: tk.Event) -> None:
        if self.mode != "replace":
            return
        if self._drag_origin is None:
            self._send_pointer("left_click")
        else:
            start_x, start_y, _, _ = self._drag_origin
            moved = abs(event.x_root - start_x) + abs(event.y_root - start_y) > 4
            if moved:
                self._send_pointer("drag_end", x=event.x_root, y=event.y_root)
                self._send_geometry()
            else:
                self._send_pointer("left_click")
        self._drag_origin = None

    def _right_click(self, event: tk.Event) -> None:
        self._send_pointer("right_click", x=event.x_root, y=event.y_root)
