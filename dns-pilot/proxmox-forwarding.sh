#!/usr/bin/env bash
# starlink-monitoring-proxmox-relay-v1
# Self-contained: copy this file to Proxmox, review, then run as root.
# Touches only its own nftables table and its own systemd service/files.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mode=${1:---install}
owner='starlink-monitoring: scoped DNS relay v1'
helper=/usr/local/libexec/starlink-dns-relay
unit=/etc/systemd/system/starlink-dns-relay.service

policy() {
    cat <<'NFT'
table ip starlink_dns_pilot {
    comment "starlink-monitoring: scoped DNS relay v1"
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        iifname "wlo1" ip saddr 192.168.1.0/24 ip daddr 192.168.1.10 udp dport 53 counter dnat to 10.10.10.20
        iifname "wlo1" ip saddr 192.168.1.0/24 ip daddr 192.168.1.10 tcp dport { 53, 8443 } counter dnat to 10.10.10.20
    }
}
NFT
}

[[ "$mode" != --print ]] || { policy; exit 0; }
case "$mode" in --install|--check|--apply|--status|--rollback) ;; *) echo 'Use --print, --check, --install, --status or --rollback' >&2; exit 2;; esac
[[ $EUID -eq 0 ]] || { echo 'Run on the Proxmox host as root, not on Ubuntu.' >&2; exit 1; }
for cmd in nft systemctl ip sysctl; do command -v "$cmd" >/dev/null; done

owned_table() {
    if nft list table ip starlink_dns_pilot >/dev/null 2>&1; then
        nft list table ip starlink_dns_pilot | grep -Fq "$owner" || {
            echo 'Refusing to replace an unowned table' >&2; exit 1;
        }
        return 0
    fi
    return 1
}

if [[ "$mode" == --status ]]; then
    systemctl --no-pager --full status starlink-dns-relay.service || true
    nft list table ip starlink_dns_pilot
    exit 0
fi

if [[ "$mode" == --rollback ]]; then
    if [[ -e "$unit" ]]; then
        grep -Fq '# starlink-monitoring-proxmox-relay-v1' "$unit" || {
            echo 'Refusing to disable an unowned service' >&2; exit 1;
        }
    fi
    # Verify table ownership before disabling anything.
    exists=no
    if owned_table; then exists=yes; fi
    if [[ -e "$unit" ]]; then systemctl disable --now starlink-dns-relay.service; fi
    if [[ "$exists" == yes ]]; then nft delete table ip starlink_dns_pilot; fi
    echo 'Relay disabled; only the pilot nftables table removed. Existing VM NAT untouched.'
    echo 'Root-owned helper, disabled unit and private backups retained for review.'
    exit 0
fi

# Refuse to apply on Ubuntu or on a changed/unknown host topology.
ip -4 address show dev wlo1 | grep -Fq 'inet 192.168.1.10/24' || {
    echo 'Expected Proxmox Wi-Fi address absent; stop for review.' >&2; exit 1;
}
ip -4 address show dev vmbr0 | grep -Fq 'inet 10.10.10.1/24' || {
    echo 'Expected private VM bridge address absent; stop for review.' >&2; exit 1;
}
[[ $(sysctl -n net.ipv4.ip_forward) == 1 ]] || {
    echo 'IPv4 forwarding is off; no settings changed. Stop for review.' >&2; exit 1;
}

if [[ "$mode" == --check || "$mode" == --apply ]]; then
    umask 077
    batch=$(mktemp)
    trap 'rm -f "$batch"' EXIT
    policy >"$batch"
    # Validate the complete add-only policy before changing anything.
    nft -c -f "$batch"
    if [[ "$mode" == --check ]]; then
        echo 'Scoped nftables transaction syntax/preflight check passed; no changes applied.'
        exit 0
    fi
    # Replace only our own owned table. Brief gap on reinstall; add-only at boot.
    if owned_table; then nft delete table ip starlink_dns_pilot; fi
    nft -f "$batch"
    count=$(nft list table ip starlink_dns_pilot | grep -c 'dnat to 10.10.10.20' || true)
    [[ "$count" == 2 ]] || {
        echo "Relay table has $count forwarding rules, expected 2. Stop for review." >&2; exit 1;
    }
    nft list table ip starlink_dns_pilot
    exit 0
fi

# --install
self=$(readlink -f -- "$0")
bash "$self" --check
for f in "$helper" "$unit"; do
    if [[ -e "$f" ]]; then
        grep -Fq '# starlink-monitoring-proxmox-relay-v1' "$f" || {
            echo "Refusing to overwrite an unowned file: $f" >&2; exit 1;
        }
    fi
done
listeners=$(ss -H -lntu '( sport = :53 or sport = :8443 )')
[[ -z "$listeners" ]] || {
    echo 'Proxmox port 53 or 8443 now has a listener. No forwarding installed; stop for review.' >&2; exit 1;
}
umask 077
mkdir -p /var/lib/starlink-dns-relay
backup=$(mktemp -d /var/lib/starlink-dns-relay/pre-install.XXXXXXXX)
nft list ruleset >"$backup/nft-ruleset.txt"
[[ ! -e "$helper" ]] || cp -p "$helper" "$backup/previous-helper"
[[ ! -e "$unit" ]] || cp -p "$unit" "$backup/previous-unit"
mkdir -p /usr/local/libexec
install -o root -g root -m 0755 "$self" "$helper"
cat >"$unit" <<'UNIT'
# starlink-monitoring-proxmox-relay-v1
[Unit]
Description=Scoped household DNS and HTTPS forwarding to Ubuntu Pi-hole
Wants=network-online.target
After=network-online.target nftables.service pve-firewall.service proxmox-firewall.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/libexec/starlink-dns-relay --apply
ExecReload=/usr/local/libexec/starlink-dns-relay --apply

[Install]
WantedBy=multi-user.target
UNIT
chmod 0644 "$unit"
systemctl daemon-reload
# Reapply even if this owned service was already active during a reinstall.
"$helper" --apply
systemctl enable --now starlink-dns-relay.service
systemctl --no-pager --full status starlink-dns-relay.service
systemctl is-enabled starlink-dns-relay.service
echo "Private pre-change rules backup: $backup"
echo 'Proxmox pilot forwarding installed. Existing VM NAT, bridges and services untouched.'
echo 'No Starlink settings changed. Test from a household client before any DNS cutover.'
echo 'Rollback: bash /usr/local/libexec/starlink-dns-relay --rollback'
