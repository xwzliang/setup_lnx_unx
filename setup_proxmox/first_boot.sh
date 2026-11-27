#!/bin/bash
set -euo pipefail

repository=${1:-enterprise}
upgrade=${2:-false}

if [[ $EUID != 0 || ! -x /usr/bin/pveversion ]]; then
    echo 'Run first-boot setup as root on the new Proxmox VE node.' >&2
    exit 1
fi
. /etc/os-release
if [[ ${VERSION_CODENAME:-} != trixie ]]; then
    echo 'First-boot setup requires Proxmox VE 9 on Debian Trixie.' >&2
    exit 1
fi
case "$upgrade" in true|false) ;; *) exit 2 ;; esac

sources=/etc/apt/sources.list.d
case "$repository" in
    enterprise) ;;
    no-subscription)
        test -r /usr/share/keyrings/proxmox-archive-keyring.gpg
        # Preserve the vendor stanzas so an administrator can re-enable them.
        for file in "$sources/pve-enterprise.sources" "$sources/ceph.sources"; do
            [[ -f $file ]] || continue
            temp=$(mktemp "$sources/.proxmox.XXXXXXXX")
            awk '
                BEGIN { RS = ""; ORS = "\n\n" }
                /(^|\n)URIs:[^\n]*enterprise\.proxmox\.com/ {
                    gsub(/(^|\n)Enabled:[^\n]*/, "")
                    $0 = $0 "\nEnabled: no"
                }
                { print }
            ' "$file" > "$temp"
            chmod --reference="$file" "$temp"
            mv -f -- "$temp" "$file"
        done
        for file in "$sources/pve-enterprise.list" "$sources/ceph.list"; do
            [[ -f $file ]] || continue
            sed -i -E '/^[[:space:]]*deb[[:space:]].*enterprise\.proxmox\.com/s/^/# /' "$file"
        done
        install -m 0644 /dev/null "$sources/setup-proxmox-no-subscription.sources"
        cat > "$sources/setup-proxmox-no-subscription.sources" <<'REPO'
Types: deb
URIs: https://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
REPO
        ;;
    *) echo 'Unknown Proxmox repository option.' >&2; exit 2 ;;
esac

if [[ $upgrade == true ]]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update
    apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold dist-upgrade
fi

systemctl enable --now fstrim.timer
management_ready() {
    local service
    for service in pve-cluster pvedaemon pveproxy; do
        systemctl is-active --quiet "$service.service" || return 1
    done
    ip link show vmbr0 >/dev/null 2>&1
}

# The vendor hook and the management services can start concurrently.
for attempt in {1..60}; do
    if management_ready; then
        pvesm status
        install -d -m 0700 /var/lib/setup-proxmox
        date -u +%FT%TZ > /var/lib/setup-proxmox/first-boot-complete
        if declare -F queue_vm_setup >/dev/null; then
            queue_vm_setup
        fi
        exit 0
    fi
    sleep 1
done
echo 'Timed out waiting for Proxmox management services and vmbr0.' >&2
exit 1
