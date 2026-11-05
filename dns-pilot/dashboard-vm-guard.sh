#!/usr/bin/env bash
# household-report-vm-guard-v1: independent from the Pi-hole firewall guard.
# Review offline first. Only the owner may run --install on the Ubuntu VM.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mode=${1:---print}
owner='household-report: scoped VM dashboard guard v1'
table=household_report_guard
helper=/usr/local/libexec/household-report-vm-guard
dropin=/etc/systemd/system/docker.service.d/household-report-guard.conf

policy() {
    cat <<'NFT'
table inet household_report_guard {
    comment "household-report: scoped VM dashboard guard v1"
    chain prerouting {
        type filter hook prerouting priority raw; policy accept;
        iifname != "ens18" ip daddr 10.10.10.20 tcp dport { 8787, 8789 } drop
        iifname "ens18" ip saddr != 192.168.1.0/24 ip daddr 10.10.10.20 tcp dport { 8787, 8789 } drop
    }
    chain forward {
        type filter hook forward priority -150; policy accept;
        oifname "br-hr005" iifname != "ens18" drop
        oifname "br-hr005" ip saddr != 192.168.1.0/24 drop
        oifname "br-hr006" iifname != "ens18" drop
        oifname "br-hr006" ip saddr != 192.168.1.0/24 drop
    }
}
NFT
}

[[ "$mode" != --print ]] || { policy; exit 0; }
case "$mode" in --check|--install|--apply|--status|--rollback) ;; *) echo 'Use --print, --check, --install, --status or --rollback' >&2; exit 2;; esac
[[ $EUID -eq 0 ]] || { echo 'Run on Ubuntu as root.' >&2; exit 1; }
for cmd in nft systemctl ip; do command -v "$cmd" >/dev/null; done

owned_table() {
    if nft list table inet "$table" >/dev/null 2>&1; then
        nft list table inet "$table" | grep -Fq "$owner" || {
            echo 'Refusing to replace an unowned table' >&2; exit 1;
        }
        return 0
    fi
    return 1
}

if [[ "$mode" == --status ]]; then
    nft list table inet "$table"
    systemctl cat docker.service | grep -F 'household-report-vm-guard --apply' || true
    exit 0
fi
if [[ "$mode" == --rollback ]]; then
    # Validate ownership before touching the boot guard or the active table.
    owned_table || true
    # Keep the ACL in place if removing it would expose a running web container.
    if systemctl is-active --quiet docker.service; then
        command -v docker >/dev/null || { echo 'Docker CLI unavailable; stop.' >&2; exit 1; }
        exposed=$(docker ps --format '{{.Ports}}') || {
            echo 'Cannot verify published ports; stop.' >&2; exit 1;
        }
        if grep -Eq '(^|[^0-9])(8787|8789)->' <<<"$exposed"; then
            echo 'Refusing to remove the guard while an app is published' >&2; exit 1
        fi
    fi
    if [[ -e "$dropin" ]]; then
        grep -Fq '# household-report-vm-guard-v1' "$dropin" || {
            echo 'Refusing to remove an unowned Docker drop-in' >&2; exit 1;
        }
    fi
    if [[ -e "$dropin" ]]; then
        rm -f -- "$dropin"
        systemctl daemon-reload
    fi
    if owned_table; then nft delete table inet "$table"; fi
    echo 'Only the dashboard VM guard was removed; Pi-hole guard untouched.'
    exit 0
fi

ip -4 address show dev ens18 | grep -Fq 'inet 10.10.10.20/24' || {
    echo 'Expected Ubuntu VM bind address absent; stop.' >&2; exit 1;
}
if [[ "$mode" == --check || "$mode" == --install ]]; then
    # Refuse an unowned table before writing a Docker startup drop-in.
    owned_table || true
fi
if [[ "$mode" == --install ]]; then
    # A reserved application bridge that already exists must be one this
    # installation owns. In a live deployment the shared dashboard already runs
    # on br-hr005, so its existence is the intended end state and not a reason
    # to stop; an unrelated interface holding a reserved name is, and is refused.
    docker_owns_bridge() {
        local wanted=$1 net owner
        command -v docker >/dev/null || return 1
        while read -r net; do
            [[ -n "$net" ]] || continue
            owner=$(docker network inspect "$net" --format '{{index .Options "com.docker.network.bridge.name"}}' 2>/dev/null || true)
            if [[ "$owner" == "$wanted" ]]; then
                return 0
            fi
        done < <(docker network ls --format '{{.Name}}' 2>/dev/null)
        return 1
    }
    for link in br-hr005 br-hr006; do
        if ip link show dev "$link" >/dev/null 2>&1 && ! docker_owns_bridge "$link"; then
            echo "The reserved application bridge $link exists but is not owned by this installation; stop." >&2
            exit 1
        fi
    done
    for file in "$helper" "$dropin"; do
        if [[ -e "$file" ]]; then
            grep -Fq '# household-report-vm-guard-v1' "$file" || {
                echo 'Refusing to replace an unowned file' >&2; exit 1;
            }
        fi
    done
fi

umask 077
batch=$(mktemp)
trap 'rm -f "$batch"' EXIT
policy >"$batch"
if owned_table; then
    # Replace in one nft transaction: never open an unguarded ingress interval.
    sed -i '1i delete table inet household_report_guard' "$batch"
fi
nft -c -f "$batch"
if [[ "$mode" == --check ]]; then
    echo 'Scoped VM guard syntax/topology check passed; no changes made.'
    exit 0
fi

if [[ "$mode" == --install ]]; then
    mkdir -p /var/lib/household-report-guard /usr/local/libexec /etc/systemd/system/docker.service.d
    backup=$(mktemp -d /var/lib/household-report-guard/pre-install.XXXXXXXX)
    nft list ruleset >"$backup/nft-ruleset.txt"
    [[ ! -e "$helper" ]] || cp -p "$helper" "$backup/previous-helper"
    [[ ! -e "$dropin" ]] || cp -p "$dropin" "$backup/previous-dropin"
    self=$(readlink -f -- "$0")
    install -o root -g root -m 0755 "$self" "$helper"
fi

# Table replacement is scoped to this application. Apply before app publication.
nft -f "$batch"
count=$(nft list table inet "$table" | grep -c ' drop' || true)
[[ "$count" == 6 ]] || { echo 'Expected six scoped drops; stop.' >&2; exit 1; }
if [[ "$mode" == --install ]]; then
    # Do not change Docker startup behavior until the guard is actually present.
    cat >"$dropin" <<'UNIT'
# household-report-vm-guard-v1
[Service]
ExecStartPre=/usr/local/libexec/household-report-vm-guard --apply
UNIT
    chmod 0644 "$dropin"
    systemctl daemon-reload
    echo "Private dashboard-only pre-change backup: $backup"
fi
echo 'Scoped VM guard present; Pi-hole guard unchanged. Docker restart not requested.'
