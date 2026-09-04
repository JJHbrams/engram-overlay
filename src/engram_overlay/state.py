"""Renderer state derived only from Engram's metadata-safe event envelope."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .protocol import DISPLAY_HINTS

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

    def apply(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        payload = message.get("payload", {})
        hint = message.get("display_hint")
        if isinstance(hint, str):
            self.display_hint = hint if hint in DISPLAY_HINTS else "idle"
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

