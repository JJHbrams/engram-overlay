"""Event API v2 assigns the mode instead of taking it as an argument.

v1 fixed the mode at construction. v2 sends it in engram.welcome and recomputes
it in renderer.assignment whenever selection changes, so a running renderer has
to follow it rather than treat it as configuration.
"""

import unittest
from unittest.mock import Mock

from engram_overlay.backends.tk import TkOverlayHost
from engram_overlay.state import OverlayState


def welcome(mode: str) -> dict:
    return {
        "schema_version": 2,
        "type": "engram.welcome",
        "display_hint": "idle",
        "payload": {"mode": mode, "selected_schema_version": 2, "content_policy": "metadata_only"},
    }


def assignment(mode: str, selected: bool) -> dict:
    return {
        "schema_version": 2,
        "type": "renderer.assignment",
        "display_hint": "idle",
        "payload": {"mode": mode, "selected": selected},
    }


class AssignedModeStateTests(unittest.TestCase):
    def test_mode_is_unknown_until_the_host_says(self) -> None:
        self.assertIsNone(OverlayState().mode)

    def test_the_welcome_carries_the_first_assignment(self) -> None:
        state = OverlayState()
        state.apply(welcome("replace"))
        self.assertEqual(state.mode, "replace")

    def test_a_later_assignment_replaces_it(self) -> None:
        state = OverlayState()
        state.apply(welcome("replace"))
        state.apply(assignment("observer", False))
        self.assertEqual(state.mode, "observer")
        self.assertFalse(state.selected)

    def test_an_unknown_mode_is_ignored(self) -> None:
        state = OverlayState()
        state.apply(welcome("replace"))
        state.apply(assignment("bogus", True))
        self.assertEqual(state.mode, "replace")

    def test_selection_is_only_taken_as_a_boolean(self) -> None:
        state = OverlayState()
        state.apply({"schema_version": 2, "type": "renderer.assignment", "display_hint": "idle",
                     "payload": {"mode": "replace", "selected": "yes"}})
        self.assertIsNone(state.selected)

    def test_semantic_events_do_not_disturb_the_mode(self) -> None:
        state = OverlayState()
        state.apply(welcome("replace"))
        state.apply({"schema_version": 2, "type": "generation.started",
                     "display_hint": "generating", "payload": {}})
        self.assertEqual(state.mode, "replace")


class AssignedModeHostTests(unittest.TestCase):
    def _host(self, mode="observer"):
        host = object.__new__(TkOverlayHost)
        host.mode = mode
        host.transport = Mock()
        host.root = Mock()
        host.root.winfo_x.return_value = 10
        host.root.winfo_y.return_value = 20
        host.root.winfo_width.return_value = 270
        host.root.winfo_height.return_value = 302
        host.visible = True
        host._drag_origin = None
        host._drag_sent_ms = None
        return host

    def test_taking_an_assignment_reports_geometry(self) -> None:
        """The host recomputes anchors on assignment and needs where we are."""
        host = self._host()
        host._apply_mode("replace")
        self.assertEqual(host.mode, "replace")
        sent = [call.args[0]["type"] for call in host.transport.send.call_args_list]
        self.assertEqual(sent, ["overlay.geometry_changed"])

    def test_a_collapsed_renderer_reports_nothing(self) -> None:
        host = self._host()
        host.visible = False
        host._apply_mode("replace")
        self.assertEqual(host.transport.send.call_args_list, [])

    def test_losing_replace_abandons_an_in_flight_drag(self) -> None:
        """Its geometry is no longer ours to move, so the drag cannot finish."""
        host = self._host(mode="replace")
        host._drag_origin = (1, 2, 3, 4)
        host._drag_sent_ms = 123.0
        host._apply_mode("observer")
        self.assertIsNone(host._drag_origin)
        self.assertIsNone(host._drag_sent_ms)


if __name__ == "__main__":
    unittest.main()
