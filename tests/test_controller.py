"""Controller failure/cleanup behavior without installing global input hooks."""

import unittest
from unittest.mock import Mock, patch

from windowglide.app import Application, Session
from windowglide.window_manager import Movement, Target


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.app = Application()
        self.app.hwnd = 123
        self.app.manager = Mock()
        self.app.hooks = Mock()
        self.target = Target(456, 10, 20, "Fixture")
        self.app.session = Session(1, self.target, (100, 100), Movement((0, 0, 500, 400), (100, 100)))
        patcher = patch("windowglide.app.w.KillTimer")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_release_flushes_final_position_before_clearing_session(self):
        self.app._command(("finish", 1, "mouse released", (230, 250)))
        self.app.manager.update_position.assert_called_once()
        self.assertEqual(self.app.manager.update_position.call_args.args[2], (230, 250))
        self.assertIsNone(self.app.session)
        self.app.hooks.reset.assert_called_once_with(1)

    def test_delayed_event_from_old_gesture_cannot_end_new_gesture(self):
        self.app._command(("finish", 0, "mouse released", (230, 250)))
        self.assertEqual(self.app.session.serial, 1)
        self.app.manager.update_position.assert_not_called()

    def test_target_disappearing_on_release_still_cleans_up(self):
        self.app.manager.update_position.side_effect = ValueError("Target closed")
        self.app.finish("release", (230, 250))
        self.assertIsNone(self.app.session)
        self.app.hooks.reset.assert_called_once_with(1)

    def test_failed_update_stops_gesture(self):
        self.app.manager.update_position.side_effect = OSError("Access denied")
        self.app._update((200, 200))
        self.assertIsNone(self.app.session)
        self.app.hooks.reset.assert_called_once_with(1)

    def test_privilege_failure_does_not_start_move(self):
        self.app.session = None
        self.app.manager.inspect.side_effect = PermissionError("Higher-integrity target")
        self.app._command(("armed", 2, 789, (20, 20)))
        self.assertIsNone(self.app.session)
        self.app.manager.begin_move.assert_not_called()
        self.app.hooks.reset.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()

