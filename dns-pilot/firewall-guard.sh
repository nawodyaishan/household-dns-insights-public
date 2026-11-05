#!/usr/bin/env bash
# Only this pilot's traffic is filtered. Never flush Docker/Tailscale chains.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
mode=${1:---apply}
[[ "$mode" == --apply || "$mode" == --check ]] || { echo 'Use --apply or --check' >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo 'Run this reviewed guard as root.' >&2; exit 1; }
iptables --version | grep -q nf_tables || { echo 'Unexpected firewall backend; stop for review.' >&2; exit 1; }

chain() {
    local table=$1 name=$2
    if ! iptables -w 10 -t "$table" -S "$name" >/dev/null 2>&1; then
        [[ "$mode" == --apply ]] || { echo "Missing $table/$name" >&2; exit 1; }
        iptables -w 10 -t "$table" -N "$name"
    fi
}
rule() {
    local table=$1 name=$2
    shift 2
    if ! iptables -w 10 -t "$table" -C "$name" "$@" 2>/dev/null; then
        [[ "$mode" == --apply ]] || { echo "Missing rule in $table/$name" >&2; exit 1; }
        iptables -w 10 -t "$table" -A "$name" "$@"
    fi
}
first_jump() {
    local table=$1 name=$2 target=$3
    shift 3
    local first
    first=$(iptables -w 10 -t "$table" -S "$name" | sed -n '/^-A /{p;q;}')
    local expected="-A $name"
    if (( $# )); then expected+=" $*"; fi
    expected+=" -j $target"
    if [[ "$first" != "$expected" ]]; then
        [[ "$mode" == --apply ]] || { echo "Pilot jump not first in $table/$name" >&2; exit 1; }
        # Insert the restrictive jump first. No remove/reinsert exposure window.
        iptables -w 10 -t "$table" -I "$name" 1 "$@" -j "$target"
    fi
}

chain raw SLDNS-PRE
chain filter SLDNS-IN
chain filter SLDNS-FWD
chain filter DOCKER-USER

# Before Docker DNAT and Tailscale's INPUT accepts: protects proxy and NAT paths.
# Rules match only this VM's pilot destination ports; no SSH/41641 changes.
for table_chain in 'raw SLDNS-PRE' 'filter SLDNS-IN'; do
    read -r table name <<<"$table_chain"
    rule "$table" "$name" -i lo -j RETURN
    rule "$table" "$name" -s 192.168.1.0/24 -j RETURN
    rule "$table" "$name" -d 10.10.10.20/32 -p udp --dport 53 -j DROP
    rule "$table" "$name" -d 10.10.10.20/32 -p tcp -m multiport --dports 53,8443 -j DROP
    rule "$table" "$name" -j RETURN
done

# Covers directly routed container traffic and all new forwarded pilot traffic.
# Replies to upstream DNS/HTTPS requests must still return to the container.
rule filter SLDNS-FWD -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
rule filter SLDNS-FWD -s 192.168.1.0/24 -p udp --dport 53 -j RETURN
rule filter SLDNS-FWD -s 192.168.1.0/24 -p tcp -m multiport --dports 53,443 -j RETURN
rule filter SLDNS-FWD -j DROP

first_jump raw PREROUTING SLDNS-PRE -d 10.10.10.20/32
first_jump filter INPUT SLDNS-IN -d 10.10.10.20/32
first_jump filter DOCKER-USER SLDNS-FWD -o br-sl-dns
first_jump filter FORWARD DOCKER-USER
echo "Pilot firewall $mode: OK (household source subnet only; host loopback unaffected)"
