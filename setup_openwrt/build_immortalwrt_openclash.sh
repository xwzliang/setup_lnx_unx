#!/usr/bin/env bash
set -euo pipefail
umask 077

firmware=$1
converter=$2
stage=$(mktemp -d /tmp/immortalwrt-openclash.XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
tar --no-same-owner -xf - -C "$stage"

builder=setup-immortalwrt-openclash-builder:25.12.2
if ! docker image inspect "$builder" >/dev/null 2>&1; then
    docker build -t "$builder" - < "$stage/Dockerfile" >&2
fi

if [[ $converter == yes ]]; then
    converter_ref=xwzliang/subconverter-custom@sha256:048b44c6df7a83b83a29741f976441c73201fe6e74b7c5789847dce10e21f8ec
    converter_image=sha256:5c37238061333197a100e07a17145a7bfb76fd9bb0b1f40cd390d3042952d70d
    if ! docker image inspect "$converter_image" >/dev/null 2>&1; then
        docker pull --platform linux/amd64 "$converter_ref" >&2
    fi
    mkdir -p "$stage/files/usr/share/immortalwrt"
    docker save "$converter_image" > "$stage/files/usr/share/immortalwrt/subconverter.tar"
fi

docker run --rm -i --user "$(id -u):$(id -g)" --memory 4g --cpus 2 \
    --volume "$stage:/work" --workdir /work "$builder" bash -s -- "$firmware" "$converter" <<'BUILD'
set -euo pipefail
name=immortalwrt-imagebuilder-25.12.2-x86-64.Linux-x86_64
tar --zstd -xf "$name.tar.zst"
install -m 0644 luci-app-openclash-0.48.002.apk "$name/packages/"
mkdir -p files/etc/rc.d
ln -s ../init.d/openclash files/etc/rc.d/S99openclash
extra_packages=
rootfs_size=512
if [[ $2 == yes ]]; then
    extra_packages='docker dockerd'
    rootfs_size=768
    ln -s ../init.d/dockerd files/etc/rc.d/S99dockerd
    ln -s ../init.d/router-subconverter files/etc/rc.d/S99router-subconverter
fi

# ImageBuilder preserves the overlay directory modes. System daemons must
# be able to traverse /etc and /usr. The outer workspace stays private.
find files -type d -exec chmod 0755 {} +

cd "$name"
sed -i -E '/^CONFIG_(ISO|QCOW2|VDI|VMDK|VHDX)_IMAGES=y$/s/=y$/=n/; /^CONFIG_TARGET_ROOTFS_(SQUASHFS|TARGZ)=y$/s/=y$/=n/' .config
suffix=
if [[ $1 == uefi ]]; then
    sed -i 's/^CONFIG_GRUB_IMAGES=y$/CONFIG_GRUB_IMAGES=n/' .config
    suffix=-efi
else
    sed -i 's/^CONFIG_GRUB_EFI_IMAGES=y$/CONFIG_GRUB_EFI_IMAGES=n/' .config
fi
# ImageBuilder needs mode 022 for system files. The workspace is private.
umask 022
make image PROFILE=generic ROOTFS_PARTSIZE="$rootfs_size" FILES=/work/files \
    PACKAGES="-dnsmasq -automount dnsmasq-full luci-app-openclash bash curl ca-bundle ip-full ruby ruby-yaml ruby-digest kmod-tun kmod-inet-diag unzip kmod-nft-tproxy luci-compat luci luci-base kmod-wireguard wireguard-tools luci-proto-wireguard $extra_packages" >&2
umask 077
image="bin/targets/x86/64/immortalwrt-25.12.2-x86-64-generic-ext4-combined$suffix.img.gz"
if [[ ! -s $image ]]; then
    printf 'ImageBuilder did not produce %s\n' "$image" >&2
    exit 1
fi
{ cat /work/settings.json; cat "$image"; } | python3 /work/immortalwrt_image.py
BUILD
