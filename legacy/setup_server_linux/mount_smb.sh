server_name_or_ip=$1
sharename=$2
youruser=$3
yourpass=$4
sudo apt install -y cifs-utils libnss-mdns

cat <<EOF | sudo tee /etc/.smbcredentials
username=$youruser
password=$yourpass
# domain=DOMAIN   # omit this line if you’re not on a Windows domain
EOF
sudo chmod 600 /etc/.smbcredentials

sudo echo "//${server_name_or_ip}/${sharename} /mnt/${sharename}  cifs  credentials=/etc/.smbcredentials,uid=1000,gid=1000,vers=3.0,_netdev  0  0" >> /etc/fstab

sudo mkdir -p /mnt/${sharename}

sudo chown $(id -u):$(id -g) /mnt/${sharename}

sudo mount -a
