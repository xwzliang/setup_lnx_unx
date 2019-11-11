#!/usr/bin/env bash

dir="$(dirname "$0")"

install_package_script=$HOME/.emacs.d/emacs_install_packages.el

cat << _EOF_ >$install_package_script
(require 'package)

; find package information from following archives
(setq package-archives '(("gnu" . "http://elpa.gnu.org/packages/")
						 ("melpa" . "https://melpa.org/packages/")))

; list of packages
(setq package-list
    '(
	  clues-theme
	  use-package	; The use-package macro allows you to isolate package configuration in your .emacs file in a way that is both performance-oriented and, well, tidy. Also can auto-install package and warn instead of give error when certain package is lacking.
	  smartparens	; Minor mode for Emacs that deals with parens pairs and tries to be smart about it.
	  magit		; Magit is an interface to the version control system Git, implemented as an Emacs package. Magit aspires to be a complete Git porcelain.
	  evil-surround		; This package emulates surround.vim
	  evil-nerd-commenter	; Comment/uncomment lines efficiently. Like Nerd Commenter in Vim
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