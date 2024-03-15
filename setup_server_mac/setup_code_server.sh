#!/usr/bin/env bash

curl -fsSL https://code-server.dev/install.sh | sh

code-server --bind-addr localhost:8081
