#!/usr/bin/env bash

dir="$(dirname "$0")"

install_package_script=$HOME/.emacs.d/emacs_install_packages.el

cat << _EOF_ >$install_package_script
(require 'package)

; find package information from following archives
(setq package-archives '(("gnu" . "http://elpa.gnu.org/packages/")
						 ("marmalade" . "http://marmalade-repo.org/packages/")
						 ("melpa-stable" . "http://stable.melpa.org/packages/")))

; list of packages
(setq package-list
    '(
	  clues-theme
	  ))

; activate all the packages
(package-initialize)

; fetch the list of packages available
(unless package-archive-contents
  (package-refresh-contents))

; install the missing packages
(dolist (package package-list)
  (unless (package-installed-p package)
    (package-install package)))
_EOF_

emacs --script $install_package_script
