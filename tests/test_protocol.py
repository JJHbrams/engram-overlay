import io
import json
import unittest

from engram_overlay.protocol import (
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


if __name__ == "__main__":
    unittest.main()

