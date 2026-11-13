"""Recovery policy checks that do not change networking or require root."""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import types
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('home_net_cli', str(Path(__file__).with_name('home-net')))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class RecoveryPolicy(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_healthy_gateway_is_not_restarted(self):
        with patch.object(cli, 'health', return_value={'vpn': True, 'dns': True}), \
             patch.object(cli, 'direct_mode', return_value=False), \
             patch.object(cli, 'systemctl') as control:
            self.assertEqual(cli.recover(), 0)
            control.assert_not_called()

    def test_one_restart_recovers_tunnel(self):
        with patch.object(cli, 'health', side_effect=[{'vpn': False, 'dns': False}, {'vpn': True, 'dns': True}]), \
             patch.object(cli, 'direct_mode', return_value=False), \
             patch.object(cli.socket, 'create_connection', return_value=contextlib.nullcontext()), \
             patch.object(cli, 'systemctl') as control, \
             patch.object(cli, 'enable_direct') as direct:
            self.assertEqual(cli.recover(), 0)
            control.assert_called_once_with('restart', 'xray.service')
            direct.assert_not_called()

    def test_failed_recovery_uses_direct_mode(self):
        with patch.object(cli, 'health', return_value={'vpn': False, 'dns': False}), \
             patch.object(cli, 'direct_mode', return_value=False), \
             patch.object(cli.socket, 'create_connection', return_value=contextlib.nullcontext()), \
             patch.object(cli, 'systemctl') as control, \
             patch.object(cli, 'enable_direct', return_value=0) as direct:
            self.assertEqual(cli.recover(), 0)
            control.assert_called_once_with('restart', 'xray.service')
            direct.assert_called_once_with()

    def test_explicit_vpn_failure_preserves_current_mode(self):
        with patch.object(cli, 'health', return_value={'vpn': False, 'dns': True}), \
             patch.object(cli, 'direct_mode', return_value=True), \
             patch.object(cli.socket, 'create_connection', return_value=contextlib.nullcontext()), \
             patch.object(cli, 'systemctl') as control, \
             patch.object(cli, 'enable_direct') as direct:
            self.assertEqual(cli.recover(require_vpn=True), 2)
            control.assert_called_once_with('restart', 'xray.service')
            direct.assert_not_called()

    def test_failed_dns_on_return_keeps_internet_and_reports_vpn_failure(self):
        with patch.object(cli.sys, 'argv', ['home-net', 'vpn']), \
             patch.object(cli, 'health', return_value={'vpn': True, 'dns': True}), \
             patch.object(cli, 'direct_mode', return_value=True), \
             patch.object(cli, 'dns_test', return_value=False), \
             patch.object(cli, 'systemctl') as control, \
             patch.object(cli, 'enable_direct', return_value=0) as direct:
            self.assertEqual(cli.main(), 2)
            control.assert_called_once_with('disable', '--now', cli.UNIT)
            direct.assert_called_once_with()

    def test_proxy_check_cannot_be_bypassed_by_no_proxy_environment(self):
        with patch.object(cli, 'command', return_value=types.SimpleNamespace(returncode=0)) as run:
            self.assertTrue(cli.proxy_test('https://example.com'))
            args = run.call_args.args[0]
            self.assertEqual(args[args.index('--noproxy')+1], '')


if __name__ == '__main__':
    unittest.main()
