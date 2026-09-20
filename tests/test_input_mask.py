import unittest
from unittest.mock import patch

from windowglide.input_mask import mask_alt_menu


class MenuMaskTests(unittest.TestCase):
    @patch("windowglide.input_mask.send_input", return_value=2)
    def test_mask_is_a_paired_tagged_non_alt_key(self, send):
        self.assertTrue(mask_alt_menu())
        count, events, size = send.call_args.args
        self.assertEqual(count, 2)
        self.assertEqual([event.ki.wVk for event in events], [0xE8, 0xE8])
        self.assertEqual([event.ki.dwFlags for event in events], [0, 2])
        self.assertTrue(all(event.ki.dwExtraInfo for event in events))

    @patch("windowglide.input_mask.send_input", side_effect=[1, 1])
    def test_partial_injection_attempts_to_release_mask_key(self, send):
        self.assertFalse(mask_alt_menu())
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args.args[0], 1)

    @patch("windowglide.input_mask.send_input", return_value=0)
    def test_injection_failure_is_reported_without_retrying_alt(self, send):
        self.assertFalse(mask_alt_menu())
        send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
