#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# setup_proxmox_autologin.sh
#
# Description:
#   Configures passwordless, automatic login and trusted SSL for Proxmox VE (PVE).
#   Designed for private LAN / homelab environments where typing credentials
#   repeatedly or handling certificate warnings and session expirations is undesirable.
#
# Features:
#   1. Automatic silent login as root@pam (or custom user) on page load.
#   2. 1-Year persistent session cookies (prevents logout on browser close).
#   3. Silent re-authentication on 401 / session expiration (e.g. computer wake from sleep).
#   4. Disables the annoying "No Subscription" nag popup completely.
#   5. Supports both Desktop UI and Mobile Touch UI.
#   6. Configures valid SSL certificate with SANs (.local, hostname, IP, localhost)
#      signed by the internal PVE Root CA.
#   7. If invoked from macOS, automatically imports and trusts the PVE Root CA in Keychain.
#   8. Survives PVE upgrades via APT Post-Invoke hook and systemd service.
#   9. Supports local execution directly on PVE or remote execution via SSH from Mac/Linux.
#
# Usage:
#   # Local execution on Proxmox host:
#   sudo ./setup_proxmox_autologin.sh [-p PASSWORD] [-u USER]
#
#   # Remote execution via SSH:
#   ./setup_proxmox_autologin.sh --remote root@192.168.1.100 [-p PASSWORD]
#   ./setup_proxmox_autologin.sh -r pve [-p PASSWORD]
#
#   # Revert / Uninstall:
#   sudo ./setup_proxmox_autologin.sh --uninstall
#   ./setup_proxmox_autologin.sh -r pve --uninstall
# ==============================================================================

SCRIPT_SRC="${BASH_SOURCE[0]:-$0}"
SCRIPT_NAME="$(basename "${SCRIPT_SRC}")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_SRC}")" 2>/dev/null && pwd || echo ".")"
SCRIPT_PATH="${SCRIPT_DIR}/${SCRIPT_NAME}"

PVE_USER="root@pam"
PVE_PASS=""
REMOTE_HOST=""
REMOTE_PORT="22"
UNINSTALL=false

show_help() {
    cat << HELP_EOF
Usage:
  ${SCRIPT_NAME} [OPTIONS]

Options:
  -p, --password <PASS>   Proxmox user password (prompts securely if omitted)
  -u, --user <USER>       Proxmox username (default: root@pam)
  -r, --remote <HOST>     Execute remotely on target host via SSH (e.g. root@192.168.5.101 or ssh alias)
  --port <PORT>           SSH port when using --remote (default: 22)
  --uninstall             Remove auto-login hooks and restore original stock templates
  -h, --help              Show this help message and exit

Examples:
  # Run directly on Proxmox node as root:
  sudo ./${SCRIPT_NAME} -p mypassword

  # Run remotely from Mac or another machine over SSH:
  ./${SCRIPT_NAME} -r root@192.168.5.101 -p mypassword
  ./${SCRIPT_NAME} -r pve

  # Uninstall and revert changes:
  sudo ./${SCRIPT_NAME} --uninstall
  ./${SCRIPT_NAME} -r pve --uninstall
HELP_EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--password)
            PVE_PASS="$2"
            shift 2
            ;;
        -u|--user)
            PVE_USER="$2"
            shift 2
            ;;
        -r|--remote)
            REMOTE_HOST="$2"
            shift 2
            ;;
        --port)
            REMOTE_PORT="$2"
            shift 2
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Error: Unknown argument '$1'" >&2
            show_help >&2
            exit 1
            ;;
    esac
done

