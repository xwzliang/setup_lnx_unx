#!/usr/bin/env bash
# Run locally; reproduce the router's subconverter deployment over SSH.
set -euo pipefail
router=192.168.5.1
ssh_port=22
image=xwzliang/subconverter-custom:0.0.2
name=subconverter
port=15051
bind_address=0.0.0.0
config_dir=/etc/openclash/config

usage() {
    cat <<'HELP'
Usage: install_subconverter.sh [options]
  --router HOST       Router address/SSH alias (default: 192.168.5.1)
  --ssh-port PORT     SSH port (default: 22)
  --image IMAGE       Docker image (default: xwzliang/subconverter-custom:0.0.2)
  --name NAME         Container name (default: subconverter)
  --port PORT         Published TCP port (default: 15051; container port: 25500)
  --bind-address IP   Published IPv4 address (default: 0.0.0.0)
  --config-dir PATH   Router directory mounted read/write at /data
                     (default: /etc/openclash/config)
  -h, --help          Show help

Requires Docker running on the router. A matching existing container is reused;
a stopped matching container is started. Conflicting containers are never replaced.
HELP
}
die() { echo "ERROR: $*" >&2; exit 1; }
while (($#)); do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --router|--ssh-port|--image|--name|--port|--bind-address|--config-dir)
            (($# >= 2)) || die "Missing value for $1"
            case "$1" in
                --router) router=${2#root@} ;;
                --ssh-port) ssh_port=$2 ;;
                --image) image=$2 ;;
                --name) name=$2 ;;
                --port) port=$2 ;;
                --bind-address) bind_address=$2 ;;
                --config-dir) config_dir=$2 ;;
            esac
            shift 2 ;;
        *) die "Unknown option: $1" ;;
    esac
done
# Validate before constructing the remote shell command (including its arguments).
[[ $router =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || die "Invalid router address/alias"
[[ $image =~ ^[a-zA-Z0-9][a-zA-Z0-9_./:@-]*$ ]] || die "Invalid image reference"
[[ $name =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || die "Invalid container name"
[[ $config_dir =~ ^/[a-zA-Z0-9_./-]+$ ]] || die "Config directory must be an absolute path without spaces"
[[ $bind_address =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Bind address must be IPv4"
for value in "$port" "$ssh_port"; do
    [[ $value =~ ^[0-9]{1,5}$ ]] || die "Invalid port: $value"
    ((10#$value >= 1 && 10#$value <= 65535)) || die "Invalid port: $value"
done
port=$((10#$port)); ssh_port=$((10#$ssh_port))

ssh -p "$ssh_port" -o ConnectTimeout=10 "root@$router" \
    "sh -s -- '$image' '$name' '$port' '$bind_address' '$config_dir'" <<'REMOTE'
set -eu
image=$1; name=$2; port=$3; bind_address=$4; config_dir=$5
die() { echo "ERROR: $*" >&2; exit 1; }
command -v docker >/dev/null || die "Install Docker on the router first"
command -v curl >/dev/null || die "Install curl on the router first"
docker info >/dev/null 2>&1 || die "Docker daemon is not running"

if docker container inspect "$name" >/dev/null 2>&1; then
    actual_image=$(docker inspect --format '{{.Config.Image}}' "$name")
    restart=$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$name")
    network=$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$name")
    privileged=$(docker inspect --format '{{.HostConfig.Privileged}}' "$name")
    ports=$(docker inspect --format '{{range $p, $bindings := .HostConfig.PortBindings}}{{range $bindings}}{{if .HostIp}}{{.HostIp}}{{else}}0.0.0.0{{end}}:{{.HostPort}}:{{$p}}{{"\n"}}{{end}}{{end}}' "$name")
    mounts=$(docker inspect --format '{{range .Mounts}}{{.Type}}|{{.Source}}|{{.Destination}}|{{.RW}}{{"\n"}}{{end}}' "$name")
    test "$actual_image" = "$image" && test "$restart" = always &&
        test "$privileged" = false &&
        test "$ports" = "$bind_address:$port:25500/tcp" &&
        test "$mounts" = "bind|$config_dir|/data|true" ||
        die "Container $name differs from requested image/ports/mount/restart settings; left unchanged. Inspect it or use --name for a separate deployment."
    case "$network" in default|bridge) ;; *) die "Container $name uses a different network; left unchanged" ;; esac
    if test "$(docker inspect --format '{{.State.Running}}' "$name")" = true; then
        echo "Matching container $name is already running; no restart."
    else
        docker start "$name" >/dev/null
        echo "Started existing container $name."
    fi
else
    # Pull only when absent; rerunning never silently updates a mutable tag.
    docker image inspect "$image" >/dev/null 2>&1 || docker pull "$image"
    mkdir -p "$config_dir"
    docker run -d --name "$name" --restart always --network bridge \
        --publish "$bind_address:$port:25500/tcp" \
        --mount "type=bind,src=$config_dir,dst=/data" "$image" >/dev/null
    echo "Created container $name."
fi
check_host=$bind_address
test "$check_host" != 0.0.0.0 || check_host=127.0.0.1
attempt=0
while test "$attempt" -lt 15; do
    if version=$(curl --noproxy '*' -fsS --connect-timeout 2 --max-time 3 "http://$check_host:$port/version" 2>/dev/null); then
        case "$version" in
            *subconverter*)
                echo "Ready: $version"
                echo "Image: $image; TCP port: $port; persistent data: $config_dir -> /data"
                exit 0 ;;
        esac
    fi
    attempt=$((attempt + 1))
    sleep 2
done
die "Container exists but /version is not ready. Check: docker logs $name. No container or config files were deleted."
REMOTE
