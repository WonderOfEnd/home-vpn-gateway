import base64
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install


def link(address='1.1.1.1', **options):
    # Parser fixtures only. No live endpoints or credentials are used.
    fields = {'security': 'reality', 'type': 'tcp', 'sni': 'www.example.org',
              'pbk': base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('='),
              'sid': 'ab12', 'spx': '/example path', **options}
    return f'vless://{uuid.uuid4()}@{address}:7443?{urlencode(fields)}#Home'


class InstallerTests(unittest.TestCase):
    def test_flow_port_and_reality_settings_reach_both_outbounds(self):
        for flow in ('', 'xtls-rprx-vision'):
            with self.subTest(flow=flow):
                profile = install.parse_link(link(flow=flow, type='raw', **{'support-x25519mlkem768': 'true'}))
                config = install.xray_config(profile, '192.168.48.15')
                listeners = {item['tag']: item['listen'] for item in config['inbounds']}
                self.assertEqual(listeners['redirect-in'], '192.168.48.15')
                self.assertEqual(listeners['tproxy-udp-in'], '127.0.0.1')
                proxies = [out for out in config['outbounds'] if out['protocol'] == 'vless']
                self.assertEqual([out['tag'] for out in proxies], ['proxy', 'proxy-voice'])
                for out in proxies:
                    server, = out['settings']['vnext']
                    self.assertEqual((server['address'], server['port']), (profile['vps'], 7443))
                    self.assertEqual(server['users'][0]['id'], profile['uuid'])
                    self.assertEqual(server['users'][0].get('flow', ''), flow)
                    self.assertEqual(out['streamSettings']['realitySettings']['spiderX'], '/example path')
                self.assertEqual(proxies[0].get('mux', {}).get('enabled', False), not flow)
                self.assertNotIn('<VPS_IP>', json.dumps(config))

    def test_unsupported_links_fail_before_system_changes(self):
        for options in ({'security': 'tls'}, {'type': 'ws'}, {'flow': 'wrong'}, {'sid': 'abc'},
                        {'pbk': 'short'}, {'sni': 'bad/name'}, {'encryption': 'other'},
                        {'headerType': 'http'}, {'address': '127.0.0.1'}, {'address': '[::1]'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                install.parse_link(link(**options))

    def test_named_server_must_resolve_to_one_public_ipv4(self):
        def lookup(ip):
            return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (ip, 7443))
        with patch.object(socket, 'getaddrinfo', return_value=[lookup('1.1.1.1')]):
            self.assertEqual(install.parse_link(link('vpn.example.org'))['vps'], '1.1.1.1')
        for results in ([], [lookup('10.0.0.1')], [lookup('1.1.1.1'), lookup('1.0.0.1')]):
            with patch.object(socket, 'getaddrinfo', return_value=results), self.assertRaises(ValueError):
                install.parse_link(link('vpn.example.org'))

    def test_detects_private_lan_and_rejects_public_server_or_ambiguous_routes(self):
        default = [{'dev': 'ens18', 'gateway': '192.168.48.1'}]
        addrs = [{'addr_info': [{'scope': 'global', 'local': '192.168.48.15', 'prefixlen': 24}]}]
        with patch.object(install, 'capture', side_effect=map(json.dumps, [default, addrs])):
            net = install.network()
        self.assertEqual(net, {'iface': 'ens18', 'ip': '192.168.48.15', 'cidr': '192.168.48.0/24', 'router': '192.168.48.1'})
        for routes, addresses in (([], []), (default * 2, addrs),
                                  ([{'dev': 'eth0', 'gateway': '1.1.1.1'}],
                                   [{'addr_info': [{'scope': 'global', 'local': '1.1.1.2', 'prefixlen': 24}]}])):
            with patch.object(install, 'capture', side_effect=map(json.dumps, [routes, addresses])), self.assertRaises(ValueError):
                install.network()

    def test_staged_tools_and_dns_follow_selected_network(self):
        net = {'iface': 'ens18', 'ip': '192.168.48.15', 'cidr': '192.168.48.0/24'}
        profile = install.parse_link(link())
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            install.stage_files(stage, net, profile)
            config = stage / 'usr/local/etc/xray/config.json'
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertTrue((stage / 'usr/local/bin/home-net').stat().st_mode & 0o111)
            self.assertIn('HOME_GATEWAY_LAN_IFACE=ens18', (stage / 'etc/default/home-gateway-direct').read_text())
            self.assertIn('HOME_GATEWAY_LAN_CIDR=192.168.48.0/24', (stage / 'etc/default/home-gateway-direct').read_text())
            self.assertIn('%d/gateway.json', (stage / install.UNIT_DIR / 'xray.service.d/20-gateway.conf').read_text())
        env = install.compose_config(net)['services']['pihole']['environment']
        self.assertEqual(env['FTLCONF_dns_upstreams'], '127.0.0.1#5353')
        self.assertEqual(env['FTLCONF_dns_interface'], 'ens18')
        self.assertEqual(env['FTLCONF_webserver_port'], '192.168.48.15:8080')


if __name__ == '__main__':
    unittest.main()