configure_firefox_trust() {
    local ca_file="$1"
    local ff_profile_dirs=()

    # Detect Firefox profile directories on macOS and Linux
    if [[ -d "${HOME}/Library/Application Support/Firefox/Profiles" ]]; then
        for p in "${HOME}/Library/Application Support/Firefox/Profiles"/*; do
            [[ -d "$p" ]] && ff_profile_dirs+=("$p")
        done
    fi
    if [[ -d "${HOME}/.mozilla/firefox" ]]; then
        for p in "${HOME}/.mozilla/firefox"/*; do
            [[ -d "$p" ]] && ff_profile_dirs+=("$p")
        done
    fi
    if [[ -d "${HOME}/.var/app/org.mozilla.firefox/.mozilla/firefox" ]]; then
        for p in "${HOME}/.var/app/org.mozilla.firefox/.mozilla/firefox"/*; do
            [[ -d "$p" ]] && ff_profile_dirs+=("$p")
        done
    fi

    if [[ ${#ff_profile_dirs[@]} -gt 0 ]]; then
        echo "==> Configuring Firefox to trust OS / enterprise Root CAs..."
        for p in "${ff_profile_dirs[@]}"; do
            local user_js="${p}/user.js"
            if [[ -f "${user_js}" ]]; then
                if ! grep -q 'security.enterprise_roots.enabled' "${user_js}"; then
                    echo 'user_pref("security.enterprise_roots.enabled", true);' >> "${user_js}"
                    echo "    Updated ${user_js}"
                fi
            else
                echo 'user_pref("security.enterprise_roots.enabled", true);' > "${user_js}"
                echo "    Created ${user_js}"
            fi
        done
        echo "[OK] Firefox configured (security.enterprise_roots.enabled = true)."
    fi

    # Save a permanent copy of the Root CA for reference or manual import
    local pve_conf_dir="${HOME}/.config/proxmox"
    mkdir -p "${pve_conf_dir}"
    local host_id
    host_id="$(echo "${REMOTE_HOST:-local}" | tr -cd '[:alnum:]_-')"
    local saved_ca="${pve_conf_dir}/pve-root-ca-${host_id}.pem"
    cp -f "${ca_file}" "${saved_ca}"
    chmod 644 "${saved_ca}"
    echo "    Saved CA copy to: ${saved_ca}"
}

# If remote execution requested, transfer and invoke script over SSH
if [[ -n "${REMOTE_HOST}" ]]; then
    echo "==> Remote mode selected: target '${REMOTE_HOST}' (port ${REMOTE_PORT})"
    
    if [[ "${UNINSTALL}" == "true" ]]; then
        echo "==> Executing uninstall remotely on ${REMOTE_HOST}..."
        ssh -p "${REMOTE_PORT}" "${REMOTE_HOST}" "bash -s" -- --uninstall < "${SCRIPT_PATH}"
        exit 0
    fi

    if [[ -z "${PVE_PASS}" ]]; then
        read -rsp "Enter Proxmox password for [${PVE_USER}]: " PVE_PASS
        echo ""
    fi

    if [[ -z "${PVE_PASS}" ]]; then
        echo "Error: Password cannot be empty." >&2
        exit 1
    fi

    echo "==> Executing setup remotely on ${REMOTE_HOST}..."
    ssh -p "${REMOTE_PORT}" "${REMOTE_HOST}" "bash -s" -- -u "${PVE_USER}" -p "${PVE_PASS}" < "${SCRIPT_PATH}"

    # Fetch PVE Root CA to establish client-side trust (macOS Keychain + Firefox)
    tmp_ca="/tmp/pve-root-ca-$(echo "${REMOTE_HOST}" | tr -cd '[:alnum:]_-').pem"
    if ssh -p "${REMOTE_PORT}" "${REMOTE_HOST}" "cat /etc/pve/pve-root-ca.pem" > "${tmp_ca}" 2>/dev/null; then
        if [[ "$(uname -s)" == "Darwin" ]]; then
            cert_cn="$(openssl x509 -in "${tmp_ca}" -noout -subject 2>/dev/null | sed -n 's/.*CN[ =]*//p' | sed 's/,.*//' || echo "Proxmox Virtual Environment")"
            if security find-certificate -c "${cert_cn}" ~/Library/Keychains/login.keychain-db &>/dev/null; then
                echo "[OK] PVE Root CA is already present in macOS login keychain."
            else
                echo "==> Detected macOS client: Adding PVE Root CA to macOS login keychain..."
                security add-trusted-cert -r trustRoot -p ssl -k ~/Library/Keychains/login.keychain-db "${tmp_ca}" 2>/dev/null || true
                echo "[OK] PVE Root CA trusted in macOS keychain (Safari, Chrome, Edge, curl)."
            fi
        fi
        configure_firefox_trust "${tmp_ca}"
        rm -f "${tmp_ca}"
    fi
    exit 0
fi

# ------------------------------------------------------------------------------
# LOCAL EXECUTION ON PROXMOX NODE
# ------------------------------------------------------------------------------

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Error: This script must be run as root (or with sudo) on the Proxmox node." >&2
    exit 1
fi

if [[ ! -d "/usr/share/pve-manager" || ! -f "/usr/share/perl5/PVE/Service/pveproxy.pm" ]]; then
    echo "Error: This system does not appear to be a Proxmox VE installation." >&2
    echo "Missing /usr/share/pve-manager or /usr/share/perl5/PVE/Service/pveproxy.pm" >&2
    exit 1
fi

# Handle Uninstall
if [[ "${UNINSTALL}" == "true" ]]; then
    echo "==> Uninstalling Proxmox Auto-Login..."
    
    # 1. Stop and disable systemd service
    if systemctl is-enabled pve-autologin.service &>/dev/null; then
        systemctl disable --now pve-autologin.service 2>/dev/null || true
    fi
    rm -f /etc/systemd/system/pve-autologin.service
    systemctl daemon-reload

    # 2. Remove APT hook
    rm -f /etc/apt/apt.conf.d/99pve-autologin

    # 3. Remove apply script
    rm -f /usr/local/bin/pve-autologin-apply

    # 4. Restore original templates from backup
    if [[ -f "/usr/share/pve-manager/index.html.tpl.bak" ]]; then
        cp -a /usr/share/pve-manager/index.html.tpl.bak /usr/share/pve-manager/index.html.tpl
        echo "Restored /usr/share/pve-manager/index.html.tpl from backup."
    fi
    if [[ -f "/usr/share/pve-manager/touch/index.html.tpl.bak" ]]; then
        cp -a /usr/share/pve-manager/touch/index.html.tpl.bak /usr/share/pve-manager/touch/index.html.tpl
        echo "Restored /usr/share/pve-manager/touch/index.html.tpl from backup."
    fi

    # 5. Restart pveproxy
    systemctl reload-or-try-restart pveproxy || systemctl restart pveproxy
    echo "==> Proxmox Auto-Login uninstalled successfully."
    exit 0
fi

# Prompt for password if not passed
if [[ -z "${PVE_PASS}" ]]; then
    read -rsp "Enter Proxmox password for [${PVE_USER}]: " PVE_PASS
    echo ""
fi

if [[ -z "${PVE_PASS}" ]]; then
    echo "Error: Password cannot be empty." >&2
    exit 1
fi

echo "==> Testing credentials for user '${PVE_USER}' against local API..."
AUTH_CHECK=$(curl -k -s -X POST https://127.0.0.1:8006/api2/extjs/access/ticket \
    --data-urlencode "username=${PVE_USER}" \
    --data-urlencode "password=${PVE_PASS}" \
    --data-urlencode "new-format=1" || true)

if ! echo "${AUTH_CHECK}" | grep -q '"success":1'; then
    echo "Error: Authentication failed! The provided credentials for '${PVE_USER}' are invalid." >&2
    echo "API Response: ${AUTH_CHECK}" >&2
    exit 1
fi
echo "[OK] Credentials verified successfully."

# Backup original templates if backups do not exist yet
if [[ ! -f "/usr/share/pve-manager/index.html.tpl.bak" ]]; then
    cp -a /usr/share/pve-manager/index.html.tpl /usr/share/pve-manager/index.html.tpl.bak
    echo "[OK] Created backup /usr/share/pve-manager/index.html.tpl.bak"
fi
if [[ -f "/usr/share/pve-manager/touch/index.html.tpl" && ! -f "/usr/share/pve-manager/touch/index.html.tpl.bak" ]]; then
    cp -a /usr/share/pve-manager/touch/index.html.tpl /usr/share/pve-manager/touch/index.html.tpl.bak
    echo "[OK] Created backup /usr/share/pve-manager/touch/index.html.tpl.bak"
fi

# Configure SSL Certificate with full Subject Alternative Names (SANs)
setup_ssl_certificate() {
    echo "==> Configuring SSL certificate with SANs (including .local and IP)..."
    local nodename
    nodename="$(hostname)"
    local local_ip
    local_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || echo '')"

    cat << 'CNF_EOF' > /tmp/pveproxy-ssl.cnf
[ req ]
default_bits = 2048
prompt = no
default_md = sha256
req_extensions = req_ext
distinguished_name = dn

[ dn ]
CN = __NODENAME__.local
O = Proxmox Virtual Environment
OU = PVE Cluster Node

[ req_ext ]
subjectAltName = @alt_names

[ v3_ext ]
authorityKeyIdentifier = keyid,issuer
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = __NODENAME__.local
DNS.2 = __NODENAME__
DNS.3 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
CNF_EOF

    sed -i "s/__NODENAME__/${nodename}/g" /tmp/pveproxy-ssl.cnf
    if [[ -n "${local_ip}" ]]; then
        echo "IP.3 = ${local_ip}" >> /tmp/pveproxy-ssl.cnf
    fi

    if [[ -f "/etc/pve/pve-root-ca.pem" && -f "/etc/pve/priv/pve-root-ca.key" ]]; then
        openssl genrsa -out /tmp/pveproxy-ssl.key 2048 2>/dev/null
        openssl req -new -key /tmp/pveproxy-ssl.key -out /tmp/pveproxy-ssl.csr -config /tmp/pveproxy-ssl.cnf 2>/dev/null
        openssl x509 -req -in /tmp/pveproxy-ssl.csr \
            -CA /etc/pve/pve-root-ca.pem -CAkey /etc/pve/priv/pve-root-ca.key -CAcreateserial \
            -out /tmp/pveproxy-ssl.crt -days 820 -extfile /tmp/pveproxy-ssl.cnf -extensions v3_ext -sha256 2>/dev/null

        cat /tmp/pveproxy-ssl.crt /etc/pve/pve-root-ca.pem > /etc/pve/local/pveproxy-ssl.pem
        cp -f /tmp/pveproxy-ssl.key /etc/pve/local/pveproxy-ssl.key
        rm -f /tmp/pveproxy-ssl.*
        echo "[OK] Generated /etc/pve/local/pveproxy-ssl.pem with SAN for ${nodename}.local"
    fi
}

