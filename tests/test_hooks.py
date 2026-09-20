"""Gesture boundaries: no installation and no synthetic desktop input."""

import ctypes as C
import unittest
from unittest.mock import Mock, patch
import queue

from windowglide import win32 as w
from windowglide.hooks import Hooks


class HookTests(unittest.TestCase):
    def setUp(self):
        self.hooks = Hooks(123, queue.SimpleQueue())
        self.hooks.submit = Mock()
        patcher = patch("windowglide.hooks.mask_alt_menu", return_value=True)
        self.mask = patcher.start()
        self.addCleanup(patcher.stop)
        for name, result in (("candidate_at", 456), ("w.key_down", False), ("w.CallNextHookEx", 0)):
            patcher = patch(f"windowglide.hooks.{name}", return_value=result)
            value = patcher.start()
            self.addCleanup(patcher.stop)
            if name == "w.key_down":
                value.side_effect = lambda vk: vk == w.VK_MENU

    def mouse(self, message, x=300, y=300, injected=False):
        event = w.MSLLHOOKSTRUCT(pt=w.W.POINT(x, y), flags=int(injected))
        return self.hooks._mouse(0, message, C.addressof(event))

    def key(self, vk, up=False):
        event = w.KBDLLHOOKSTRUCT(vkCode=vk)
        return self.hooks._keyboard(0, w.WM_KEYUP if up else w.WM_KEYDOWN, C.addressof(event))

    def test_plain_alt_and_alt_shortcut_pass_through_without_mask(self):
        self.assertEqual(self.key(w.VK_LMENU), 0)
        self.assertEqual(self.key(w.VK_LMENU, True), 0)
        self.key(w.VK_LMENU)
        self.assertEqual(self.key(ord("D")), 0)
        self.key(ord("D"), True)
        self.key(w.VK_LMENU, True)
        self.mask.assert_not_called()

    def test_alt_after_mouse_release_is_masked_once_and_release_passes_through(self):
        self.key(w.VK_LMENU)
        self.mouse(w.WM_LBUTTONDOWN)
        self.mouse(w.WM_MOUSEMOVE, 320, 320)
        self.mouse(w.WM_LBUTTONUP, 320, 320)
        self.assertIsNone(self.hooks.gesture)
        self.assertEqual(self.key(w.VK_LMENU, True), 0)
        self.mask.assert_called_once()
        self.key(w.VK_LMENU)
        self.key(w.VK_LMENU, True)
        self.mask.assert_called_once()  # a fresh plain Alt press remains normal

    def test_alt_repeat_does_not_forget_drag(self):
        self.key(w.VK_LMENU)
        self.mouse(w.WM_LBUTTONDOWN)
        self.mouse(w.WM_MOUSEMOVE, 320, 320)
        self.key(w.VK_LMENU)  # physical key repeat
        self.key(w.VK_LMENU, True)
        self.mask.assert_called_once()

    def test_alt_release_before_mouse_release_stops_drag_and_masks(self):
        self.key(w.VK_LMENU)
        self.mouse(w.WM_LBUTTONDOWN)
        self.mouse(w.WM_MOUSEMOVE, 320, 320)
        self.assertEqual(self.key(w.VK_LMENU, True), 0)
        self.assertIsNone(self.hooks.gesture)
        self.mask.assert_called_once()
        self.assertEqual(self.mouse(w.WM_LBUTTONUP), 1)

    def test_escape_does_not_forget_later_alt_release(self):
        self.key(w.VK_LMENU)
        self.mouse(w.WM_LBUTTONDOWN)
        self.mouse(w.WM_MOUSEMOVE, 320, 320)
        self.key(w.VK_ESCAPE)
        self.key(w.VK_ESCAPE, True)
        self.key(w.VK_LMENU, True)
        self.mask.assert_called_once()

    def test_mask_failure_never_swallows_alt_release(self):
        self.key(w.VK_LMENU)
        self.mouse(w.WM_LBUTTONDOWN)
        self.mouse(w.WM_MOUSEMOVE, 320, 320)
        self.mask.return_value = False
        self.assertEqual(self.key(w.VK_LMENU, True), 0)
        self.assertEqual(self.hooks.submit.call_args.args[0], "mask_failed")

    def test_injected_gestures_are_not_intercepted_in_normal_mode(self):
        self.assertEqual(self.mouse(w.WM_LBUTTONDOWN, injected=True), 0)
        self.hooks.submit.assert_not_called()

    def test_right_drag_starts_resize_and_consumes_paired_release(self):
        self.key(w.VK_LMENU)
        self.assertEqual(self.mouse(w.WM_RBUTTONDOWN), 1)
        self.assertEqual(self.hooks.submit.call_args.args[-1], "resize")
        self.mouse(w.WM_MOUSEMOVE, 320, 320)
        self.assertEqual(self.mouse(w.WM_RBUTTONUP, 320, 320), 1)
        self.assertIsNone(self.hooks.gesture)
        self.key(w.VK_LMENU, True)
        self.mask.assert_called_once()

    def test_consumed_right_click_without_motion_also_masks_alt(self):
        self.key(w.VK_LMENU)
        self.mouse(w.WM_RBUTTONDOWN)
        self.mouse(w.WM_RBUTTONUP)
        self.key(w.VK_LMENU, True)
        self.mask.assert_called_once()

    def test_left_click_without_motion_keeps_plain_alt_behavior(self):
        self.key(w.VK_LMENU)
        self.mouse(w.WM_LBUTTONDOWN)
        self.mouse(w.WM_LBUTTONUP)
        self.key(w.VK_LMENU, True)
        self.mask.assert_not_called()

    def test_second_button_does_not_end_or_change_active_gesture(self):
        self.mouse(w.WM_RBUTTONDOWN)
        self.assertEqual(self.mouse(w.WM_LBUTTONDOWN), 1)
        self.assertEqual(self.mouse(w.WM_LBUTTONUP), 1)
        self.assertEqual(self.hooks.gesture.kind, "resize")
        self.assertEqual(self.mouse(w.WM_RBUTTONUP), 1)
        self.assertIsNone(self.hooks.gesture)

    def test_nonresizable_target_right_click_passes_through(self):
        with patch("windowglide.hooks.candidate_at", return_value=None):
            self.assertEqual(self.mouse(w.WM_RBUTTONDOWN), 0)
            self.assertEqual(self.mouse(w.WM_RBUTTONUP), 0)
        self.hooks.submit.assert_not_called()

    def test_motion_is_coalesced_and_does_not_queue_each_frame(self):
        self.assertEqual(self.mouse(w.WM_LBUTTONDOWN), 1)
        self.mouse(w.WM_MOUSEMOVE, 310, 310)
        for offset in range(20, 200):
            self.mouse(w.WM_MOUSEMOVE, 300 + offset, 300 + offset)
        kinds = [call.args[0] for call in self.hooks.submit.call_args_list]
        self.assertEqual(kinds, ["armed", "start", "motion"])
        self.assertEqual(self.hooks.latest_position[1], (499, 499))

    def test_escape_stops_and_consumes_later_mouse_release(self):
        self.mouse(w.WM_LBUTTONDOWN)
        event = w.KBDLLHOOKSTRUCT(vkCode=w.VK_ESCAPE)
        self.assertEqual(self.hooks._keyboard(0, w.WM_KEYDOWN, C.addressof(event)), 1)
        self.assertIsNone(self.hooks.gesture)
        self.assertEqual(self.mouse(w.WM_LBUTTONUP), 1)
        self.assertFalse(self.hooks.eat_left_up)
        self.assertEqual(self.hooks._keyboard(0, w.WM_KEYUP, C.addressof(event)), 1)


