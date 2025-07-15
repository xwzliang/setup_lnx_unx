#!/bin/bash

get_timezone() {
  if command -v timedatectl >/dev/null 2>&1; then
    timedatectl | grep "Time zone" | awk '{print $3}'
  elif [ -f /etc/timezone ]; then
    cat /etc/timezone
  elif readlink /etc/localtime >/dev/null 2>&1; then
    readlink /etc/localtime | sed 's|.*/zoneinfo/||'
  else
    date +%Z
  fi
}

timezone=$(get_timezone)
echo "Detected timezone: $timezone"

docker volume create n8n_data
docker run -d  --restart always --add-host=host.docker.internal:host-gateway --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n -v /Users/broliang:/files -e NODE_FUNCTION_ALLOW_BUILTIN='*' -e NODE_FUNCTION_ALLOW_EXTERNAL='*' -e GENERIC_TIMEZONE=$timezone docker.n8n.io/n8nio/n8n