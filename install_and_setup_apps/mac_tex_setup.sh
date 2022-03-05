#!/usr/bin/env bash

# Probably need 12G free space

# Try basictex first, it's much smaller.
brew install --cask basictex
# brew install --cask mactex

# for MacTex CLI tools to take effect
eval "$(/usr/libexec/path_helper)"

# sudo tlmgr update --self

# For emacs-mac org mode export pdf.
# sudo tlmgr install wrapfig
# sudo tlmgr install capt-of
