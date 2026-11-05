"""Versioned household network policy manifest: single source of contract truth.

Plan D3 (006): one manifest generates both approved dashboard relay paths, both VM
application boundaries and the Compose binding/verification expectations. The root
helpers installed on Proxmox and the Ubuntu VM stay self-contained shell scripts;
this module renders the exact policy text they embed, and contract tests refuse any
drift between them. Nothing here mutates a host: rendering and evaluation only.

Approved topology (005 r4/B5C deployment, adopted under a separately owned table):

  Household LAN 192.168.1.0/24 -- Proxmox wlo1 192.168.1.10/24
      TCP 8787 -> DNAT 10.10.10.20:8787   (shared HTTP dashboard,  table household_report_relay)
      TCP 8789 -> DNAT 10.10.10.20:8789   (owner TLS dashboard,    table household_owner_relay)
  Proxmox vmbr0 10.10.10.1/24 -- VM ens18 10.10.10.20/24
      shared app bridge br-hr005 (IPv4-only), owner app bridge br-hr006 (IPv4-only)
      guard table household_report_guard restricts both app ports and both bridges

DNS UDP/TCP 53 and admin 8443 forwarding live in the separately owned
starlink_dns_pilot table and are never touched by any household-report policy.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

MANIFEST_REVISION = "006-b3-network-v1"

LAN_SUBNET = "192.168.1.0/24"
PROXMOX_INGRESS = "wlo1"
PROXMOX_ADDRESS = "192.168.1.10"
VM_INGRESS = "ens18"
VM_ADDRESS = "10.10.10.20"
DNS_PORTS = ("53", "8443")

# Each dashboard is its own published port/origin pair with its own owned relay
# table, so one dashboard's rollback never touches the other's forwarding.
@dataclass(frozen=True, slots=True)
class DashboardPath:
    """One approved dashboard publication path."""

    name: str
    version_marker: str
    service: str
    public_port: int
    app_bridge: str
    relay_table: str
    relay_unit: str
    public_url: str
    tls: bool

    def __post_init__(self) -> None:
        import re

        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", self.service) or not re.fullmatch(
            r"[a-zA-Z0-9_.-]{1,64}", self.app_bridge
        ):
            raise ValueError("Dashboard service and bridge names must be simple identifiers")
        if self.public_port != 8787 and self.public_port != 8789:
            raise ValueError("Only the approved ports 8787 and 8789 are known")
        if self.tls and not self.public_url.startswith("https://"):
            raise ValueError("TLS paths must publish an https origin")
        if not self.tls and not self.public_url.startswith("http://"):
            raise ValueError("Plain paths must publish an http origin")


SHARED = DashboardPath(
    name="shared",
    version_marker="household-report: scoped dashboard relay v1",
    service="shared",
    public_port=8787,
    app_bridge="br-hr005",
    relay_table="household_report_relay",
    relay_unit="household-report-relay.service",
    public_url="http://192.168.1.10:8787",
    tls=False,
)
OWNER = DashboardPath(
    name="owner",
    version_marker="household-report: scoped owner dashboard relay v1",
    service="owner",
    public_port=8789,
    app_bridge="br-hr006",
    relay_table="household_owner_relay",
    relay_unit="household-report-owner-relay.service",
    public_url="https://192.168.1.10:8789",
    tls=True,
)
PATHS = (SHARED, OWNER)

GUARD_TABLE = "household_report_guard"
GUARD_VERSION_MARKER = "household-report: scoped VM dashboard guard v1"


def _lan_network() -> ipaddress.IPv4Network:
    return ipaddress.ip_network(LAN_SUBNET)


def bind_validation(address: str) -> ipaddress.IPv4Address:
    """A host bind must be exactly the approved VM/Proxmox IPv4 address."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as error:
        raise ValueError(f"Bind must be one explicit IP address, not {address!r}") from error
    if parsed.version != 4:
        raise ValueError("IPv6 publication is not approved")
    if parsed not in {ipaddress.ip_address(PROXMOX_ADDRESS), ipaddress.ip_address(VM_ADDRESS)}:
        raise ValueError("Bind must be one of the two approved addresses")
    return ipaddress.IPv4Address(parsed)


def validate() -> str:
    """Manifest self-consistency; returns the manifest revision."""
    _lan_network()
    if len({path.public_port for path in PATHS}) != len(PATHS):
        raise ValueError("Each dashboard needs its own published port")
    if len({path.relay_table for path in PATHS}) != len(PATHS):
        raise ValueError("Each relay needs its own owned nft table")
    if len({path.relay_unit for path in PATHS}) != len(PATHS):
        raise ValueError("Each relay needs its own owned systemd unit")
    if len({path.app_bridge for path in PATHS}) != len(PATHS):
        raise ValueError("Each dashboard needs its own dedicated application bridge")
    for path in PATHS:
        if f"{PROXMOX_ADDRESS}:{path.public_port}" not in path.public_url:
            raise ValueError("Public origin must be the relayed Proxmox address and port")
    return MANIFEST_REVISION


def relay_policy(path: DashboardPath) -> str:
    """Proxmox nft policy text for one dashboard path."""
    bind_validation(PROXMOX_ADDRESS)
    return (
        f"table ip {path.relay_table} {{\n"
        f"    comment \"{path.version_marker}\"\n"
        "    chain prerouting {\n"
        "        type nat hook prerouting priority dstnat; policy accept;\n"
        f"        iifname \"{PROXMOX_INGRESS}\" ip saddr {LAN_SUBNET} ip daddr {PROXMOX_ADDRESS}"
        f" tcp dport {path.public_port} counter dnat to {VM_ADDRESS}:{path.public_port}\n"
        "    }\n"
        "}\n"
    )


def guard_policy() -> str:
    """VM nft policy text covering both dashboard ports and both app bridges."""
    bind_validation(VM_ADDRESS)
    prerouting = "\n".join(
        [
            f'        iifname != "{VM_INGRESS}" ip daddr {VM_ADDRESS} tcp dport '
            "{ 8787, 8789 } drop",
            f'        iifname "{VM_INGRESS}" ip saddr != {LAN_SUBNET} ip daddr {VM_ADDRESS}'
            " tcp dport { 8787, 8789 } drop",
        ]
    )
    forward = "\n".join(
        block
        for path in PATHS
        for block in (
            f'        oifname "{path.app_bridge}" iifname != "{VM_INGRESS}" drop',
            f'        oifname "{path.app_bridge}" ip saddr != {LAN_SUBNET} drop',
        )
    )
    return (
        f"table inet {GUARD_TABLE} {{\n"
        f"    comment \"{GUARD_VERSION_MARKER}\"\n"
        "    chain prerouting {\n"
        "        type filter hook prerouting priority raw; policy accept;\n"
        f"{prerouting}\n"
        "    }\n"
        "    chain forward {\n"
        "        type filter hook forward priority -150; policy accept;\n"
        f"{forward}\n"
        "    }\n"
        "}\n"
    )
