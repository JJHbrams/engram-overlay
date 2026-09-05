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

    def test_replace_size_resizes_view_and_acknowledges_actual_geometry(self):
        host = self._host(mode="replace")
        host.state = OverlayState()
        host.view = Mock()
        host.view.resize.return_value = (120, 160)
        host.canvas = Mock()
        host.inbox = queue.Queue()
        host.inbox.put({
            "schema_version": 1,
            "type": "overlay.set_size",
            "payload": {"width": 300, "height": 400},
        })

        host._drain_messages()

        host.view.resize.assert_called_once_with(300, 400)
        host.root.geometry.assert_called_once_with("120x160")
        host.canvas.config.assert_called_once_with(width=120, height=160)
        sent = [call.args[0] for call in host.transport.send.call_args_list]
        self.assertEqual(sent[-1]["type"], "overlay.geometry_changed")

    def test_menu_dismiss_precedes_right_and_left_pointer_actions(self):
        host = self._host(mode="replace")
        host._right_click(Mock(x_root=12, y_root=13))
        host._drag_end(Mock())
        actions = [call.args[0]["payload"]["action"] for call in host.transport.send.call_args_list]
        self.assertEqual(actions, ["menu_dismiss", "right_click", "menu_dismiss", "left_click"])

class TkOverlayHostPresentationTests(unittest.TestCase):
    """Engram's launcher owns whether the character is on screen.

    The host owns the window, the view owns the transition animation, and the
    visibility ack is sent only once that animation has finished.
    """

    def _host(self, *, start_hidden=True, enter_ms=720, exit_ms=700):
        host = object.__new__(TkOverlayHost)
        host.mode = "replace"
        host.transport = Mock()
        host.root = Mock()
        host.root.after.return_value = "after#1"
        host.root.winfo_x.return_value = 100
        host.root.winfo_y.return_value = 200
        host.root.winfo_width.return_value = 270
        host.root.winfo_height.return_value = 302
        host.view = Mock()
        host.view.begin_enter.return_value = enter_ms
        host.view.begin_exit.return_value = exit_ms
        host.visible = not start_hidden
        host._show_after = None
        host._dismiss_after = None
        host._drag_origin = None
        return host

    def _sent(self, host):
        return [call.args[0] for call in host.transport.send.call_args_list]

    def test_show_acks_only_after_the_arrival_finishes(self):
        host = self._host()
        host._apply_presentation(True)
        host.root.deiconify.assert_called_once()
        host.view.begin_enter.assert_called_once()
        self.assertTrue(host.visible)
        # The documented show order is deiconify -> enter -> geometry -> ack.
        self.assertEqual(self._sent(host), [])
        host.root.after.assert_called_once_with(720, host._finish_show)

        host._finish_show()
        sent = self._sent(host)
        self.assertEqual([m["type"] for m in sent], ["overlay.geometry_changed", "overlay.visibility_changed"])
        self.assertEqual(sent[-1]["payload"], {"visible": True})

    def test_show_without_an_arrival_hook_acks_immediately(self):
        host = self._host()
        host.view = Mock(spec=[])

        host._apply_presentation(True)

        self.assertEqual([message["type"] for message in self._sent(host)],
                         ["overlay.geometry_changed", "overlay.visibility_changed"])

    def test_hide_withdraws_only_after_the_farewell_finishes(self):
        host = self._host(start_hidden=False)
        host._apply_presentation(False)
        host.view.begin_exit.assert_called_once()
        # Still on screen while the animation runs, and nothing acked yet.
        host.root.withdraw.assert_not_called()
        self.assertEqual(self._sent(host), [])
        host.root.after.assert_called_once_with(700, host._finish_dismiss)

        host._finish_dismiss()
        host.root.withdraw.assert_called_once()
        self.assertEqual(self._sent(host)[-1]["payload"], {"visible": False})

    def test_repeated_launcher_clicks_do_not_replay_the_animation(self):
        host = self._host(start_hidden=False)
        host._apply_presentation(True)
        host.view.begin_enter.assert_not_called()
        self.assertEqual(self._sent(host), [])

    def test_hiding_twice_is_a_no_op(self):
        host = self._host()
        host._apply_presentation(False)
        host.view.begin_exit.assert_not_called()
        host.root.withdraw.assert_not_called()

    def test_show_during_a_running_hide_keeps_the_window_up(self):
        host = self._host(start_hidden=False)
        host._apply_presentation(False)
        pending = host._dismiss_after
        self.assertIsNotNone(pending)

        host._apply_presentation(True)
        host.root.after_cancel.assert_called_once_with(pending)
        self.assertIsNone(host._dismiss_after)
        host.root.withdraw.assert_not_called()
        host.view.begin_enter.assert_called_once()
        self.assertTrue(host.visible)

    def test_hide_during_a_running_show_cancels_its_true_ack(self):
        host = self._host()
        host._apply_presentation(True)
        pending = host._show_after
        self.assertIsNotNone(pending)

        host._apply_presentation(False)

        host.root.after_cancel.assert_called_once_with(pending)
        self.assertIsNone(host._show_after)
        self.assertEqual(self._sent(host), [])
        # A stale Tk callback must be harmless even if cancellation races it.
        host._finish_show()
        self.assertEqual(self._sent(host), [])

    def test_redundant_show_during_arrival_does_not_schedule_or_ack_twice(self):
        host = self._host()
        host._apply_presentation(True)
        pending = host._show_after

        host._apply_presentation(True)

        self.assertEqual(host._show_after, pending)
        host.root.after.assert_called_once_with(720, host._finish_show)
        self.assertEqual(self._sent(host), [])

    def test_a_view_without_transition_hooks_still_collapses(self):
        host = self._host(start_hidden=False)
        host.view = Mock(spec=[])  # no begin_enter/begin_exit
        host._apply_presentation(False)
        host.root.withdraw.assert_called_once()
        self.assertEqual(self._sent(host)[-1]["payload"], {"visible": False})

    def test_a_failing_transition_hook_does_not_take_the_renderer_down(self):
        host = self._host(start_hidden=False)
        host.view.begin_exit.side_effect = RuntimeError("artwork missing")
        host._apply_presentation(False)
        host.transport.log.assert_called_once()
        host.root.withdraw.assert_called_once()

    def test_collapsed_window_is_not_redrawn(self):
        host = self._host()
        host.FRAME_MS = 16
        host._tick()
        host.view.tick.assert_not_called()
        host.root.after.assert_called_once_with(16, host._tick)

    def test_visible_window_is_redrawn(self):
        host = self._host(start_hidden=False)
        host.FRAME_MS = 16
        host.root.winfo_pointerxy.return_value = (5, 6)
        host.root.winfo_x.return_value = 1
        host.root.winfo_y.return_value = 2
        host._tick()
        host.view.tick.assert_called_once_with(5, 6, 1, 2)


if __name__ == "__main__":
    unittest.main()
