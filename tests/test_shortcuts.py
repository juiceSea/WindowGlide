import ctypes as C
import queue
import unittest
from unittest.mock import Mock, patch

from windowglide import win32 as w
from windowglide.config import VisualSettings
from windowglide.hooks import Hooks
from windowglide.shortcuts import ShortcutMatcher, bindings_for, parse_shortcut
from windowglide.window_actions import Minimized, MinimizedStack
from windowglide.window_manager import Target


class ShortcutTests(unittest.TestCase):
    def test_parse_config_rejects_ambiguous_or_duplicate_keys(self):
        for value in ("J", "Shift+J", "Ctrl+Ctrl+J", "Ctrl+Banana", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_shortcut(value)
        with self.assertRaises(ValueError):
            VisualSettings(shortcut_restore="Alt+Ctrl+Win+J")
        with self.assertRaises(ValueError):
            VisualSettings(shortcut_restore="Ctrl+Win+Alt+Q")
        self.assertEqual(bindings_for(VisualSettings(enable_window_shortcuts=False)), {})
        self.assertEqual(parse_shortcut(" ctrl + WIN + alt + f8 ")[1], 0x77)

    def test_exact_chord_once_per_press_and_keyup_consumed_after_modifiers_release(self):
        matcher = ShortcutMatcher(bindings_for(VisualSettings()))
        for vk in (0xA2, 0x5B, 0xA4):
            matcher.feed(vk, False)
        self.assertEqual(matcher.feed(ord("J"), False), (True, "minimize"))
        self.assertEqual(matcher.feed(ord("J"), False), (True, None))
        for vk in (0x5B, 0xA2, 0xA4):
            self.assertEqual(matcher.feed(vk, True), (False, None))
        self.assertEqual(matcher.feed(ord("J"), True), (True, None))
        self.assertFalse(matcher.down)
        matcher.feed(ord("J"), False)
        self.assertEqual(matcher.feed(ord("J"), True), (False, None))

    def test_extra_shift_and_main_key_pressed_before_modifiers_do_not_trigger(self):
        matcher = ShortcutMatcher(bindings_for(VisualSettings()))
        for vk in (0xA2, 0x5B, 0xA4, 0xA0):
            matcher.feed(vk, False)
        self.assertEqual(matcher.feed(ord("J"), False), (False, None))
        matcher.feed(0xA0, True)
        self.assertEqual(matcher.feed(ord("J"), False), (False, None))
        matcher.feed(ord("J"), True)
        self.assertEqual(matcher.feed(ord("J"), False), (True, "minimize"))

    @patch("windowglide.hooks.w.CallNextHookEx", return_value=0)
    @patch("windowglide.hooks.w.GetForegroundWindow", return_value=456)
    @patch("windowglide.hooks.mask_alt_menu", return_value=True)
    def test_touchpad_injected_shortcut_is_handled_in_normal_mode(self, mask, foreground, next_hook):
        hooks = Hooks(123, queue.SimpleQueue(), shortcuts=bindings_for(VisualSettings()))
        hooks.submit = Mock()
        def feed(vk, up=False):
            event = w.KBDLLHOOKSTRUCT(vkCode=vk, flags=0x10, dwExtraInfo=987)
            return hooks._keyboard(0, w.WM_KEYUP if up else w.WM_KEYDOWN, C.addressof(event))
        for vk in (0xA2, 0x5B, 0xA4):
            feed(vk)
        self.assertEqual(feed(ord("K")), 1)
        hooks.submit.assert_called_once_with("shortcut", "restore", 456)
        self.assertEqual(feed(ord("K"), True), 1)
        for vk in (0xA4, 0x5B, 0xA2):
            feed(vk, True)
        self.assertFalse(hooks.shortcut_mask)
        self.assertFalse(hooks.shortcuts.down)

    def test_stack_deduplicates_bounds_size_and_removes_destroyed_windows(self):
        stack = MinimizedStack()
        for hwnd in range(101):
            stack.push(Minimized(Target(hwnd, 1, 2, "fixture"), False))
        self.assertEqual(len(stack.entries), 100)
        self.assertEqual(stack.entries[0].target.hwnd, 1)
        stack.push(Minimized(Target(20, 1, 2, "fixture"), True))
        self.assertEqual(len(stack.entries), 100)
        self.assertTrue(stack.pop().maximized)
        stack.remove(100)
        self.assertEqual(stack.pop().target.hwnd, 99)
