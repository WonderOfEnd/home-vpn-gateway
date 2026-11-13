import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('home_net_watchdog', Path(__file__).with_name('watchdog.py'))
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class WatchdogPolicy(unittest.TestCase):
    def run_watch(self, state, healthy=False, direct=False):
        client = {'direct_mode': Mock(return_value=direct),
                  'health': Mock(return_value={'vpn': healthy, 'dns': True}),
                  'recover': Mock(return_value=0), 'enable_direct': Mock(return_value=0)}
        with patch.object(watch.runpy, 'run_path', return_value=client), \
             patch.object(watch, 'load_state', return_value=state), \
             patch.object(watch, 'save_state'), \
             patch.object(watch.time, 'monotonic', return_value=1000), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(watch.main(), 0)
        return client

    def test_direct_mode_is_never_automatically_disabled(self):
        client = self.run_watch({}, direct=True)
        client['health'].assert_not_called()
        client['recover'].assert_not_called()

    def test_one_failed_sample_does_not_change_network(self):
        client = self.run_watch({})
        client['recover'].assert_not_called()
        client['enable_direct'].assert_not_called()

    def test_second_failed_sample_runs_one_recovery(self):
        client = self.run_watch({'failures': 1})
        client['recover'].assert_called_once_with()
        client['enable_direct'].assert_not_called()

    def test_repeated_failures_do_not_create_a_restart_loop(self):
        client = self.run_watch({'failures': 1, 'last_attempt': 980})
        client['enable_direct'].assert_called_once_with()
        client['recover'].assert_not_called()

    def test_healthy_sample_resets_failure_counter(self):
        state = {'failures': 1}
        client = self.run_watch(state, healthy=True)
        self.assertEqual(state['failures'], 0)
        client['recover'].assert_not_called()
