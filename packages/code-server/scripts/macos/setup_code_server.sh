#!/usr/bin/env bash

curl -fsSL https://code-server.dev/install.sh | sh

brew services start code-server
