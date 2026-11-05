"""Offline household dashboard relay/guard contract; no root apply."""

from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROXMOX = ROOT / 'dns-pilot/dashboard-proxmox-relay.sh'
VM = ROOT / 'dns-pilot/dashboard-vm-guard.sh'
OWNER = ROOT / 'dns-pilot/dashboard-owner-relay.sh'
OVERRIDE = ROOT / 'destination-report/compose.lan.yaml'
AI_OVERRIDE = ROOT / 'destination-report/compose.ai.yaml'


class DashboardRelayTests(unittest.TestCase):
    def policy(self, script):
        self.assertTrue(script.is_file(), str(script))
        subprocess.run(['bash', '-n', str(script)], check=True)
        return subprocess.check_output(['bash', str(script), '--print'], text=True)

    def test_proxmox_only_forwards_one_household_tcp_port(self):
        policy = self.policy(PROXMOX)
        for token in ('table ip household_report_relay', 'iifname "wlo1"',
                      'ip saddr 192.168.1.0/24', 'ip daddr 192.168.1.10',
                      'tcp dport 8787', 'dnat to 10.10.10.20:8787'):
            self.assertIn(token, policy)
        self.assertEqual(policy.count('dnat to'), 1)
        for forbidden in ('starlink_dns_pilot', 'udp dport', 'tcp dport 53',
                          '8443', '8006', 'flush ruleset', 'masquerade'):
            self.assertNotIn(forbidden, policy)
        script = PROXMOX.read_text()
        for token in ('--rollback', 'nft -c -f', 'nft list ruleset',
                      'Refusing to replace an unowned table', 'systemctl enable --now',
                      'ss -H -lnt', 'ip -4 address show dev wlo1'):
            self.assertIn(token, script)
        self.assertIn("sed -i '1i delete table ip household_report_relay'", script)
        self.assertNotIn('nft delete table ip "$table"; fi\nnft -f', script)

    def test_vm_guard_blocks_direct_and_container_bypass(self):
        policy = self.policy(VM)
        for token in ('table inet household_report_guard',
                      'type filter hook prerouting priority raw',
                      'iifname != "ens18" ip daddr 10.10.10.20 tcp dport { 8787, 8789 } drop',
                      'iifname "ens18" ip saddr != 192.168.1.0/24 ip daddr 10.10.10.20 '
                      'tcp dport { 8787, 8789 } drop',
                      'type filter hook forward priority -150',
                      'oifname "br-hr005" iifname != "ens18" drop',
                      'oifname "br-hr005" ip saddr != 192.168.1.0/24 drop',
                      'oifname "br-hr006" iifname != "ens18" drop',
                      'oifname "br-hr006" ip saddr != 192.168.1.0/24 drop'):
            self.assertIn(token, policy)
        for forbidden in ('starlink_dns_pilot', 'SLDNS-', 'udp dport',
                          'flush ruleset', '53,8443', 'policy drop'):
            self.assertNotIn(forbidden, policy)
        text = VM.read_text()
        for token in ('ExecStartPre=', '--apply', '--rollback', 'nft -c -f',
                      'nft list ruleset', 'Refusing to replace an unowned table',
                      'ip -4 address show dev ens18', 'ip link show dev "$link"',
                      'docker_owns_bridge', 'not owned by this installation',
                      'docker ps --format',
                      'grep -Eq \'(^|[^0-9])(8787|8789)->\'',
                      '[[ "$count" == 6 ]]',
                      'Refusing to remove the guard while an app is published'):
            self.assertIn(token, text)
        self.assertIn("sed -i '1i delete table inet household_report_guard'", text)
        self.assertNotIn('nft delete table inet "$table"; fi\nnft -f', text)
        # The reserved bridge may already exist when it is our own Docker
        # network (the shared dashboard runs on br-hr005 in a live deployment);
        # an unrelated interface holding the name is still refused.
        self.assertNotIn('The reserved application bridge already exists', text)

    def test_owner_relay_is_independently_owned_and_scoped(self):
        policy = self.policy(OWNER)
        for token in ('table ip household_owner_relay',
                      'household-report: scoped owner dashboard relay v1',
                      'iifname "wlo1"', 'ip saddr 192.168.1.0/24',
                      'ip daddr 192.168.1.10', 'tcp dport 8789',
                      'dnat to 10.10.10.20:8789'):
            self.assertIn(token, policy)
        self.assertEqual(policy.count('dnat to'), 1)
        for forbidden in ('household_report_relay', 'starlink_dns_pilot',
                          'udp dport', 'tcp dport 53', '8443', '8006',
                          'flush ruleset', 'masquerade', '8787'):
            self.assertNotIn(forbidden, policy)
        script = OWNER.read_text()
        for token in ('household_owner_relay', '--rollback', 'nft -c -f',
                      'nft list ruleset', 'Refusing to replace an unowned table',
                      'systemctl enable --now household-report-owner-relay.service',
                      "ss -H -lnt '( sport = :8789 )'",
                      "grep -F 'tcp dport 8789'",
                      '# household-report-owner-relay-v1'):
            self.assertIn(token, script)
        self.assertIn("sed -i '1i delete table ip household_owner_relay'", script)
        self.assertNotIn('household-report-proxmox-relay-v1', script)
        self.assertNotIn('nft delete table ip "$table"; fi\nnft -f', script)

    def test_campaign_profile_uses_a_dedicated_named_bridge(self):
        text = OVERRIDE.read_text()
        self.assertIn('com.docker.network.bridge.name: br-hr005', text)
        self.assertIn('enable_ipv6: false', text)
        self.assertIn('networks:', text)
        self.assertIn('- campaign', text)

if __name__ == '__main__':
    unittest.main()
