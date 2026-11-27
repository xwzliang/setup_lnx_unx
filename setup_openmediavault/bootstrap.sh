#!/usr/bin/env bash
# Run inside the new Debian guest on first boot.
set -euo pipefail

state=/var/lib/setup-omv
install -d -m 0700 "$state"
exec 9>"$state/bootstrap.lock"
flock 9
[[ -e $state/packages-ready ]] && exit 0
rm -f -- "$state/packages-failed"
cleanup() {
    local status=$?
    if (( status != 0 )); then
        touch "$state/packages-failed"
    fi
    if [[ -n ${staged_installer:-} ]]; then
        rm -f -- "$staged_installer"
    fi
}
trap cleanup EXIT
. /etc/os-release
[[ $ID == debian && $VERSION_CODENAME == trixie && $(dpkg --print-architecture) == amd64 ]]

export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=3 update
apt-get -y -o Acquire::Retries=3 install qemu-guest-agent ca-certificates curl
systemctl start qemu-guest-agent

# OMV-Extras' upstream Debian 13 installer also installs its signed package
# repository. Retain the cloud image's DHCP networking and defer any reboot.
revision=8c933b5ad263d9da7882cd2f79ea2000d676f475
digest=ca65ff0f59d429d4a9164accfd28199f7cb557b6589e5b384a96babd47ad7e7c
staged_installer=$(mktemp)
curl -fsSL --retry 3 --max-time 120 \
    "https://raw.githubusercontent.com/OpenMediaVault-Plugin-Developers/installScript/$revision/install" -o "$staged_installer"
printf '%s  %s\n' "$digest" "$staged_installer" | sha256sum --check --status
bash "$staged_installer" -f -n -r
apt-get -y -o Acquire::Retries=3 install openmediavault-mergerfs openmediavault-resetperms smbclient
systemctl restart openmediavault-engined
touch "$state/packages-ready"
