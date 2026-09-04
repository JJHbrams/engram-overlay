"""Shared Tk window lifecycle and Engram input/geometry wiring."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Any, Protocol

from ..protocol import JsonlTransport, geometry_message, pointer_message
from ..state import OverlayState


class TkOverlayView(Protocol):
    """Visual behavior supplied by one Tk-based overlay implementation."""

    width: int
    height: int
    background: str
    transparent_color: str | None

    def mount(self, canvas: tk.Canvas) -> None: ...

    def apply_state(self, state: OverlayState) -> None: ...

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None: ...


class TkOverlayHost:
    """Own the Tk window while a view owns only drawing and animation."""

    FRAME_MS = 16

    def __init__(
        self,
        transport: JsonlTransport,
        view: TkOverlayView,
        *,
        mode: str = "observer",
        title: str = "Engram Custom Overlay",
    ) -> None:
        self.transport = transport
        self.view = view
        self.mode = mode
        self.state = OverlayState()
        self.inbox: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.root = tk.Tk()
        self.root.title(title)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if view.transparent_color:
            try:
                self.root.attributes("-transparentcolor", view.transparent_color)
            except tk.TclError:
                pass
        self.root.geometry(f"{view.width}x{view.height}+100+100")
        self.canvas = tk.Canvas(
            self.root,
            width=view.width,
            height=view.height,
            highlightthickness=0,
            borderwidth=0,
            bg=view.background,
        )
        self.canvas.pack(fill="both", expand=True)
        self.view.mount(self.canvas)
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._bind_pointer_events()

    def run(self) -> None:
        threading.Thread(target=self._read_messages, name="engram-jsonl-reader", daemon=True).start()
        # Geometry is optional for a passive observer.  Interactive observers
        # emit it so Engram can use this window as a transient bubble anchor.
        self.root.after_idle(self._send_geometry)
        self.root.after(20, self._drain_messages)
        self.root.after(self.FRAME_MS, self._tick)
        self.root.mainloop()

    def _bind_pointer_events(self) -> None:
        self.canvas.bind("<Enter>", lambda event: self._send_pointer("pointer_enter"))
        self.canvas.bind("<Leave>", lambda event: self._send_pointer("pointer_leave"))
        self.canvas.bind("<Button-1>", self._drag_begin)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Button-3>", self._right_click)

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
                # Local pointer motion is newer than queued host echoes.  Let
                # drag_end reconcile the final authoritative position.
                if self._drag_origin is None:
                    self.root.geometry(f"+{self.state.x}+{self.state.y}")
                self.state.x = self.state.y = None
            if self.mode == "replace" and self.state.width is not None and self.state.height is not None:
                resize = getattr(self.view, "resize", None)
                if callable(resize):
                    width, height = resize(self.state.width, self.state.height)
                    self.root.geometry(f"{width}x{height}")
                    self.canvas.config(width=width, height=height)
                    self.root.update_idletasks()
                    self._send_geometry()
                self.state.width = self.state.height = None
            self.view.apply_state(self.state)
        self.root.after(20, self._drain_messages)

    def _tick(self) -> None:
        pointer_x, pointer_y = self.root.winfo_pointerxy()
        self.view.tick(pointer_x, pointer_y, self.root.winfo_x(), self.root.winfo_y())
        self.root.after(self.FRAME_MS, self._tick)

    def _send_pointer(self, action: str, *, x: int | None = None, y: int | None = None) -> None:
        self.transport.send(pointer_message(action, screen_x=x, screen_y=y))

    def _send_geometry(self) -> None:
        self.root.update_idletasks()
        self.transport.send(
            geometry_message(self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height())
        )

    def _drag_begin(self, event: tk.Event) -> None:
        self._send_pointer("menu_dismiss")
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        target_x, target_y = self._drag_target(event)
        self.root.geometry(f"+{target_x}+{target_y}")
        # Event API v1 calls these fields screen_x/screen_y, but Engram treats
        # them as the requested window top-left, not the current pointer.
        self._send_pointer("drag_move", x=target_x, y=target_y)

    def _drag_end(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            self._send_pointer("menu_dismiss")
            self._send_pointer("left_click")
        else:
            start_x, start_y, _, _ = self._drag_origin
            moved = abs(event.x_root - start_x) + abs(event.y_root - start_y) > 4
            if moved:
                target_x, target_y = self._drag_target(event)
                self.root.geometry(f"+{target_x}+{target_y}")
                self._send_pointer("drag_end", x=target_x, y=target_y)
                if self.mode == "observer":
                    self._send_geometry()
            else:
                self._send_pointer("left_click")
        self._drag_origin = None

    def _drag_target(self, event: tk.Event) -> tuple[int, int]:
        if self._drag_origin is None:
            raise RuntimeError("drag target requested without an active drag")
        start_x, start_y, window_x, window_y = self._drag_origin
        return window_x + event.x_root - start_x, window_y + event.y_root - start_y

    def _right_click(self, event: tk.Event) -> None:
        self._send_pointer("menu_dismiss")
        self._send_pointer("right_click", x=event.x_root, y=event.y_root)

