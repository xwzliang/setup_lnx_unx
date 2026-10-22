#!/usr/bin/env bash

# prevent snap updates entirely:
crontab << EOF
@reboot /usr/local/bin/dropboxd start
# prevent snap updates entirely:
1 1 1 * * /usr/bin/snap set system refresh.hold="2030-01-01T01:00:00-01:00"
EOF

