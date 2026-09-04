"""Engram External Overlay Event API v1 JSONL helpers."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import IO, Any, Iterator

SCHEMA_VERSION = 1
DISPLAY_HINTS = frozenset(
    {
        "default",
        "idle",
        "hover",
        "click",
        "input",
        "generating",
        "search",
        "thought",
        "memory",
        "success",
        "provider_error",
        "error",
    }
)
# Engram's launcher icon owns whether the character is on screen. A renderer that
# advertises this capability starts collapsed and is shown or hidden by the host;
# one that does not keeps the always-visible behaviour.
PRESENTATION_CAPABILITY = "overlay.presentation"
SHOW_MESSAGE = "overlay.show"
HIDE_MESSAGE = "overlay.hide"

# The only tool information Engram publishes: a category, never a tool name.
TOOL_CATEGORIES = frozenset(
    {"memory", "search", "read", "write", "execute", "communication", "other"}
)
POINTER_ACTIONS = frozenset(
    {
        "left_click",
        "right_click",
        "pointer_enter",
        "pointer_leave",
        "drag_begin",
        "drag_move",
        "drag_end",
        "menu_dismiss",
    }
)
COORDINATE_ACTIONS = frozenset({"right_click", "drag_move", "drag_end"})


class ProtocolError(ValueError):
    """Raised when a JSONL line is not a valid v1 protocol object."""


def hello_message(*, capabilities: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "overlay.hello",
        "payload": {"supported_schema_versions": [SCHEMA_VERSION], **({"capabilities": capabilities} if capabilities else {})},
    }


def geometry_message(x: int, y: int, width: int, height: int) -> dict[str, Any]:
    if width <= 0 or height <= 0:
        raise ProtocolError("geometry width and height must be positive")
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "overlay.geometry_changed",
        "payload": {"x": int(x), "y": int(y), "width": int(width), "height": int(height)},
    }


def visibility_message(visible: bool) -> dict[str, Any]:
    """Reported once the show or hide animation has finished, not when it starts."""
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "overlay.visibility_changed",
        "payload": {"visible": bool(visible)},
    }


def pointer_message(action: str, *, screen_x: int | None = None, screen_y: int | None = None) -> dict[str, Any]:
    if action not in POINTER_ACTIONS:
        raise ProtocolError(f"unsupported pointer action: {action}")
    payload: dict[str, Any] = {"action": action}
    if action in COORDINATE_ACTIONS:
        if screen_x is None or screen_y is None:
            raise ProtocolError(f"{action} requires screen coordinates")
        payload.update(screen_x=int(screen_x), screen_y=int(screen_y))
    return {"schema_version": SCHEMA_VERSION, "type": "pointer.action", "payload": payload}


def parse_message(line: str) -> dict[str, Any]:
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid JSONL") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message must be a JSON object")
    if message.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("unsupported schema_version")
    if not isinstance(message.get("type"), str):
        raise ProtocolError("message type must be a string")
    payload = message.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("message payload must be an object")
    return message


@dataclass
class JsonlTransport:
    """Thread-safe JSONL transport. Protocol data uses stdout; diagnostics use stderr."""

    reader: IO[str]
    writer: IO[str]
    diagnostics: IO[str]

    def __post_init__(self) -> None:
        self._write_lock = threading.Lock()

    def send(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            self.writer.write(encoded + "\n")
            self.writer.flush()

    def log(self, message: str) -> None:
        self.diagnostics.write(message + "\n")
        self.diagnostics.flush()

    def messages(self) -> Iterator[dict[str, Any]]:
        for line in self.reader:
            if not line.strip():
                continue
            try:
                yield parse_message(line)
            except ProtocolError as exc:
                self.log(str(exc))

