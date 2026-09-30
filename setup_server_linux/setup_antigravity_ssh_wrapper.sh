#!/usr/bin/env bash
#
# setup_antigravity_ssh_wrapper.sh
#
# Sets up a transparent wrapper for Google Antigravity CLI (agy) on Linux machines
# to resolve GNOME Keyring authentication errors inside SSH terminal sessions.
#
# Root Cause:
#   agy contains an SSH detector that checks SSH_CONNECTION, SSH_CLIENT, and SSH_TTY.
#   When detected, it disables system GNOME Keyring access and falls back to file storage,
#   causing "Please sign in to view available models" even when the user is already
#   logged in on the Linux desktop / XRDP session.
#
# This script:
#   1. Moves the raw ELF binary from 'agy' to 'agy.real'.
#   2. Installs an intelligent wrapper script at 'agy' that strips SSH_* env vars and
#      exports the correct DBUS_SESSION_BUS_ADDRESS.
#   3. Adds an interactive shell fallback in ~/.all_sh_aliases (or ~/.bashrc / ~/.zshrc).
#   4. Verifies the setup and tests keyring connectivity.
#

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

log_info() {
    printf "\033[1;34m==>\033[0m %s\n" "$*"
}

log_success() {
    printf "\033[1;32m✓\033[0m %s\n" "$*"
}

log_warn() {
    printf "\033[1;33m!\033[0m %s\n" "$*" >&2
}

log_error() {
    printf "\033[1;31m✗\033[0m %s\n" "$*" >&2
}

die() {
    log_error "$*"
    exit 1
}

show_usage() {
    cat << EOF
Usage: $SCRIPT_NAME [OPTIONS]

Set up the Antigravity CLI (agy) wrapper on Linux to allow seamless GNOME Keyring
authentication within SSH terminal sessions.

Options:
  -i, --install       Download & install official Antigravity CLI if not found, then wrap
  -u, --uninstall     Restore original raw agy binary and remove shell hooks
  -c, --check         Check current setup status and test authentication
  -d, --dir <DIR>     Explicit directory containing agy (default: auto-detect)
  -h, --help          Show this help message

Examples:
  ./$SCRIPT_NAME              # Automatically find and wrap existing agy
  ./$SCRIPT_NAME --install    # Install agy if missing, then wrap
  ./$SCRIPT_NAME --check      # Verify SSH authentication status
  ./$SCRIPT_NAME --uninstall  # Restore raw agy binary
EOF
}

TARGET_DIR=""
ACTION="wrap"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--install)
            ACTION="install"
            shift
            ;;
        -u|--uninstall)
            ACTION="uninstall"
            shift
            ;;
        -c|--check)
            ACTION="check"
            shift
            ;;
        -d|--dir)
            [[ -n "${2:-}" ]] || die "Missing directory argument for --dir"
            TARGET_DIR="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            die "Unknown option: $1 (run with --help for usage)"
            ;;
    esac
done

detect_agy_locations() {
    local candidates=()
    if [[ -n "$TARGET_DIR" ]]; then
        candidates+=("$TARGET_DIR")
    fi
    candidates+=("$HOME/.local/bin" "/usr/local/bin")
    
    local cmd_path
    cmd_path="$(command -v agy 2>/dev/null || true)"
    if [[ -n "$cmd_path" ]]; then
        candidates+=("$(dirname "$cmd_path")")
    fi
    local real_cmd_path
    real_cmd_path="$(command -v agy.real 2>/dev/null || true)"
    if [[ -n "$real_cmd_path" ]]; then
        candidates+=("$(dirname "$real_cmd_path")")
    fi

    local seen=":"
    FOUND_DIR=""
    for dir in "${candidates[@]}"; do
        [[ -d "$dir" ]] || continue
        if [[ "$seen" == *":$dir:"* ]]; then
            continue
        fi
        seen="$seen$dir:"

        if [[ -f "$dir/agy" || -f "$dir/agy.real" ]]; then
            FOUND_DIR="$dir"
            return 0
        fi
    done

    FOUND_DIR="$HOME/.local/bin"
    return 1
}

install_official_agy() {
    log_info "Installing official Antigravity CLI via curl..."
    mkdir -p "$FOUND_DIR"
    curl -fsSL https://antigravity.google/cli/install.sh | bash
    [[ -f "$FOUND_DIR/agy" ]] || die "Installation completed but $FOUND_DIR/agy was not found."
    log_success "Official Antigravity CLI installed successfully."
}

configure_shell_hook() {
    local target_rc=""
    if [[ -f "$HOME/.all_sh_aliases" ]]; then
        target_rc="$HOME/.all_sh_aliases"
    elif [[ -f "$HOME/.bashrc" ]]; then
        target_rc="$HOME/.bashrc"
    elif [[ -f "$HOME/.zshrc" ]]; then
        target_rc="$HOME/.zshrc"
    else
        target_rc="$HOME/.all_sh_aliases"
        touch "$target_rc"
    fi

    if grep -q "Antigravity CLI SSH session" "$target_rc" 2>/dev/null; then
        log_info "Shell alias hook already present in $target_rc"
        return 0
    fi

    log_info "Adding interactive shell helper function to $target_rc..."
    cat >> "$target_rc" << 'EOF_RC'

# >>> Antigravity CLI SSH session keyring fix >>>
if [ -n "$SSH_CONNECTION" ] || [ -n "$SSH_CLIENT" ] || [ -n "$SSH_TTY" ]; then
  agy() {
    env -u SSH_CONNECTION -u SSH_CLIENT -u SSH_TTY \
      DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}" \
      "$(command -v agy.real 2>/dev/null || which -p agy.real 2>/dev/null || which agy)" "$@"
  }
