"""Synthetic network-contract evaluator: parsed policy text against packet tuples.

This is the P (packaged synthetic) layer for plan D3: it parses the exact nft text
rendered by network_policy.py (and embedded verbatim in the root helper scripts)
and evaluates a deterministic allow/deny matrix of synthetic packets. No nft,
Docker, socket or packet ever exists here, so a passing matrix is not live
evidence; the L-gate precondition list names what only a privileged live run can
confirm, and it stays explicit and unevaluated.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from network_policy import (
    DashboardPath,
    VM_INGRESS,
    relay_policy,
)

LAN_SUBNET = "192.168.1.0/24"
LAN = ipaddress.ip_network(LAN_SUBNET)


class PolicyContractError(ValueError):
    """Rendered policy text does not parse into the fixed contract."""


@dataclass(frozen=True, slots=True)
class Packet:
    """One synthetic packet tuple (IPv4 unless version is given)."""

    iifname: str
    saddr: str
    daddr: str
    dport: int
    version: int = 4


@dataclass(frozen=True, slots=True)
class RelayRule:
    """The exactly-one scoped prerouting DNAT rule of a relay table."""

    table: str
    iifname: str
    saddr: ipaddress.IPv4Network
    daddr: ipaddress.IPv4Address
    dport: int
    to_addr: ipaddress.IPv4Address
    to_port: int


def parse_relay(policy_text: str) -> RelayRule:
    """Parse one relay table; any deviation from the fixed shape is refused."""
    table_match = re.search(r"^table ip (\S+) \{", policy_text, re.MULTILINE)
    rule_match = re.search(
        r'^\s+iifname "([^"]+)" ip saddr (\S+) ip daddr (\S+) tcp dport (\d+)'
        r" counter dnat to (\S+):(\d+)\s*\n",
        policy_text,
        re.MULTILINE,
    )
    comment = re.search(
        r'^\s+comment "household-report: .*"\n', policy_text, re.MULTILINE
    )
    if not table_match or not rule_match or not comment:
        raise PolicyContractError("Relay policy does not contain the fixed scoped DNAT rule")
    if policy_text.count("dnat to") != 1:
        raise PolicyContractError("A relay table must forward exactly one endpoint")
    for forbidden in ("flush ruleset", "masquerade", "snat", "table inet filter"):
        if forbidden in policy_text:
            raise PolicyContractError("Relay policy contains a forbidden construct")
    iifname, saddr, daddr, dport, to_addr, to_port = rule_match.groups()
    return RelayRule(
        table=table_match.group(1),
        iifname=iifname,
        saddr=ipaddress.ip_network(saddr),
        daddr=ipaddress.ip_address(daddr),
        dport=int(dport),
        to_addr=ipaddress.ip_address(to_addr),
        to_port=int(to_port),
    )


@dataclass(frozen=True, slots=True)
class PreroutingDrop:
    iifname: str
    negated: bool
    daddr: ipaddress.IPv4Address
    ports: tuple[int, ...]
    source_not_lan: bool = False


@dataclass(frozen=True, slots=True)
class ForwardDrop:
    """One forward-chain drop: either ingress-scoped or source-scoped."""

    bridge: str
    iifname: str = ""
    iif_negated: bool = False
    source_not_lan: bool = False


@dataclass(frozen=True, slots=True)
class GuardRules:
    prerouting: tuple[PreroutingDrop, ...]
    forward: tuple[ForwardDrop, ...]

    def bridges(self) -> tuple[str, ...]:
        return sorted({drop.bridge for drop in self.forward})


_IIF = r'iifname (?:!= )?"[^"]+"'
_FORWARD_IIF = re.compile(rf'^\s+oifname "([^"]+)" ({_IIF}) drop\s*$', re.MULTILINE)
_FORWARD_SRC = re.compile(r'^\s+oifname "([^"]+)" ip saddr != (\S+) drop\s*$', re.MULTILINE)


def parse_guard(policy_text: str) -> GuardRules:
    """Parse the guard table; only the known two-prerouting/four-forward shape."""
    if not re.search(r"^table inet household_report_guard \{", policy_text, re.MULTILINE):
        raise PolicyContractError("Guard policy table identity mismatch")
    selectors = re.findall(
        rf'^\s+({_IIF})(?: ip saddr != (\S+))? ip daddr (\S+) tcp dport \{{ ([\d, ]+) \}} drop\s*$',
        policy_text,
        re.MULTILINE,
    )
    forward_iif = _FORWARD_IIF.findall(policy_text)
    forward_src = _FORWARD_SRC.findall(policy_text)
    if len(selectors) != 2 or len(forward_iif) != 2 or len(forward_src) != 2:
        raise PolicyContractError(
            "Guard policy must contain two prerouting drops and two bridge pairs"
        )
    prerouting = tuple(
        PreroutingDrop(
            iifname=iifname.replace("iifname !=", "").replace("iifname", "").strip(' "'),
            negated="!=" in iifname,
            daddr=ipaddress.ip_address(daddr),
            ports=tuple(int(port) for port in ports.split(",")),
            source_not_lan=bool(saddr),
        )
        for iifname, saddr, daddr, ports in selectors
    )
    forward: list[ForwardDrop] = []
    for bridge, iifname in forward_iif:
        forward.append(
            ForwardDrop(
                bridge=bridge,
                iifname=iifname.replace("iifname !=", "").replace("iifname", "").strip(' "'),
                iif_negated="!=" in iifname,
            )
        )
    for bridge, saddr in forward_src:
        if saddr != LAN_SUBNET:
            raise PolicyContractError("Source drops must exclude only the approved LAN")
        forward.append(ForwardDrop(bridge=bridge, source_not_lan=True))
    return GuardRules(prerouting=prerouting, forward=tuple(forward))


def relay_result(rule: RelayRule, packet: Packet) -> Packet | None:
    """DNAT rewrite when every selector matches; otherwise no relay matches."""
    if (
        packet.version == 4
        and packet.iifname == rule.iifname
        and ipaddress.ip_address(packet.saddr) in rule.saddr
        and ipaddress.ip_address(packet.daddr) == rule.daddr
        and packet.dport == rule.dport
    ):
        return Packet(packet.iifname, packet.saddr, str(rule.to_addr), rule.to_port)
    return None


def prerouting_verdict(guard: GuardRules, packet: Packet) -> str | None:
    """'dropped' when a prerouting selector matches the packet."""
    for drop in guard.prerouting:
        if packet.version != 4 or ipaddress.ip_address(packet.daddr) != drop.daddr:
            continue
        if packet.dport not in drop.ports:
            continue
        if (packet.iifname == drop.iifname) != drop.negated:
            if drop.source_not_lan and ipaddress.ip_address(packet.saddr) in LAN:
                continue
            return "dropped"
    return None


def forward_verdict(guard: GuardRules, packet: Packet, oifname: str) -> str | None:
    """'dropped' when a forward selector matches; 'accepted' when none does."""
    for drop in guard.forward:
        if drop.bridge != oifname:
            continue
        if drop.source_not_lan:
            if ipaddress.ip_address(packet.saddr) not in LAN:
                return "dropped"
        elif (packet.iifname == drop.iifname) != drop.iif_negated:
            return "dropped"
    return "accepted" if guard.bridges() else None


def follow_relayed_packet(*, path: DashboardPath, packet: Packet, guard: GuardRules) -> str:
    """The full shared/owner path: relay DNAT, then guard, then bridge verdict.

    Returns one of: 'dnat-absent', 'dropped-prerouting', 'dropped-forward',
    'forwarded'.
    """
    relayed = relay_result(parse_relay(relay_policy(path)), packet)
    if relayed is None:
        return "dnat-absent"
    # After Proxmox DNAT/forward the packet enters the VM on ens18; the saddr and
    # (without masquerade) the addresses are unchanged.
    at_vm = Packet(VM_INGRESS, relayed.saddr, relayed.daddr, relayed.dport)
    if prerouting_verdict(guard, at_vm) == "dropped":
        return "dropped-prerouting"
    if forward_verdict(guard, at_vm, path.app_bridge) == "dropped":
        return "dropped-forward"
    return "forwarded"


def live_preconditions() -> tuple[str, ...]:
    """Explicit named checks only a separately authorized live run can establish."""
    return (
        "conntrack/original destination: at the VM a forwarded LAN source may look "
        "identical whether it targeted the Proxmox relay or the VM directly; the live "
        "run must record whether the VM can distinguish them and keep the documented "
        "residual honest",
        "nft backend/ordering: pve-firewall and proxmox-firewall hook ordering, Docker "
        "iptables backend behaviour and bridge hook priorities",
        "anti-spoofing: LAN devices cannot forge the Proxmox addresses or DNAT themselves",
        "real second-device positive path and every negative path from plan D3",
        "UDP/TCP 53 and admin 8443 unchanged before/after apply/reinstall/rollback/reboot",
    )
