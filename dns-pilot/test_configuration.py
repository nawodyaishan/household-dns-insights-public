"""Static deployment contract tests. No service is started by these tests."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent


class ConfigurationTests(unittest.TestCase):
    def config(self):
        path = ROOT / 'compose.yaml'
        self.assertTrue(path.is_file(), 'Monitoring-only Compose definition is missing')
        result = subprocess.run(['docker', 'compose', '-f', str(path), 'config', '--format', 'json'], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_monitoring_only(self):
        config = self.config()
        service = config['services']['pihole']
        env = service['environment']
        self.assertEqual(env['FTLCONF_dns_upstreams'], '1.1.1.1;1.0.0.1')
        for key in ['dns_blocking_active', 'dns_blockESNI', 'dns_specialDomains_mozillaCanary', 'dns_specialDomains_iCloudPrivateRelay', 'dns_specialDomains_designatedResolver', 'dhcp_active', 'ntp_ipv4_active', 'ntp_ipv6_active', 'ntp_sync_active']:
            self.assertEqual(env['FTLCONF_' + key], 'false', key)
        self.assertEqual(env['FTLCONF_database_maxDBdays'], '7')
        self.assertEqual(env['FTLCONF_dns_queryLogging'], 'true')
        self.assertEqual(env['FTLCONF_misc_privacylevel'], '0')
        self.assertEqual(env['FTLCONF_dns_revServers'], '')
        self.assertEqual(env['TZ'], 'UTC')
        self.assertNotIn('FTLCONF_webserver_api_password', env)
        self.assertTrue(env['WEBPASSWORD_FILE'])

    def test_isolation_and_persistence(self):
        config = self.config()
        service = config['services']['pihole']
        self.assertRegex(service['image'], r'^pihole/pihole:2026\.10\.0(?:@sha256:[a-f0-9]{64})?$')
        self.assertFalse(service.get('privileged', False))
        self.assertNotIn('network_mode', service)
        self.assertFalse(service.get('cap_add'))
        self.assertEqual(service['restart'], 'unless-stopped')
        self.assertTrue(any(v['target'] == '/etc/pihole' and v['type'] == 'volume' for v in service['volumes']))
        self.assertTrue(service['secrets'])
        ports = service['ports']
        self.assertTrue(all(p['host_ip'] == '127.0.0.1' for p in ports))
        self.assertEqual({(int(p['published']), p['target'], p['protocol']) for p in ports}, {(1053, 53, 'udp'), (1053, 53, 'tcp'), (8443, 443, 'tcp')})
        self.assertFalse(any(n.get('enable_ipv6', False) for n in config['networks'].values()))

    def test_lan_override_has_no_wildcard_or_ipv6_bindings(self):
        override = ROOT / 'compose.lan.yaml'
        self.assertTrue(override.is_file(), 'Gated LAN override is missing')
        result = subprocess.run(['docker', 'compose', '-f', str(ROOT / 'compose.yaml'), '-f', str(override), 'config', '--format', 'json'], capture_output=True, text=True, check=True)
        service = json.loads(result.stdout)['services']['pihole']
        self.assertEqual({p['host_ip'] for p in service['ports']}, {'127.0.0.1', '10.10.10.20'})
        lan = {(int(p['published']), p['target'], p['protocol']) for p in service['ports'] if p['host_ip'] == '10.10.10.20'}
        self.assertEqual(lan, {(53, 53, 'tcp'), (53, 53, 'udp'), (8443, 443, 'tcp')})


if __name__ == '__main__':
    unittest.main()
