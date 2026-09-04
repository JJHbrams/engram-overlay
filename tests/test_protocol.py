import io
import json
import unittest

from engram_overlay.protocol import (
    TOOL_CATEGORIES,
    JsonlTransport,
    ProtocolError,
    geometry_message,
    hello_message,
    parse_message,
    pointer_message,
)
from engram_overlay.state import OverlayState


class ProtocolTests(unittest.TestCase):
    def test_hello_contract(self) -> None:
        self.assertEqual(
            hello_message(),
            {
                "schema_version": 1,
                "type": "overlay.hello",
                "payload": {"supported_schema_versions": [1]},
            },
        )

    def test_optional_capability_is_additive(self) -> None:
        self.assertEqual(hello_message(capabilities=["overlay.set_size"])["payload"]["capabilities"], ["overlay.set_size"])

    def test_geometry_requires_positive_size(self) -> None:
        self.assertEqual(geometry_message(1, 2, 3, 4)["payload"]["width"], 3)
        with self.assertRaises(ProtocolError):
            geometry_message(1, 2, 0, 4)

    def test_coordinate_actions_require_both_coordinates(self) -> None:
        with self.assertRaises(ProtocolError):
            pointer_message("right_click", screen_x=10)
        message = pointer_message("drag_end", screen_x=10, screen_y=20)
        self.assertEqual(message["payload"]["screen_y"], 20)

    def test_parser_rejects_invalid_json_and_schema(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_message("not json")
        with self.assertRaises(ProtocolError):
            parse_message('{"schema_version":2,"type":"future"}')

    def test_transport_keeps_diagnostics_off_protocol_stdout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        transport = JsonlTransport(io.StringIO(), stdout, stderr)
        transport.send(hello_message())
        transport.log("diagnostic")
        self.assertEqual(json.loads(stdout.getvalue())["type"], "overlay.hello")
        self.assertEqual(stderr.getvalue(), "diagnostic\n")

    def test_unknown_hint_falls_back_to_idle(self) -> None:
        state = OverlayState()
        state.apply({"schema_version": 1, "type": "future.event", "display_hint": "future", "payload": {}})
        self.assertEqual(state.display_hint, "idle")

    def test_set_position_updates_coordinates(self) -> None:
        state = OverlayState()
        state.apply({"schema_version": 1, "type": "overlay.set_position", "payload": {"x": 31.5, "y": 42}})
        self.assertEqual((state.x, state.y), (31, 42))

    def test_set_size_updates_pending_dimensions(self) -> None:
        state = OverlayState()
        state.apply({"schema_version": 1, "type": "overlay.set_size", "payload": {"width": 31.5, "height": 42}})
        self.assertEqual((state.width, state.height), (31, 42))

    def test_set_size_ignores_non_positive_and_non_finite_values(self) -> None:
        state = OverlayState()
        for width, height in ((0, 10), (-1, 10), (10, 0), (float("inf"), 10), (10, float("nan"))):
            state.apply({"schema_version": 1, "type": "overlay.set_size", "payload": {"width": width, "height": height}})
        self.assertIsNone(state.width)
        self.assertIsNone(state.height)

    def tool_event(self, category: object) -> dict:
        payload = {} if category is None else {"category": category}
        return {"schema_version": 1, "type": "tool.started", "display_hint": "generating", "payload": payload}

    def test_tool_category_is_captured(self) -> None:
        state = OverlayState()
        for category in TOOL_CATEGORIES:
            with self.subTest(category=category):
                state.apply(self.tool_event(category))
                self.assertEqual(state.tool_category, category)

    def test_unknown_tool_category_is_dropped(self) -> None:
        state = OverlayState()
        for category in ("future", "", 7, None):
            with self.subTest(category=category):
                state.apply(self.tool_event(category))
                self.assertIsNone(state.tool_category)

    def test_a_semantic_event_without_a_category_clears_the_previous_one(self) -> None:
        """category describes its own message; tool.completed must not leave it stale."""
        state = OverlayState()
        state.apply(self.tool_event("write"))
        self.assertEqual(state.tool_category, "write")
        state.apply({"schema_version": 1, "type": "tool.completed", "display_hint": "generating", "payload": {}})
        self.assertIsNone(state.tool_category)

    def test_geometry_messages_leave_the_category_alone(self) -> None:
        """set_position/set_size carry no display_hint, so they are not semantic events."""
        state = OverlayState()
        state.apply(self.tool_event("execute"))
        state.apply({"schema_version": 1, "type": "overlay.set_position", "payload": {"x": 1, "y": 2}})
        state.apply({"schema_version": 1, "type": "overlay.set_size", "payload": {"width": 10, "height": 20}})
        self.assertEqual(state.tool_category, "execute")


if __name__ == "__main__":
    unittest.main()

