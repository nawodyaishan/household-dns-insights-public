#!/usr/bin/env bash
# User-run root step. Does not publish LAN ports or restart any service.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash dns-pilot/install-firewall.sh' >&2; exit 1; }
src=$(cd -- "$(dirname -- "$0")" && pwd)
bash -n "$src/firewall-guard.sh"
umask 077
backup=$(mktemp -d /var/lib/starlink-dns-pilot-firewall-backup.XXXXXXXX)
iptables-save >"$backup/iptables.v4"
ip6tables-save >"$backup/iptables.v6"
target=/usr/local/libexec/starlink-dns-guard
dropin=/etc/systemd/system/docker.service.d/60-starlink-dns-guard.conf
mkdir -p /usr/local/libexec /etc/systemd/system/docker.service.d
[[ ! -e "$target" ]] || cp -p "$target" "$backup/previous-guard"
[[ ! -e "$dropin" ]] || cp -p "$dropin" "$backup/previous-dropin"
install -o root -g root -m 0755 "$src/firewall-guard.sh" "$target"
"$target" --apply
"$target" --check
# This is intentionally fail-closed: future Docker starts fail if protection
# cannot be loaded. It affects Docker startup, but does not restart Docker now.
printf '[Service]\nExecStartPre=/usr/local/libexec/starlink-dns-guard --apply\n' >"$dropin"
chmod 0644 "$dropin"
systemctl daemon-reload
systemctl show --no-pager docker.service -p ExecStartPre
iptables -t raw -S SLDNS-PRE
iptables -S SLDNS-IN
iptables -S SLDNS-FWD
echo "Private pre-change backup: $backup"
echo 'Installed. Docker, SSH, Starlink and Proxmox were NOT restarted or reconfigured.'
echo 'LAN ports are still unpublished. Share this output, not your sudo password.'
