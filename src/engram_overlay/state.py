"""Renderer state derived only from Engram's metadata-safe event envelope."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .protocol import DISPLAY_HINTS, HIDE_MESSAGE, SHOW_MESSAGE, TOOL_CATEGORIES

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

    def apply(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        payload = message.get("payload", {})
        hint = message.get("display_hint")
        if isinstance(hint, str):
            self.display_hint = hint if hint in DISPLAY_HINTS else "idle"
            # display_hint collapses every non-search, non-memory tool into
            # "generating"; payload.category is the only thing that says which
            # kind of work it is. It describes the message that carried it, so a
            # semantic event without one clears it rather than leaving it stale.
            category = payload.get("category") if isinstance(payload, dict) else None
            self.tool_category = category if category in TOOL_CATEGORIES else None
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

