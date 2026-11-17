"""Controller with the real D-Bus backend: the session's Inhibit portal and logind."""

import unittest

from sleep_control.backend import DBusBackend
from sleep_control.state import REASON, BackendError, Controller, describe

from . import power
from .qtapp import qt_app

HOST = "kde-session"


class ControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        qt_app()
        self.blocks = power.Blocks()
        self.controller = Controller(DBusBackend())
        self.seen: list[bool] = []
        self.controller.on_change(self.seen.append)
        self.addCleanup(self.controller.allow_sleep)

    def test_starts_allowed(self) -> None:
        self.assertFalse(self.controller.awake)
        self.assertEqual(self.controller.describe(), "Sleep is allowed")

    def test_keep_awake_holds_one_inhibition_until_allowed(self) -> None:
        self.controller.keep_awake()
        self.controller.keep_awake()
        self.assertTrue(self.controller.awake)
        self.assertEqual(self.controller.describe(), "Sleep is blocked (kept awake)")
        self.assertEqual(self.blocks.wait(1), 1)
        self.assertEqual(self.blocks.wait(2, timeout=2), 1, "a second keep_awake took another inhibition")
        self.controller.allow_sleep()
        self.assertFalse(self.controller.awake)
        self.assertEqual(self.blocks.wait(0, timeout=3), 0)
        self.assertEqual(self.seen, [True, False])

    def test_allow_sleep_when_allowed_does_nothing(self) -> None:
        self.controller.allow_sleep()
        self.assertEqual(self.seen, [])

    def test_on_off_on_takes_a_new_request(self) -> None:
        backend = DBusBackend()
        first = backend.inhibit("sleep-control test")
        backend.release(first)
        second = backend.inhibit("sleep-control test")
        backend.release(second)
        self.assertTrue(first.startswith("/org/freedesktop/portal/desktop/request/"))
        self.assertNotEqual(first, second)

    def test_release_right_after_inhibit_leaves_nothing_held(self) -> None:
        # The portal's backend is still setting up the request when the reply comes.
        backend = DBusBackend()
        for _ in range(5):
            backend.release(backend.inhibit(REASON))
        self.assertEqual(self.blocks.wait(1, timeout=7), 0)

    def test_release_of_a_closed_request_fails(self) -> None:
        backend = DBusBackend()
        handle = backend.inhibit("sleep-control test")
        backend.release(handle)
        with self.assertRaises(BackendError) as caught:
            backend.release(handle)
        self.assertIn(handle, str(caught.exception))

    def test_release_of_something_else_fails_at_once(self) -> None:
        with self.assertRaises(BackendError):
            DBusBackend().release("/org/freedesktop/portal/desktop")

    def test_can_suspend_answers(self) -> None:
        self.assertIn(DBusBackend().can_suspend(), ("yes", "no", "na", "challenge", "inhibited",
                                                    "inhibitor-blocked", "challenge-inhibitor-blocked"))

    def test_sleep_now_releases_then_logind_refuses_under_a_block_lock(self) -> None:
        self.controller.keep_awake()
        with power.sleep_blocked():
            with self.assertRaises(BackendError) as caught:
                self.controller.sleep_now()
        self.assertIn(power.DENIED, str(caught.exception))
        self.assertFalse(self.controller.awake)
        self.assertEqual(self.seen, [True, False])
        self.assertEqual(self.blocks.wait(0, timeout=3), 0)

    def test_describe(self) -> None:
        self.assertEqual(describe(True), "Sleep is blocked (kept awake)")
        self.assertEqual(describe(False), "Sleep is allowed")


if __name__ == "__main__":
    unittest.main()
