#!/usr/bin/env bash

. set_privoxy

# emacs --batch --eval '(print "working")'

# First use privoxy to bootstrap straight.el
emacs --batch --eval "$(cat <<'EOF'
    (progn
        ;; Bootstrap code for straight.el package manager
        (defvar bootstrap-version)
        (let ((bootstrap-file
            (expand-file-name "straight/repos/straight.el/bootstrap.el" user-emacs-directory))
            (bootstrap-version 5))
        (unless (file-exists-p bootstrap-file)
            (with-current-buffer
                (url-retrieve-synchronously
                "https://raw.githubusercontent.com/raxod502/straight.el/develop/install.el"
                'silent 'inhibit-cookies)
            (goto-char (point-max))
            (eval-print-last-sexp)))
        (load bootstrap-file nil 'nomessage))
    )
EOF
)"

. set_proxy
# Then use socks proxy to clone git repos
yes | emacs --batch --script ~/git/dot_emacs/init.el