class WinHookTests(unittest.TestCase):
    mouse = HookTests.mouse
    key = HookTests.key

    def setUp(self):
        self.hooks = Hooks(123, queue.SimpleQueue(), drag_modifier="Win")
        self.hooks.submit = Mock()
        self.physical_down = {0x5B}
        for name, result in (("mask_alt_menu", True), ("candidate_at", 456),
                             ("w.key_down", False), ("w.CallNextHookEx", 0)):
            patcher = patch(f"windowglide.hooks.{name}", return_value=result)
            value = patcher.start()
            self.addCleanup(patcher.stop)
            if name == "w.key_down":
                value.side_effect = lambda vk: vk in self.physical_down
            elif name == "mask_alt_menu":
                self.mask = value

    def test_both_win_keys_move_resize_and_all_endings_mask_then_reset(self):
        for vk in (0x5B, 0x5C):
            for down, up in ((w.WM_LBUTTONDOWN, w.WM_LBUTTONUP), (w.WM_RBUTTONDOWN, w.WM_RBUTTONUP)):
                for ending in ("mouse", "modifier", "escape", "click", "reset"):
                    with self.subTest(vk=vk, button=down, ending=ending):
                        self.physical_down = {vk}
                        self.mask.reset_mock()
                        self.hooks.submit.reset_mock()
                        self.assertEqual(self.key(vk), 0)
                        self.assertEqual(self.mouse(down), 1)
                        self.assertEqual(self.hooks.gesture.kind, "move" if down == w.WM_LBUTTONDOWN else "resize")
                        if ending != "click":
                            self.mouse(w.WM_MOUSEMOVE, 330, 330)
                            self.assertTrue(self.hooks.gesture.started)
                        self.key(vk)  # auto-repeat must retain the masking decision
                        if ending == "modifier":
                            self.assertEqual(self.key(vk, True), 0)
                            self.assertIsNone(self.hooks.gesture)
                        elif ending == "escape":
                            self.assertEqual(self.key(w.VK_ESCAPE), 1)
                            self.assertEqual(self.key(w.VK_ESCAPE, True), 1)
                            self.assertIsNone(self.hooks.gesture)
                        elif ending == "reset":
                            self.hooks.gesture = None  # controller cancels a rejected/closed target
                        self.assertEqual(self.mouse(up), 1)
                        if ending != "modifier":
                            self.assertEqual(self.key(vk, True), 0)
                        self.mask.assert_called_once()
                        self.assertIsNone(self.hooks.gesture)
                        self.key(vk)
                        self.key(vk, True)
                        self.mask.assert_called_once()  # next plain Win must remain native

    def test_plain_win_and_win_e_pass_through_without_mask(self):
        for vk in (0x5B, 0x5C):
            for key in (vk, ord("E")):
                self.assertEqual(self.key(key), 0)
            for key in (ord("E"), vk):
                self.assertEqual(self.key(key, True), 0)
            self.key(vk)
            self.key(vk, True)
        self.mask.assert_not_called()

    def test_wrong_or_extra_modifiers_do_not_start_gestures(self):
        for keys in ({w.VK_MENU}, set(), {0x5B, w.VK_MENU}, {0x5B, 0x10}, {0x5C, 0x11}):
            self.physical_down = keys
            for button in (w.WM_LBUTTONDOWN, w.WM_RBUTTONDOWN):
                self.assertEqual(self.mouse(button), 0)
                self.assertIsNone(self.hooks.gesture)
        self.mask.assert_not_called()

    def test_nonselected_alt_release_does_not_end_win_drag(self):
        self.key(0x5B)
        self.mouse(w.WM_LBUTTONDOWN)
        self.key(w.VK_LMENU)
        self.key(w.VK_LMENU, True)
        self.assertIsNotNone(self.hooks.gesture)
        self.mask.assert_not_called()

    def test_both_win_keys_remain_masked_until_both_released(self):
        self.key(0x5B)
        self.mouse(w.WM_LBUTTONDOWN)
        self.mouse(w.WM_LBUTTONUP)
        self.key(0x5C)
        self.key(0x5B, True)
        self.key(0x5C, True)
        self.assertEqual(self.mask.call_count, 2)
        self.key(0x5B)
        self.key(0x5B, True)
        self.assertEqual(self.mask.call_count, 2)

    def test_rejected_target_preserves_native_input(self):
        with patch("windowglide.hooks.candidate_at", return_value=None):
            self.key(0x5B)
            self.assertEqual(self.mouse(w.WM_LBUTTONDOWN), 0)
            self.assertEqual(self.mouse(w.WM_LBUTTONUP), 0)
            self.key(0x5B, True)
        self.mask.assert_not_called()

    def test_failed_mask_passes_real_win_release_and_reports_failure(self):
        self.key(0x5B)
        self.mouse(w.WM_RBUTTONDOWN)
        self.mouse(w.WM_RBUTTONUP)
        self.mask.return_value = False
        self.assertEqual(self.key(0x5B, True), 0)
        self.assertEqual(self.hooks.submit.call_args.args[0], "mask_failed")
        self.assertFalse(self.hooks.modifier_keys_down)
        self.assertFalse(self.hooks.mask_modifier_on_release)


if __name__ == "__main__":
    unittest.main()
