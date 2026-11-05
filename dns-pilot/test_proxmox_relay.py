"""Offline policy checks; no host network or firewall changes."""
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parent / 'proxmox-forwarding.sh'


class ProxmoxRelayTests(unittest.TestCase):
    def test_policy_is_scoped(self):
        self.assertTrue(SCRIPT.is_file(), 'Proxmox relay installer is missing')
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)
        text = subprocess.check_output(['bash', str(SCRIPT), '--print'], text=True)
        for token in ['table ip starlink_dns_pilot', 'iifname "wlo1"', 'ip saddr 192.168.1.0/24', 'ip daddr 192.168.1.10', 'udp dport 53', 'tcp dport { 53, 8443 }', 'dnat to 10.10.10.20', 'counter']:
            self.assertIn(token, text)
        self.assertEqual(text.count('dnat to'), 2)
        for forbidden in ['flush ruleset', 'masquerade', 'snat', '8006', 'dport 22', 'table inet filter']:
            self.assertNotIn(forbidden, text)

    def test_safe_install_and_rollback_contract(self):
        self.assertTrue(SCRIPT.is_file(), 'Proxmox relay installer is missing')
        text = SCRIPT.read_text()
        for token in ['--rollback', 'nft -c -f', 'nft -f', 'nft list ruleset', 'systemctl enable --now starlink-dns-relay.service', 'After=network-online.target nftables.service pve-firewall.service proxmox-firewall.service', 'nft delete table ip starlink_dns_pilot', 'Refusing to replace an unowned table', 'expected 2']:
            self.assertIn(token, text)
        for forbidden in ['flush ruleset', 'sysctl -w', 'systemctl restart networking', 'systemctl restart docker', 'iptables -F', 'systemctl restart pve-firewall']:
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
