"""Opt-in integration checks against the already running loopback pilot.

Only public test domains and sanitized counts/settings are asserted.
"""
import json
from pathlib import Path
import ssl
import subprocess
import unittest
import urllib.error
import urllib.request


class LocalRuntimeTests(unittest.TestCase):
    def test_loopback_dns_udp_and_tcp(self):
        for transport in ['+notcp', '+tcp']:
            with self.subTest(transport=transport):
                r = subprocess.run(['dig', '@127.0.0.1', '-p', '1053', 'example.com', 'A', transport, '+ignore', '+time=3', '+tries=1'], capture_output=True, text=True, check=True)
                self.assertIn('status: NOERROR', r.stdout)
                self.assertNotIn('ANSWER: 0', r.stdout)

    def test_effective_config(self):
        expected = {
            'dns.blocking.active': 'false', 'database.maxDBdays': '7',
            'database.DBinterval': '60', 'dns.queryLogging': 'true',
            'misc.privacylevel': '0', 'dns.revServers': '[]',
            'dhcp.active': 'false', 'dns.specialDomains.mozillaCanary': 'false',
            'dns.specialDomains.iCloudPrivateRelay': 'false',
            'dns.specialDomains.designatedResolver': 'false',
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                result = subprocess.run(['docker', 'exec', 'starlink-dns-pilot', 'pihole-FTL', '--config', '-q', key], capture_output=True, text=True)
                # FTL's quiet boolean getter uses shell truth semantics:
                # false is printed correctly and returns 1, not a read error.
                self.assertEqual(result.returncode, 1 if value == 'false' else 0)
                self.assertEqual(result.stdout.strip(), value)

    def test_admin_and_disabled_lists(self):
        # Bootstrap loopback only: authenticate to a locally pinned deployment,
        # never use this trust shortcut for remote administration.
        ctx = ssl._create_unverified_context()
        base = 'https://127.0.0.1:8443/api'

        def request(path, body=None, method=None, sid=None):
            headers = {'Content-Type': 'application/json'}
            if sid:
                headers['X-FTL-SID'] = sid
            req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                data = response.read()
                return json.loads(data) if data else {}

        with self.assertRaises(urllib.error.HTTPError) as denied:
            request('/stats/summary')
        self.assertEqual(denied.exception.code, 401)
        denied.exception.close()
        password = (Path.home() / '.config/starlink-dns-pilot/admin-password').read_text()
        session = request('/auth', {'password': password})['session']
        self.assertTrue(session['valid'])
        try:
            self.assertEqual(request('/dns/blocking', sid=session['sid'])['blocking'], 'disabled')
            lists = request('/lists', sid=session['sid'])['lists']
            self.assertFalse(any(item['enabled'] for item in lists))
        finally:
            request('/auth', method='DELETE', sid=session['sid'])

    def test_query_database_has_timestamped_public_test_queries(self):
        sql = "SELECT count(*) FROM queries WHERE domain IN ('example.com','example.org') AND timestamp>0;"
        count = subprocess.check_output(['docker', 'exec', 'starlink-dns-pilot', 'pihole-FTL', 'sqlite3', '/etc/pihole/pihole-FTL.db', sql], text=True).strip()
        self.assertGreater(int(count), 0)


if __name__ == '__main__':
    unittest.main()
