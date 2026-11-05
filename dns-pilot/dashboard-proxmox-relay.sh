#!/usr/bin/env bash
# household-report-proxmox-relay-v1: independent from the DNS pilot relay.
# Review offline first. Only the owner may run --install on Proxmox.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mode=${1:---print}
owner='household-report: scoped dashboard relay v1'
table=household_report_relay
helper=/usr/local/libexec/household-report-relay
unit=/etc/systemd/system/household-report-relay.service

policy() {
    cat <<'NFT'
table ip household_report_relay {
    comment "household-report: scoped dashboard relay v1"
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        iifname "wlo1" ip saddr 192.168.1.0/24 ip daddr 192.168.1.10 tcp dport 8787 counter dnat to 10.10.10.20:8787
    }
}
NFT
}

[[ "$mode" != --print ]] || { policy; exit 0; }
case "$mode" in --check|--install|--apply|--status|--rollback) ;; *) echo 'Use --print, --check, --install, --status or --rollback' >&2; exit 2;; esac
[[ $EUID -eq 0 ]] || { echo 'Run on Proxmox as root, not Ubuntu.' >&2; exit 1; }
for cmd in nft systemctl ip sysctl ss; do command -v "$cmd" >/dev/null; done

owned_table() {
    if nft list table ip "$table" >/dev/null 2>&1; then
        nft list table ip "$table" | grep -Fq "$owner" || {
            echo 'Refusing to replace an unowned table' >&2; exit 1;
        }
        return 0
    fi
    return 1
}

if [[ "$mode" == --status ]]; then
    systemctl --no-pager status household-report-relay.service || true
    nft list table ip "$table"
    exit 0
fi
if [[ "$mode" == --rollback ]]; then
    if [[ -e "$unit" ]]; then
        grep -Fq '# household-report-proxmox-relay-v1' "$unit" || {
            echo 'Refusing to disable an unowned unit' >&2; exit 1;
        }
    fi
    if owned_table; then
        if [[ -e "$unit" ]]; then systemctl disable --now household-report-relay.service; fi
        nft delete table ip "$table"
    elif [[ -e "$unit" ]]; then
        systemctl disable --now household-report-relay.service
    fi
    echo 'Only the dashboard relay was disabled; DNS pilot relay untouched.'
    exit 0
fi

ip -4 address show dev wlo1 | grep -Fq 'inet 192.168.1.10/24' || {
    echo 'Expected Proxmox Wi-Fi address absent; stop.' >&2; exit 1;
}
ip -4 address show dev vmbr0 | grep -Fq 'inet 10.10.10.1/24' || {
    echo 'Expected VM bridge address absent; stop.' >&2; exit 1;
}
[[ $(sysctl -n net.ipv4.ip_forward) == 1 ]] || {
    echo 'IPv4 forwarding is off; stop without changing it.' >&2; exit 1;
}
if [[ "$mode" == --install || "$mode" == --check ]] && [[ -n $(ss -H -lnt '( sport = :8787 )') ]]; then
    echo 'TCP/8787 has a Proxmox listener; stop.' >&2; exit 1
fi
if [[ "$mode" == --check || "$mode" == --install ]]; then
    # Refuse an unowned table before writing any helper or boot unit.
    owned_table || true
fi
if [[ "$mode" == --install ]]; then
    for file in "$helper" "$unit"; do
        if [[ -e "$file" ]]; then
            grep -Fq '# household-report-proxmox-relay-v1' "$file" || {
                echo 'Refusing to overwrite an unowned file' >&2; exit 1;
            }
        fi
    done
fi

umask 077
batch=$(mktemp)
trap 'rm -f "$batch"' EXIT
policy >"$batch"
if owned_table; then
    # One nft transaction: never leave an unguarded delete/apply interval.
    sed -i '1i delete table ip household_report_relay' "$batch"
fi
nft -c -f "$batch"
if [[ "$mode" == --check ]]; then
    echo 'Dashboard-only relay syntax/topology check passed; no changes made.'
    exit 0
fi

if [[ "$mode" == --install ]]; then
    mkdir -p /var/lib/household-report-relay /usr/local/libexec
    backup=$(mktemp -d /var/lib/household-report-relay/pre-install.XXXXXXXX)
    nft list ruleset >"$backup/nft-ruleset.txt"
    [[ ! -e "$helper" ]] || cp -p "$helper" "$backup/previous-helper"
    [[ ! -e "$unit" ]] || cp -p "$unit" "$backup/previous-unit"
    self=$(readlink -f -- "$0")
    install -o root -g root -m 0755 "$self" "$helper"
    cat >"$unit" <<'UNIT'
# household-report-proxmox-relay-v1
[Unit]
Description=Scoped household dashboard forwarding to Ubuntu VM
Wants=network-online.target
After=network-online.target nftables.service pve-firewall.service proxmox-firewall.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/libexec/household-report-relay --apply
ExecReload=/usr/local/libexec/household-report-relay --apply

[Install]
WantedBy=multi-user.target
UNIT
    chmod 0644 "$unit"
    systemctl daemon-reload
fi

# This is the dashboard-owned table only. No DNS table or global flush.
nft -f "$batch"
count=$(nft list table ip "$table" | grep -c 'dnat to 10.10.10.20:8787' || true)
[[ "$count" == 1 ]] || { echo 'Expected one dashboard rule; stop.' >&2; exit 1; }
if [[ "$mode" == --install ]]; then
    systemctl enable --now household-report-relay.service
    echo "Private dashboard-only pre-change backup: $backup"
fi
echo 'Scoped dashboard relay present; DNS pilot relay unchanged.'
