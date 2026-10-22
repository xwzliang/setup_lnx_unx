#!/usr/bin/env bash

su_dirs=(
    /media/broliang/BroliangData
    /media/broliang/MachineLear
    /media/broliang/TimeMachine
)

for su_dir in "${su_dirs[@]}"; do
	sudo mkdir -p $su_dir
done

# declare -a fstab_lines=(
fstab_lines=(
    "UUID=0fcb5033-42ea-335d-8983-aeaa1546f550	/media/broliang/BroliangData	hfsplus	defaults	0	0"
    "UUID=6084-DD20	/media/broliang/MachineLear	exfat	defaults,umask=000	0	0"
    "UUID=3EC9BB205A795375	/media/broliang/TimeMachine	ntfs	defaults	0	0"
)

for fstab_line in "${fstab_lines[@]}"; do
	if ! grep -q "$fstab_line" /etc/fstab; then
        echo $fstab_line
		sudo echo "# My hard drive" >> /etc/fstab
		sudo echo "$fstab_line" >> /etc/fstab
	fi
done

sudo mount -a