setup_ssl_certificate

# Write /usr/local/bin/pve-autologin-apply generator script
echo "==> Installing /usr/local/bin/pve-autologin-apply..."
export PVE_USER PVE_PASS
python3 - << 'PY_GEN'
import json, os, sys

pve_user = os.environ.get("PVE_USER", "root@pam")
pve_pass = os.environ.get("PVE_PASS", "")

user_json = json.dumps(pve_user)
pass_json = json.dumps(pve_pass)

template_script = """#!/usr/bin/env python3
import os, sys, re, subprocess, json

DESKTOP_TPL = "/usr/share/pve-manager/index.html.tpl"
TOUCH_TPL = "/usr/share/pve-manager/touch/index.html.tpl"

USER = __USER_JSON__
PASS = __PASS_JSON__

DESKTOP_INJECTION = '''
    <script type="text/javascript">
    if (typeof(PVE) === 'undefined') PVE = {};

    (function() {
	// 1. Completely disable the "No Subscription" nag popup
	if (typeof Proxmox !== 'undefined' && Proxmox.Utils) {
	    Proxmox.Utils.checked_command = function(orig_cmd) {
		if (typeof orig_cmd === 'function') {
		    orig_cmd();
		}
	    };

	    // 2. Make auth cookie persistent (1 year) instead of expiring on browser close
	    var origSetAuthData = Proxmox.Utils.setAuthData;
	    Proxmox.Utils.setAuthData = function(data) {
		origSetAuthData.call(this, data);
		if (data && data.ticket) {
		    var expireDate = new Date();
		    expireDate.setFullYear(expireDate.getFullYear() + 1);
		    Ext.util.Cookies.set(Proxmox.Setup.auth_cookie_name, data.ticket, expireDate, '/', null, true, 'lax');
		}
	    };
	}

	// 3. Define auto-login methods on PVE.Workspace
	if (typeof PVE !== 'undefined' && PVE.Workspace) {
	    PVE.Workspace.prototype.doAutoLogin = function() {
		var me = this;
		if (me._autoLoginInProgress) return;
		me._autoLoginInProgress = true;

		Ext.Ajax.request({
		    url: '/api2/extjs/access/ticket',
		    method: 'POST',
		    params: {
			username: __USER_JSON__,
			password: __PASS_JSON__,
			'new-format': 1
		    },
		    success: function(response) {
			me._autoLoginInProgress = false;
			var obj = Ext.decode(response.responseText);
			if (obj && obj.data) {
			    me.updateLoginData(obj.data);
			}
		    },
		    failure: function() {
			me._autoLoginInProgress = false;
		    }
		});
	    };

	    PVE.Workspace.prototype.showLogin = function() {
		var me = this;
		me.doAutoLogin();
	    };

	    // On any 401 error, trigger immediate silent re-authentication
	    Ext.Ajax.on('requestexception', function(conn, response) {
		if (response.status === 401 || response.status === '401') {
		    var ws = Ext.ComponentQuery.query('pveStdWorkspace')[0];
		    if (ws) {
			ws.doAutoLogin();
		    }
		}
	    });
	}

	// 4. Suppress login window display completely
	if (typeof PVE !== 'undefined' && PVE.window && PVE.window.LoginWindow) {
	    PVE.window.LoginWindow.prototype.show = function() {
		return this;
	    };
	}
    })();

    Ext.History.fieldid = 'x-history-field';
    Ext.onReady(function() {
	var ws = Ext.create('PVE.StdWorkspace');
	if (!ws.loginData) {
	    ws.doAutoLogin();
	}
    });
    </script>
'''

def apply_desktop():
    if not os.path.exists(DESKTOP_TPL):
        return False
    with open(DESKTOP_TPL, 'r') as f:
        content = f.read()
    if 'doAutoLogin' in content:
        return False
    idx = content.rfind('<script type="text/javascript">')
    if idx != -1 and 'PVE.StdWorkspace' in content[idx:]:
        end_idx = content.find('</script>', idx)
        if end_idx != -1:
            new_content = content[:idx] + DESKTOP_INJECTION.strip() + content[end_idx + len('</script>'):]
        else:
            new_content = content.replace("</head>", DESKTOP_INJECTION + "\\n  </head>")
    else:
        new_content = content.replace("</head>", DESKTOP_INJECTION + "\\n  </head>")
    with open(DESKTOP_TPL, 'w') as f:
        f.write(new_content)
    return True

TOUCH_INJECTION = '''
    <script type="text/javascript">
    if (typeof(PVE) === 'undefined') PVE = {};

    (function() {
	if (typeof Proxmox !== 'undefined' && Proxmox.Utils) {
	    Proxmox.Utils.checked_command = function(fn) { if (fn) fn(); };
	    var origSetAuthData = Proxmox.Utils.setAuthData;
	    Proxmox.Utils.setAuthData = function(data) {
		origSetAuthData.call(this, data);
		if (data && data.ticket) {
		    var expireDate = new Date();
		    expireDate.setFullYear(expireDate.getFullYear() + 1);
		    Ext.util.Cookies.set(Proxmox.Setup.auth_cookie_name, data.ticket, expireDate, '/', null, true, 'lax');
		}
	    };
	}
	if (typeof PVE !== 'undefined' && PVE.Workspace) {
	    var autoLoginMobile = function() {
		Ext.Ajax.request({
		    url: '/api2/extjs/access/ticket',
		    method: 'POST',
		    params: {
			username: __USER_JSON__,
			password: __PASS_JSON__,
			'new-format': 1
		    },
		    success: function(response) {
			var obj = Ext.decode(response.responseText);
			if (obj && obj.data) {
			    PVE.Workspace.updateLoginData(obj.data);
			}
		    }
		});
	    };
	    var origLoadPage = PVE.Workspace.loadPage;
	    PVE.Workspace.loadPage = function(loc) {
		if (!Proxmox.Utils.authOK()) {
		    autoLoginMobile();
		    return;
		}
		origLoadPage.call(this, loc);
	    };
	    PVE.Workspace.showLogin = function() {
		autoLoginMobile();
	    };
	}
    })();
    </script>
'''

def apply_touch():
    if not os.path.exists(TOUCH_TPL):
        return False
    with open(TOUCH_TPL, 'r') as f:
        content = f.read()
    if 'autoLoginMobile' in content:
        return False
    new_content = content.replace("</head>", TOUCH_INJECTION + "\\n  </head>")
    with open(TOUCH_TPL, 'w') as f:
        f.write(new_content)
    return True

if __name__ == "__main__":
    changed_desktop = apply_desktop()
    changed_touch = apply_touch()
    if changed_desktop or changed_touch:
        print("PVE Auto-login patch applied successfully.")
        subprocess.run(["systemctl", "reload-or-try-restart", "pveproxy"], check=False)
    else:
        print("PVE Auto-login patch already active.")
"""