fi
# <<< Antigravity CLI SSH session keyring fix <<<
EOF_RC
    log_success "Shell hook configured in $target_rc"
}

remove_shell_hook() {
    for rc in "$HOME/.all_sh_aliases" "$HOME/.bashrc" "$HOME/.zshrc"; do
        [[ -f "$rc" ]] || continue
        if grep -q "Antigravity CLI SSH session" "$rc" 2>/dev/null; then
            log_info "Removing shell hook from $rc..."
            sed -i '/# >>> Antigravity CLI SSH session/,/# <<< Antigravity CLI SSH session/d' "$rc"
            log_success "Removed hook from $rc"
        fi
    done
}

apply_wrapper() {
    local bin_dir="$1"
    local agy_path="$bin_dir/agy"
    local real_path="$bin_dir/agy.real"

    mkdir -p "$bin_dir"

    if [[ -f "$agy_path" ]]; then
        if file "$agy_path" 2>/dev/null | grep -q 'ELF'; then
            log_info "Detected raw ELF binary at $agy_path. Moving to $real_path..."
            mv -f "$agy_path" "$real_path"
        elif [[ ! -f "$real_path" ]]; then
            die "$agy_path is not an ELF binary and $real_path does not exist."
        fi
    elif [[ -f "$real_path" ]]; then
        log_info "Found existing $real_path."
    else
        die "No agy executable found in $bin_dir. Run with --install to download it."
    fi

    [[ -x "$real_path" ]] || chmod +x "$real_path"

    log_info "Writing wrapper script to $agy_path..."
    cat > "$agy_path" << 'EOF_WRAPPER'
#!/usr/bin/env sh
# Antigravity CLI SSH session wrapper
# Bypasses agy SSH-detection that disables system keyring access on Linux.
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -S "/run/user/$(id -u)/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
fi
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REAL_BIN="$DIR/agy.real"
if [ ! -x "$REAL_BIN" ]; then
  REAL_BIN="$(command -v agy.real 2>/dev/null || true)"
fi
if [ -x "$REAL_BIN" ]; then
  exec env -u SSH_CONNECTION -u SSH_CLIENT -u SSH_TTY "$REAL_BIN" "$@"
fi
echo "Error: agy.real binary not found in $DIR or PATH" >&2
exit 127
EOF_WRAPPER

    chmod 755 "$agy_path"
    log_success "Wrapper installed successfully at $agy_path"

    configure_shell_hook
}

check_environment() {
    local uid
    uid="$(id -u)"
    local bus_socket="/run/user/$uid/bus"

    echo ""
    log_info "Diagnosing environment..."
    echo "  User:         $(id -un) (UID: $uid)"
    echo "  Directory:    $FOUND_DIR"
    echo "  Wrapper:      $FOUND_DIR/agy $([[ -x "$FOUND_DIR/agy" ]] && echo '[OK]' || echo '[MISSING]')"
    echo "  Real Binary:  $FOUND_DIR/agy.real $([[ -x "$FOUND_DIR/agy.real" ]] && echo '[OK]' || echo '[MISSING]')"

    if [[ -S "$bus_socket" ]]; then
        log_success "D-Bus session bus socket active: $bus_socket"
    else
        log_warn "D-Bus user session bus socket not found at $bus_socket."
        log_warn "If this server is headless without an active graphical session, enable lingering with:"
        log_warn "  loginctl enable-linger $(id -un)"
    fi

    if [[ -x "$FOUND_DIR/agy" ]]; then
        echo ""
        log_info "Testing CLI execution via wrapper..."
        local ver
        ver="$("$FOUND_DIR/agy" --version 2>&1 || true)"
        echo "  Version: $ver"

        echo ""
        log_info "Testing Keyring authentication (models query)..."
        local models_out
        if models_out="$("$FOUND_DIR/agy" models 2>&1)"; then
            log_success "Successfully authenticated with Keyring in SSH mode!"
            echo "Available models sample:"
            printf "%s\n" "$models_out" | grep -v 'find:' | head -n 5 | sed 's/^/    /'
        else
            log_warn "Keyring authentication test returned non-zero:"
            printf "%s\n" "$models_out" | sed 's/^/    /'
            log_warn "Please ensure you have logged in to Antigravity on this machine at least once."
        fi
    fi
}

do_uninstall() {
    local bin_dir="$1"
    local agy_path="$bin_dir/agy"
    local real_path="$bin_dir/agy.real"

    if [[ -f "$real_path" ]]; then
        log_info "Restoring raw binary from $real_path to $agy_path..."
        rm -f "$agy_path"
        mv -f "$real_path" "$agy_path"
        chmod +x "$agy_path"
        log_success "Restored original binary to $agy_path."
    elif [[ -f "$agy_path" ]]; then
        log_warn "$real_path does not exist; leaving $agy_path untouched."
    fi

    remove_shell_hook
    log_success "Uninstall completed."
}

# --- Main Execution Flow ---

if ! detect_agy_locations; then
    if [[ "$ACTION" == "install" ]]; then
        install_official_agy
    elif [[ "$ACTION" != "uninstall" ]]; then
        log_warn "Could not locate 'agy' executable in candidate directories."
        echo "Run with --install to automatically download and install official Antigravity CLI."
        exit 1
    fi
fi

case "$ACTION" in
    wrap|install)
        apply_wrapper "$FOUND_DIR"
        check_environment
        echo ""
        log_success "Setup complete! You can now run 'agy' freely inside any SSH session."
        ;;
    check)
        check_environment
        ;;
    uninstall)
        do_uninstall "$FOUND_DIR"
        ;;
esac
