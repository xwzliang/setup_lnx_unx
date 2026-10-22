# Get acme.sh
curl https://get.acme.sh | sh -s email=18706703437@163.com

# https://github.com/acmesh-official/acme.sh/wiki/dnsapi2#dns_dynv6
# Add Environment variable export DYNV6_TOKEN="value"
# Issue a cert use:
/root/.acme.sh/acme.sh --issue --dns dns_dynv6 -d xwzliang.dynv6.net

# openwrt install luci-ssl
opkg update
opkg install luci-ssl

# 修改/etc/config/uhttpd.conf，确保"list listen_https '0.0.0.0:443'" "list listen_https '[::]:443'"有效
# 修改option cert 和 key 为acme申请的证书路径
# 重新启动uhttpd：/etc/init.d/uhttpd restart
