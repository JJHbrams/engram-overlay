"""Renderer state derived only from Engram's metadata-safe event envelope."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .protocol import DISPLAY_HINTS, HIDE_MESSAGE, MODES, SHOW_MESSAGE, TOOL_CATEGORIES

PALETTE = {
    "default": ("#86a8e7", "READY"),
    "idle": ("#86a8e7", "IDLE"),
    "hover": ("#91eae4", "HELLO"),
    "click": ("#fbc2eb", "CLICK"),
    "input": ("#f6d365", "INPUT"),
    "generating": ("#a18cd1", "THINKING"),
    "search": ("#4facfe", "SEARCH"),
    "thought": ("#c2e9fb", "THOUGHT"),
    "memory": ("#43e97b", "MEMORY"),
    "success": ("#38f9d7", "DONE"),
    "provider_error": ("#fa709a", "PROVIDER"),
    "error": ("#ff5858", "ERROR"),
}

_INPUT_ACTIVE = "conversation.input_active"
_INPUT_IDLE = "conversation.input_idle"
_POINTER_ENTERED = "pointer.entered"
_POINTER_LEFT = "pointer.left"
_TRANSIENT_HINT_TYPES = frozenset({
    _INPUT_ACTIVE,
    _INPUT_IDLE,
    _POINTER_ENTERED,
    _POINTER_LEFT,
    "conversation.input_submitted",
    "pointer.left_clicked",
    "pointer.right_clicked",
})
_CONTROL_HINT_TYPES = frozenset({
    "engram.welcome",
    "renderer.assignment",
    "overlay.show",
    "overlay.hide",
    "overlay.set_position",
    "overlay.set_size",
})


@dataclass
class OverlayState:
    display_hint: str = "idle"
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    tool_category: str | None = None
    # None until Engram speaks about presentation at all.
    presentation: str | None = None
    # Event API v2 assigns the mode rather than taking it as an argument, and
    # recomputes it whenever selection changes, so it is state and not config.
    mode: str | None = None
    selected: bool | None = None
    _work_display_hint: str = field(default="idle", init=False, repr=False)
    _pointer_hovered: bool = field(default=False, init=False, repr=False)
    _input_active: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.display_hint in DISPLAY_HINTS:
            self._work_display_hint = self.display_hint

    def _restore_active_hint(self) -> None:
        if self._input_active:
            self.display_hint = "input"
        elif self._pointer_hovered:
            self.display_hint = "hover"
        else:
            self.display_hint = self._work_display_hint

    def apply(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        payload = message.get("payload", {})
        hint = message.get("display_hint")
        if isinstance(hint, str):
            resolved_hint = hint if hint in DISPLAY_HINTS else "idle"
            # display_hint collapses every non-search, non-memory tool into
            # "generating"; payload.category is the only thing that says which
            # kind of work it is. It describes the message that carried it, so a
            # semantic event without one clears it rather than leaving it stale.
            if message_type not in _TRANSIENT_HINT_TYPES and message_type not in _CONTROL_HINT_TYPES:
                self._work_display_hint = resolved_hint
                category = payload.get("category") if isinstance(payload, dict) else None
                self.tool_category = category if category in TOOL_CATEGORIES else None
                self._restore_active_hint()
            elif message_type == _INPUT_ACTIVE:
                self._input_active = True
                self._restore_active_hint()
            elif message_type == _INPUT_IDLE:
                self._input_active = False
                self._restore_active_hint()
            elif message_type == _POINTER_ENTERED:
                self._pointer_hovered = True
                self._restore_active_hint()
            elif message_type == _POINTER_LEFT:
                self._pointer_hovered = False
                self._restore_active_hint()
            elif message_type not in _CONTROL_HINT_TYPES:
                self.display_hint = resolved_hint
        if message_type in ("engram.welcome", "renderer.assignment") and isinstance(payload, dict):
            mode = payload.get("mode")
            if mode in MODES:
                self.mode = mode
            selected = payload.get("selected")
            if isinstance(selected, bool):
                self.selected = selected
        if message_type == SHOW_MESSAGE:
            self.presentation = "shown"
        elif message_type == HIDE_MESSAGE:
            self.presentation = "hidden"
        if message_type == "overlay.set_position" and isinstance(payload, dict):
            x = payload.get("x")
            y = payload.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                self.x, self.y = int(x), int(y)
        if message_type == "overlay.set_size" and isinstance(payload, dict):
            width, height = payload.get("width"), payload.get("height")
            if (
                isinstance(width, (int, float)) and isinstance(height, (int, float))
                and math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0
            ):
                self.width, self.height = int(width), int(height)

    @property
    def appearance(self) -> tuple[str, str]:
        return PALETTE.get(self.display_hint, PALETTE["idle"])

