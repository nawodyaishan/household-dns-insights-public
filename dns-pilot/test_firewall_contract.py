"""Static safety checks; actual root rule checks remain an intervention gate."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent


class FirewallContractTests(unittest.TestCase):
    def test_scoped_non_destructive_guard(self):
        p = ROOT / 'firewall-guard.sh'
        self.assertTrue(p.is_file(), 'Scoped firewall guard is missing')
        text = p.read_text()
        subprocess.run(['bash', '-n', str(p)], check=True)
        for value in ['192.168.1.0/24', '10.10.10.20', 'br-sl-dns', 'DOCKER-USER', 'SLDNS-PRE', 'SLDNS-FWD', 'SLDNS-IN', '--check']:
            self.assertIn(value, text)
        for forbidden in ['iptables -F', 'iptables -P', 'nft flush', 'ufw enable', '100.64.0.0/10', '10.10.10.0/24']:
            self.assertNotIn(forbidden, text)
        self.assertIn('raw PREROUTING', text)
        self.assertIn('RELATED,ESTABLISHED', text)

    def test_installer_does_not_restart_docker(self):
        p = ROOT / 'install-firewall.sh'
        self.assertTrue(p.is_file(), 'Reviewed root installer is missing')
        text = p.read_text()
        subprocess.run(['bash', '-n', str(p)], check=True)
        self.assertIn('ExecStartPre=', text)
        self.assertIn('iptables-save', text)
        self.assertNotIn('systemctl restart', text)
        self.assertNotIn('docker compose', text)


if __name__ == '__main__':
    unittest.main()
