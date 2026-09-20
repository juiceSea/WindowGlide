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


class DeferredShortcutTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.hooks = Hooks(123, queue.SimpleQueue(), shortcuts=bindings_for(VisualSettings()))
        self.hooks.submit = Mock()
        def identity(hwnd, pointer):
            C.cast(pointer, C.POINTER(w.W.DWORD))[0] = 10
            return 20
        for name, kwargs in (
            ("w.CallNextHookEx", dict(return_value=0)),
            ("w.GetForegroundWindow", dict(return_value=456)),
            ("w.GetWindowThreadProcessId", dict(side_effect=identity)),
            ("w.SetTimer", dict(return_value=9001)),
            ("w.KillTimer", dict(return_value=True)),
            ("mask_alt_menu", dict(return_value=True)),
            ("time.monotonic", dict(side_effect=lambda: self.now)),
        ):
            patcher = patch("windowglide.hooks." + name, **kwargs)
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            if name == "w.GetForegroundWindow":
                self.foreground = mocked

    def feed(self, vk, up=False, injected=True, marker=987):
        event = w.KBDLLHOOKSTRUCT(vkCode=vk, flags=0x10 if injected else 0, dwExtraInfo=marker)
        return self.hooks._keyboard(0, w.WM_KEYUP if up else w.WM_KEYDOWN, C.addressof(event))

    def press(self, letter="J", injected=True):
        for vk in (0xA2, 0x5B, 0xA4):
            self.feed(vk, injected=injected)
        self.assertEqual(self.feed(ord(letter), injected=injected), 1)

    def release(self, letter="J", order=(0xA4, 0x5B, 0xA2)):
        self.assertEqual(self.feed(ord(letter), True), 1)
        for vk in order:
            self.feed(vk, True)

    def test_synthetic_actions_wait_for_all_releases_and_message_loop_settle(self):
        for letter, action in (("J", "minimize"), ("K", "restore"), ("M", "maximize")):
            with self.subTest(letter=letter):
                self.hooks.submit.reset_mock()
                self.press(letter)
                self.hooks._poll_deferred_shortcut()
                self.hooks.submit.assert_not_called()
                self.release(letter)
                self.hooks._poll_deferred_shortcut()
                self.hooks.submit.assert_not_called()
                self.now += 0.06
                self.hooks._poll_deferred_shortcut()
                self.hooks.submit.assert_called_once_with("deferred_shortcut", action, 456, 10, 20)
                self.assertIsNone(self.hooks.shortcut_timer)
                self.assertFalse(self.hooks.shortcuts.down)

    def test_real_keyboard_dispatches_immediately(self):
        self.press(injected=False)
        self.hooks.submit.assert_called_once_with("shortcut", "minimize", 456)
        self.assertIsNone(self.hooks.deferred_shortcut)

    def test_main_key_released_last_and_auto_repeat_do_not_dispatch_early(self):
        self.press()
        for _ in range(3):
            self.feed(ord("J"))
        for vk in (0x5B, 0xA2, 0xA4):
            self.feed(vk, True)
        self.now += 0.3
        self.hooks._poll_deferred_shortcut()
        self.hooks.submit.assert_not_called()
        self.feed(ord("J"), True)
        self.now += 0.06
        self.hooks._poll_deferred_shortcut()
        self.hooks.submit.assert_called_once_with("deferred_shortcut", "minimize", 456, 10, 20)

    def test_missing_release_times_out_without_late_execution(self):
        self.press()
        self.now += 1.6
        self.hooks._poll_deferred_shortcut()
        self.hooks.submit.assert_called_once_with("shortcut_cancelled", "minimize", "input release timed out")
        self.release()
        self.now += 1
        self.hooks._poll_deferred_shortcut()
        self.assertEqual(self.hooks.submit.call_count, 1)

    def test_focus_change_cancels_original_target(self):
        self.press()
        self.release()
        self.foreground.return_value = 789
        self.now += 0.06
        self.hooks._poll_deferred_shortcut()
        self.hooks.submit.assert_called_once_with("shortcut_cancelled", "minimize", "target or foreground changed")

    def test_reused_window_handle_is_rejected(self):
        self.press()
        self.release()
        self.now += 0.06
        with patch("windowglide.hooks.w.GetWindowThreadProcessId", return_value=21):
            self.hooks._poll_deferred_shortcut()
        self.hooks.submit.assert_called_once_with("shortcut_cancelled", "minimize", "target or foreground changed")

    def test_new_input_cancels_but_own_mask_does_not(self):
        self.press()
        self.release()
        self.feed(0xE8, marker=0x57474D4B)
        self.feed(0xE8, True, marker=0x57474D4B)
        self.hooks.submit.assert_not_called()
        self.feed(ord("A"), injected=False)
        self.hooks.submit.assert_called_once_with("shortcut_cancelled", "minimize", "new input before dispatch")

    def test_shutdown_discards_waiting_action(self):
        self.press()
        self.release()
        self.hooks._clear_deferred_shortcut()
        self.now += 1
        self.hooks._poll_deferred_shortcut()
        self.hooks.submit.assert_not_called()
        self.assertIsNone(self.hooks.shortcut_timer)