code = template_script.replace("__USER_JSON__", user_json).replace("__PASS_JSON__", pass_json)

with open('/usr/local/bin/pve-autologin-apply', 'w') as f:
    f.write(code)
PY_GEN

chmod 700 /usr/local/bin/pve-autologin-apply

# Apply the patch immediately
echo "==> Applying template modifications..."
/usr/local/bin/pve-autologin-apply

# Setup APT hook for package upgrade persistence
echo "==> Configuring APT Post-Invoke hook..."
cat << 'APT_EOF' > /etc/apt/apt.conf.d/99pve-autologin
DPkg::Post-Invoke { "if [ -x /usr/local/bin/pve-autologin-apply ]; then /usr/local/bin/pve-autologin-apply; fi"; };
APT_EOF

# Setup systemd service for boot persistence
echo "==> Configuring systemd persistence service..."
cat << 'SERVICE_EOF' > /etc/systemd/system/pve-autologin.service
[Unit]
Description=Ensure PVE Auto-login is applied
Before=pveproxy.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/pve-autologin-apply
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable --now pve-autologin.service

# Reload pveproxy
echo "==> Reloading pveproxy service..."
systemctl reload-or-try-restart pveproxy || systemctl restart pveproxy

echo "------------------------------------------------------------------------------"
echo " SUCCESS: Proxmox VE auto-login & SSL setup completed!"
echo " User:        ${PVE_USER}"
echo " Web UI URL:  https://$(hostname).local:8006/ (or https://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'YOUR_PVE_IP'):8006/)"
echo " Persistence: APT Post-Invoke hook & systemd service enabled."
echo "------------------------------------------------------------------------------"
