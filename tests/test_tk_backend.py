import queue
import unittest
from unittest.mock import Mock

from engram_overlay.backends.tk import TkOverlayHost
from engram_overlay.state import OverlayState


class TkOverlayHostObserverTests(unittest.TestCase):
    def _host(self, mode="observer"):
        host = object.__new__(TkOverlayHost)
        host.mode = mode
        host.transport = Mock()
        host.root = Mock()
        host.root.winfo_x.return_value = 100
        host.root.winfo_y.return_value = 200
        host.root.winfo_width.return_value = 30
        host.root.winfo_height.return_value = 40
        host._drag_origin = None
        return host

    def test_observer_emits_click_and_initial_geometry(self):
        host = self._host()
        host._send_pointer("left_click")
        host._send_geometry()
        self.assertEqual(host.transport.send.call_count, 2)
        self.assertEqual(host.transport.send.call_args_list[0].args[0]["payload"]["action"], "left_click")
        self.assertEqual(host.transport.send.call_args_list[1].args[0]["type"], "overlay.geometry_changed")

    def test_observer_drag_moves_locally_and_reports_anchor_geometry(self):
        host = self._host()
        host._drag_origin = (10, 20, 100, 200)
        event = Mock(x_root=25, y_root=35)
        host._drag_move(event)
        host._drag_end(event)
        host.root.geometry.assert_called_with("+115+215")
        sent_types = [call.args[0]["type"] for call in host.transport.send.call_args_list]
        self.assertIn("pointer.action", sent_types)
        self.assertIn("overlay.geometry_changed", sent_types)

    def test_position_echo_is_ignored_while_local_drag_is_active(self):
        host = self._host(mode="replace")
        host.state = OverlayState()
        host.view = Mock()
        host.inbox = queue.Queue()
        host._drag_origin = (10, 20, 100, 200)
        host.inbox.put({
            "schema_version": 1,
            "type": "overlay.set_position",
            "payload": {"x": 80, "y": 90},
        })

        host._drain_messages()

        host.root.geometry.assert_not_called()
        self.assertIsNone(host.state.x)
        self.assertIsNone(host.state.y)

    def test_position_ack_is_applied_after_drag_finishes(self):
        host = self._host(mode="replace")
        host.state = OverlayState()
        host.view = Mock()
        host.inbox = queue.Queue()
        host.inbox.put({
            "schema_version": 1,
            "type": "overlay.set_position",
            "payload": {"x": 115, "y": 215},
        })

        host._drain_messages()

        host.root.geometry.assert_called_once_with("+115+215")


if __name__ == "__main__":
    unittest.main()
