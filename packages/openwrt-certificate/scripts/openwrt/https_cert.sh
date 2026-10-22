#!/usr/bin/env sh
set -eu
: "${SETUP_ACME_EMAIL:?Pass --set ACME_EMAIL=you@example.com}"
: "${SETUP_ACME_DOMAIN:?Pass --set ACME_DOMAIN=your.domain}"
: "${DYNV6_TOKEN:?Export DYNV6_TOKEN for the DNS provider}"
if [ ! -x "$HOME/.acme.sh/acme.sh" ]; then
    installer=$(mktemp)
    trap 'rm -f "$installer"' EXIT
    curl -fL https://get.acme.sh -o "$installer"
    sh "$installer" email="$SETUP_ACME_EMAIL"
fi
"$HOME/.acme.sh/acme.sh" --issue --dns dns_dynv6 -d "$SETUP_ACME_DOMAIN"
opkg update
opkg install luci-ssl
printf '%s\n' 'Certificate issued. Set uhttpd cert/key paths to the issued files and restart uhttpd.'
