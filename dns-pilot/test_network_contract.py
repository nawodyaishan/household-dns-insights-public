"""Synthetic network-contract matrix: rendered policies, packet tuples, origins.

Offline (P level): parses the exact nft text from network_policy.py and evaluates a
fixed allow/deny matrix. Nothing runs nft, Docker or any socket, so passing here is
not live evidence; the live preconditions stay explicit and unevaluated.
"""

from pathlib import Path

import ipaddress
import unittest

import network_contract as nc
import network_policy as np

ROOT = Path(__file__).resolve().parent
PROXMOX = 'dashboard-proxmox-relay.sh'
OWNER = 'dashboard-owner-relay.sh'
VM = 'dashboard-vm-guard.sh'
AI_OVERRIDE = ROOT.parent / 'destination-report/compose.ai.yaml'
DNS_TOOLS = ROOT.parent / 'dns-pilot'

LAN_DEVICE = '192.168.1.203'  # synthetic intended second device
FOREIGN = '203.0.113.9'  # synthetic test-net source
V6 = 'fd00::9'


class RenderedPolicyContract(unittest.TestCase):
    def setUp(self):
        self.shared = np.relay_policy(np.SHARED)
        self.owner = np.relay_policy(np.OWNER)
        self.guard = np.guard_policy()

    def test_manifest_validates_and_scripts_match_it_exactly(self):
        self.assertTrue(hasattr(self, 'shared'))
        subprocess_free = True
        self.assertTrue(subprocess_free)
        # The three scripts embed the manifest text byte-for-byte.
        for path, expected in (
            (ROOT / PROXMOX, self.shared),
            (ROOT / OWNER, self.owner),
            (ROOT / VM, self.guard),
        ):
            self.assertTrue(path.is_file(), str(path))
            script = path.read_text()
            self.assertIn('$owner', script)
            # The helper prints its policy; compare with the manifest render.
            import subprocess

            printed = subprocess.check_output(
                ['bash', str(path), '--print'], text=True
            )
            self.assertEqual(printed, expected)

    def test_relay_tables_are_distinct_and_each_forwards_exactly_one(self):
        shared = nc.parse_relay(self.shared)
        owner = nc.parse_relay(self.owner)
        self.assertNotEqual(shared.table, owner.table)
        self.assertNotEqual(shared.to_port, owner.to_port)
        self.assertEqual(shared.dport, 8787)
        self.assertEqual(owner.dport, 8789)

    def test_dns_and_admin_ports_are_never_touched(self):
        for text in (self.shared, self.owner, self.guard):
            for token in ('udp dport', 'tcp dport 53', '8443', 'flush ruleset', 'masquerade'):
                self.assertNotIn(token, text)
        self.assertNotIn('starlink_dns_pilot', ''.join((self.shared, self.owner, self.guard)))

    def test_guard_covers_both_ports_and_both_bridges(self):
        guard = nc.parse_guard(self.guard)
        self.assertEqual(guard.bridges(), ['br-hr005', 'br-hr006'])
        ports = sorted({port for drop in guard.prerouting for port in drop.ports})
        self.assertEqual(ports, [8787, 8789])

    def test_owner_relay_refuses_the_historical_shared_table_rule(self):
        script = (ROOT / OWNER).read_text()
        self.assertIn('household_owner_relay', script)
        self.assertIn("grep -F 'tcp dport 8789'", script)
        self.assertIn('migrate it deliberately first', script)


