"""Notification delivery must neither lose queued events nor depend on VPN health."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('home_net_notify', Path(__file__).with_name('notify.py'))
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)


class Notifications(unittest.TestCase):
    def test_initial_observation_does_not_claim_a_switch(self):
        state = notify.observe({}, 'vpn', 'first')
        self.assertEqual(state, {'mode': 'vpn', 'queue': []})

    def test_only_changes_enqueue_and_keep_order(self):
        state = notify.observe({}, 'vpn', 'initial')
        notify.observe(state, 'direct', 'down')
        notify.observe(state, 'direct', 'still down')
        notify.observe(state, 'vpn', 'up')
        self.assertEqual([(x['mode'], x['time']) for x in state['queue']],
                         [('direct', 'down'), ('vpn', 'up')])

    def test_transient_rule_switching_does_not_create_false_events(self):
        state = notify.observe({'mode': 'vpn'}, None, 'switching')
        self.assertEqual(state, {'mode': 'vpn', 'queue': []})

    def test_failed_delivery_survives_another_process_and_is_retried(self):
        previous_umask = notify.os.umask(0o077)
        self.addCleanup(notify.os.umask, previous_umask)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / 'config.json'
            config.write_text(json.dumps({'topic': 'random_test_topic_with_enough_characters'}))
            with patch.object(notify, 'CONFIG', config), patch.object(notify, 'STATE_DIR', base / 'state'), \
                 patch.object(notify, 'mode', return_value='vpn'), \
                 patch.object(notify, 'publish', side_effect=[False, True]) as send, \
                 contextlib.redirect_stdout(io.StringIO()):
                notify.main(test=True)
                pending = json.loads((base / 'state/state.json').read_text())
                self.assertEqual(len(pending['queue']), 1)
                notify.main()
                delivered = json.loads((base / 'state/state.json').read_text())
                self.assertEqual(delivered['queue'], [])
                self.assertEqual(send.call_args_list[0].args, send.call_args_list[1].args)

    def test_sender_uses_direct_public_dns_and_never_a_proxy(self):
        responses = [types.SimpleNamespace(returncode=0, stdout='ntfy.example.\n159.203.148.75\n'),
                     types.SimpleNamespace(returncode=0, stdout='200')]
        with patch.object(notify.subprocess, 'run', side_effect=responses) as run:
            self.assertTrue(notify.publish('random_test_topic_with_enough_characters',
                                          {'mode': 'direct', 'time': 'then', 'test': False}))
            self.assertIn('@1.1.1.1', run.call_args_list[0].args[0])
            args = run.call_args_list[1].args[0]
            self.assertEqual(args[args.index('--noproxy') + 1], '*')
            self.assertEqual(args[args.index('--resolve') + 1], 'ntfy.sh:443:159.203.148.75')
            self.assertNotIn('--insecure', args)
            self.assertNotIn('random_test_topic_with_enough_characters', ' '.join(args))
            self.assertIn('topic', json.loads(run.call_args_list[1].kwargs['input']))

    def test_dns_error_does_not_fall_back_to_tunnel_dns(self):
        with patch.object(notify.subprocess, 'run', return_value=types.SimpleNamespace(returncode=9, stdout='')) as run:
            self.assertFalse(notify.publish('random_test_topic_with_enough_characters',
                                           {'mode': 'vpn', 'time': 'then', 'test': False}))
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
