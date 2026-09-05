import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from engram_overlay.backends.tk import TkOverlayHost


class TkDragTests(unittest.TestCase):
    def make_host(self) -> TkOverlayHost:
        host = TkOverlayHost.__new__(TkOverlayHost)
        host.mode = "replace"
        host.root = Mock()
        host._send_pointer = Mock()
        host._send_geometry = Mock()
        host._drag_origin = (340, 260, 100, 80)
        host._drag_sent_ms = None
        return host

    def test_drag_move_reports_window_top_left_instead_of_pointer(self) -> None:
        host = self.make_host()

        host._drag_move(SimpleNamespace(x_root=390, y_root=300))

        host.root.geometry.assert_called_once_with("+150+120")
        host._send_pointer.assert_called_once_with("drag_move", x=150, y=120)

    def test_drag_end_uses_the_same_final_position_for_window_and_host(self) -> None:
        host = self.make_host()

        host._drag_end(SimpleNamespace(x_root=400, y_root=310))

        host.root.geometry.assert_called_once_with("+160+130")
        host._send_pointer.assert_called_once_with("drag_end", x=160, y=130)
        host._send_geometry.assert_not_called()
        self.assertIsNone(host._drag_origin)


if __name__ == "__main__":
    unittest.main()


class DragThrottleTests(unittest.TestCase):
    """Event API v2 caps inbound messages; a drag must stay well under it."""

    def _host(self):
        host = object.__new__(TkOverlayHost)
        host.mode = "replace"
        host.transport = Mock()
        host.root = Mock()
        host.root.winfo_x.return_value = 100
        host.root.winfo_y.return_value = 200
        host._drag_origin = (0, 0, 100, 200)
        host._drag_sent_ms = None
        return host

    def moves(self, host):
        return [c.args[0] for c in host.transport.send.call_args_list
                if c.args[0]["payload"].get("action") == "drag_move"]

    def test_a_burst_of_motion_reports_at_most_once_per_frame(self):
        host = self._host()
        with patch("engram_overlay.backends.tk.time.monotonic") as clock:
            # 20 motion events inside a single frame interval.
            clock.side_effect = [i * 0.0005 for i in range(1, 41)]
            for step in range(20):
                host._drag_move(Mock(x_root=step, y_root=step))
        self.assertEqual(len(self.moves(host)), 1)

    def test_motion_across_frames_keeps_reporting(self):
        host = self._host()
        with patch("engram_overlay.backends.tk.time.monotonic") as clock:
            clock.side_effect = [i * 0.02 for i in range(1, 21)]
            for step in range(6):
                host._drag_move(Mock(x_root=step, y_root=step))
        self.assertEqual(len(self.moves(host)), 6)

    def test_the_window_follows_every_motion_event(self):
        """Only the reports are coalesced; the window must not stutter."""
        host = self._host()
        with patch("engram_overlay.backends.tk.time.monotonic") as clock:
            clock.side_effect = [i * 0.0005 for i in range(1, 41)]
            for step in range(10):
                host._drag_move(Mock(x_root=step, y_root=step))
        self.assertEqual(host.root.geometry.call_count, 10)

    def test_a_new_drag_reports_its_first_motion_immediately(self):
        host = self._host()
        with patch("engram_overlay.backends.tk.time.monotonic") as clock:
            clock.side_effect = [1.0, 1.0005, 5.0, 5.0005]
            host._drag_move(Mock(x_root=1, y_root=1))
            host._drag_move(Mock(x_root=2, y_root=2))
            host._drag_begin(Mock(x_root=3, y_root=3))
            host._drag_move(Mock(x_root=4, y_root=4))
        self.assertEqual(len(self.moves(host)), 2)
