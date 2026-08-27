import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from engram_overlay.backends.tk import TkOverlayHost


class TkDragTests(unittest.TestCase):
    def make_host(self) -> TkOverlayHost:
        host = TkOverlayHost.__new__(TkOverlayHost)
        host.mode = "replace"
        host.root = Mock()
        host._send_pointer = Mock()
        host._send_geometry = Mock()
        host._drag_origin = (340, 260, 100, 80)
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
