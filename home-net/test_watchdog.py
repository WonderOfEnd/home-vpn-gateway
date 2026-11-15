"""Exercise both directions and interrupted sequences without changing networking."""
import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('home_net_watchdog', Path(__file__).with_name('watchdog.py'))
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class WatchdogPolicy(unittest.TestCase):
    def setUp(self):
        self.mode = False
        self.state = {}
        self.now = 1000
        self.client = {'direct_mode': Mock(side_effect=lambda: self.mode),
                       'health': Mock(), 'recover': Mock(),
                       'enable_direct': Mock(side_effect=self.enable_direct),
                       'restore_vpn': Mock(side_effect=self.restore_vpn)}

    def enable_direct(self):
        self.mode = True
        return 0

    def restore_vpn(self):
        self.mode = False
        return 0

    def save_state(self, state):
        self.state = copy.deepcopy(state)

    def sample(self, vpn=False, dns=True, seconds=30):
        self.now += seconds
        self.client['health'].return_value = {'vpn': vpn, 'dns': dns}
        with patch.object(watch.runpy, 'run_path', return_value=self.client), \
             patch.object(watch, 'load_state', side_effect=lambda: copy.deepcopy(self.state)), \
             patch.object(watch, 'save_state', side_effect=self.save_state), \
             patch.object(watch.time, 'monotonic', side_effect=lambda: self.now), \
             contextlib.redirect_stdout(io.StringIO()):
            return watch.main()

    def test_four_failed_checks_switch_to_direct_without_restarts(self):
        for count in range(1, 4):
            self.assertEqual(self.sample(), 0)
            self.assertEqual(self.state['failures'], count)
            self.client['enable_direct'].assert_not_called()
        self.assertEqual(self.sample(), 0)
        self.client['enable_direct'].assert_called_once_with()
        self.client['recover'].assert_not_called()
        self.assertTrue(self.mode)
        self.assertEqual(self.state['failures'], 0)

    def test_four_successful_checks_in_direct_mode_restore_vpn(self):
        self.mode = True
        for count in range(1, 4):
            self.assertEqual(self.sample(vpn=True), 0)
            self.assertEqual(self.state['successes'], count)
            self.client['restore_vpn'].assert_not_called()
        self.assertEqual(self.sample(vpn=True), 0)
        self.client['restore_vpn'].assert_called_once_with()
        self.assertFalse(self.mode)
        self.assertEqual(self.state['successes'], 0)

    def test_success_interrupts_failure_sequence(self):
        for _ in range(3):
            self.sample()
        self.sample(vpn=True)
        self.assertEqual(self.state['failures'], 0)
        self.sample()
        self.assertEqual(self.state['failures'], 1)
        self.client['enable_direct'].assert_not_called()

    def test_failure_interrupts_recovery_sequence(self):
        self.mode = True
        for _ in range(3):
            self.sample(vpn=True)
        self.sample()
        self.assertEqual(self.state['successes'], 0)
        self.sample(vpn=True)
        self.assertEqual(self.state['successes'], 1)
        self.client['restore_vpn'].assert_not_called()

    def test_checks_continue_through_multiple_round_trips(self):
        for _ in range(2):
            for _ in range(4):
                self.sample()
            self.assertTrue(self.mode)
            for _ in range(4):
                self.sample(vpn=True)
            self.assertFalse(self.mode)
        self.assertEqual(self.client['enable_direct'].call_count, 2)
        self.assertEqual(self.client['restore_vpn'].call_count, 2)

    def test_failed_direct_dns_does_not_prevent_return_to_healthy_vpn(self):
        self.mode = True
        for _ in range(4):
            self.sample(vpn=True, dns=False)
        self.client['restore_vpn'].assert_called_once_with()

    def test_failed_normal_dns_also_triggers_direct_mode(self):
        for _ in range(4):
            self.sample(vpn=True, dns=False)
        self.assertTrue(self.mode)

    def test_dns_rollback_starts_a_new_recovery_sequence(self):
        self.mode = True
        self.client['restore_vpn'].side_effect = None  # Client rolled back to direct.
        self.client['restore_vpn'].return_value = 0
        for _ in range(4):
            self.sample(vpn=True)
        self.assertTrue(self.mode)
        self.assertEqual(self.state['successes'], 0)
        self.sample(vpn=True)
        self.assertEqual(self.state['successes'], 1)
        self.client['restore_vpn'].assert_called_once_with()

    def test_manual_mode_change_resets_previous_samples(self):
        for _ in range(3):
            self.sample()
        self.mode = True
        self.sample(vpn=True)
        self.assertEqual(self.state['failures'], 0)
        self.assertEqual(self.state['successes'], 1)
        self.client['restore_vpn'].assert_not_called()

    def test_manual_mode_change_during_probe_discards_result(self):
        for _ in range(3):
            self.sample()
        def health():
            self.mode = True
            return {'vpn': False, 'dns': True}
        self.client['health'].side_effect = health
        self.sample()
        self.assertEqual(self.state['mode'], 'direct')
        self.assertEqual(self.state['failures'], 0)
        self.client['enable_direct'].assert_not_called()

    def test_long_pause_discards_old_checks(self):
        self.mode = True
        for _ in range(3):
            self.sample(vpn=True)
        self.sample(vpn=True, seconds=90)
        self.assertEqual(self.state['successes'], 1)
        self.client['restore_vpn'].assert_not_called()

    def test_old_or_malformed_state_starts_a_new_sequence(self):
        for state in [{'failures': 3, 'last_attempt': 1000},
                      {'version': 2, 'mode': 'vpn', 'last_check': 1000,
                       'failures': '3', 'successes': 0}]:
            with self.subTest(state=state):
                self.state = state
                self.sample()
                self.assertEqual(self.state['failures'], 1)
                self.client['enable_direct'].assert_not_called()