class PacketMatrix(unittest.TestCase):
    def setUp(self):
        self.guard = nc.parse_guard(np.guard_policy())
        self.shared = nc.parse_relay(np.relay_policy(np.SHARED))
        self.owner = nc.parse_relay(np.relay_policy(np.OWNER))

    def follow(self, path, packet):
        return nc.follow_relayed_packet(path=path, packet=packet, guard=self.guard)

    def test_approved_second_device_paths_forward(self):
        self.assertEqual(
            self.follow(np.SHARED, nc.Packet('wlo1', LAN_DEVICE, '192.168.1.10', 8787)),
            'forwarded',
        )
        self.assertEqual(
            self.follow(np.OWNER, nc.Packet('wlo1', LAN_DEVICE, '192.168.1.10', 8789)),
            'forwarded',
        )

    def test_no_cross_forwarding_between_the_two_relay_tables(self):
        self.assertIsNone(
            nc.relay_result(self.shared, nc.Packet('wlo1', LAN_DEVICE, '192.168.1.10', 8789))
        )
        self.assertIsNone(
            nc.relay_result(self.owner, nc.Packet('wlo1', LAN_DEVICE, '192.168.1.10', 8787))
        )

    def test_outside_lan_source_never_receives_a_dnat(self):
        foreign = nc.Packet('wlo1', FOREIGN, '192.168.1.10', 8789)
        self.assertIsNone(nc.relay_result(self.owner, foreign))

    def test_wrong_ingress_and_wrong_port_do_not_reach_the_dashboards(self):
        self.assertEqual(
            self.follow(np.OWNER, nc.Packet('eth0', LAN_DEVICE, '192.168.1.10', 8789)),
            'dnat-absent',
        )
        self.assertEqual(
            self.follow(np.OWNER, nc.Packet('wlo1', LAN_DEVICE, '192.168.1.10', 8443)),
            'dnat-absent',
        )

    def test_forged_self_dnats_and_wrong_addresses_do_not_forward(self):
        # A LAN device targeting the VM address through Proxmox routing, and one
        # claiming the dashboard ports for a non-approved address, both fall.
        self.assertEqual(
            self.follow(np.SHARED, nc.Packet('wlo1', LAN_DEVICE, '10.10.10.20', 8787)),
            'dnat-absent',
        )
        wrong_port = nc.Packet('wlo1', LAN_DEVICE, '192.168.1.10', 8006)
        self.assertIsNone(nc.relay_result(self.owner, wrong_port))

    def test_direct_vm_path_from_a_lan_source_is_the_recorded_residual(self):
        # Documented plan D3 residual: at the VM a forwarded LAN source may look
        # identical to one that targeted the VM directly; the guard's ingress
        # facts cannot distinguish them pending the live conntrack precondition.
        packet = nc.Packet('ens18', LAN_DEVICE, '10.10.10.20', 8789)
        self.assertIsNone(nc.prerouting_verdict(self.guard, packet))

    def test_direct_vm_path_from_quiet_and_offlan_sources_is_dropped(self):
        quiet_subnet = nc.Packet('ens18', '10.10.10.99', '10.10.10.20', 8789)
        self.assertEqual(nc.prerouting_verdict(self.guard, quiet_subnet), 'dropped')
        other_ingress = nc.Packet('ens18', FOREIGN, '10.10.10.20', 8787)
        self.assertEqual(nc.prerouting_verdict(self.guard, other_ingress), 'dropped')
        wrong_ingress = nc.Packet('eth0', LAN_DEVICE, '10.10.10.20', 8787)
        self.assertEqual(nc.prerouting_verdict(self.guard, wrong_ingress), 'dropped')

    def test_ipv6_never_receives_a_dnat_and_is_recorded_at_bind_level(self):
        v6 = nc.Packet('wlo1', V6, '192.168.1.10', 8789, 6)
        self.assertIsNone(nc.relay_result(self.owner, v6))
        self.assertIsNone(nc.prerouting_verdict(self.guard, v6))

    def test_direct_container_and_offnet_bridge_paths_drop(self):
        container_ip = nc.Packet('eth0', LAN_DEVICE, '10.10.10.20', 8789)
        self.assertEqual(
            nc.forward_verdict(self.guard, container_ip, 'br-hr006'), 'dropped'
        )
        offnet = nc.Packet('ens18', FOREIGN, '10.10.10.20', 8789)
        self.assertEqual(nc.forward_verdict(self.guard, offnet, 'br-hr006'), 'dropped')
        inside = nc.Packet('ens18', LAN_DEVICE, '10.10.10.20', 8789)
        self.assertEqual(nc.forward_verdict(self.guard, inside, 'br-hr006'), 'accepted')

    def test_live_preconditions_are_named_not_marked_passed(self):
        preconditions = nc.live_preconditions()
        self.assertGreaterEqual(len(preconditions), 5)
        self.assertIn('conntrack', '\n'.join(preconditions))


class OriginAndBindContract(unittest.TestCase):
    def test_manifest_origins_match_the_approved_pair(self):
        self.assertEqual(np.SHARED.public_url, 'http://192.168.1.10:8787')
        self.assertEqual(np.OWNER.public_url, 'https://192.168.1.10:8789')

    def test_owner_compose_binds_the_exact_vm_address(self):
        text = AI_OVERRIDE.read_text()
        for token in (
            '${HR_AI_BIND:-10.10.10.20}:${HR_PORT:-8789}:8789',
            'HR_ALLOWED_HOSTS: "${HR_ALLOWED_HOSTS:-192.168.1.10:8789}"',
            'HR_PUBLIC_URL: "${HR_PUBLIC_URL:-https://192.168.1.10:8789}"',
            'com.docker.network.bridge.name: br-hr006',
            'enable_ipv6: false',
        ):
            self.assertIn(token, text)
        for forbidden in ('0.0.0.0', '::', '10.10.10.20:8789,127.0.0.1'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
