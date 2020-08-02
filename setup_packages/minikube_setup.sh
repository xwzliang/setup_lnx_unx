#!/usr/bin/env bash

## I cannot find a way to pull image from k8s.gcr.io, no matter using proxy or not


# mkdir -p /etc/systemd/system/docker.service.d

# cat <<EOF >/etc/systemd/system/docker.service.d/http-proxy.conf
# [Service]
# Environment="HTTP_PROXY=http://127.0.0.1:8118"
# Environment="HTTPS_PROXY=https://127.0.0.1:8118"
# EOF

# systemctl daemon-reload; systemctl restart docker

# mkdir -p /etc/sysconfig

# cat <<EOF >/etc/sysconfig/docker
# export HTTP_PROXY="http://127.0.0.1:8118"
# export HTTPS_PROXY="https://127.0.0.1:8118"
# EOF

# service docker restart


# This workaround works
docker pull anjone/kicbase

minikube start --driver=docker --base-image="anjone/kicbase"
