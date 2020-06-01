#!/usr/bin/env bash

dir="$(dirname "$0")"

install_package_script=$HOME/.emacs.d/emacs_install_packages.el

cat << _EOF_ >$install_package_script
(require 'package)

; find package information from following archives
(setq package-archives '(("gnu" . "http://elpa.gnu.org/packages/")
                         ("melpa" . "https://melpa.org/packages/")))
(add-to-list 'package-archives '("org" . "https://orgmode.org/elpa/") t)

; list of packages
(setq package-list
    '(
      clues-theme                           ; An Emacs theme, which is approaching awesomeness
      evil                                  ; The extensible vi layer for Emacs.
      evil-collection                       ; A set of keybindings for evil-mode
      use-package                           ; The use-package macro allows you to isolate package configuration in your .emacs file in a way that is both performance-oriented and, well, tidy. Also can auto-install package and warn instead of give error when certain package is lacking.
      smartparens                           ; Minor mode for Emacs that deals with parens pairs and tries to be smart about it.
      magit                                 ; Magit is an interface to the version control system Git, implemented as an Emacs package. Magit aspires to be a complete Git porcelain.
      evil-magit                            ; This library configures Magit and Evil to play well with each other.
      git-gutter                            ; Emacs port of GitGutter
      evil-surround                         ; This package emulates surround.vim
      evil-nerd-commenter                   ; Comment/uncomment lines efficiently. Like Nerd Commenter in Vim
      neotree                               ; A Emacs tree plugin like NerdTree for Vim.
      helm                                  ; Helm is an Emacs framework for incremental completions and narrowing selections.
      insert-shebang                        ; Insert shebang line automatically for Emacs.
      w3m                                   ; An Emacs interface to w3m
      restart-emacs                         ; This is a simple package to restart Emacs for within Emacs.
      helm-descbinds                        ; Helm Descbinds provides an interface to emacs’ describe-bindings making the currently active key bindings interactively searchable with helm.
      projectile                            ; a project interaction library for Emacs
      helm-projectile                       ; Helm integration for Projectile
      bm                                    ; This package provides visible, buffer local, bookmarks and the ability to jump forward and backward to the next bookmark.
      hydra                                 ; This is a package for GNU Emacs that can be used to tie related commands into a family of short bindings with a common prefix - a Hydra.
      iedit                                 ; Edit multiple regions simultaneously in a buffer or a region
      evil-iedit-state                      ; Slick Evil states for iedit.
      ggtags                                ; Emacs frontend to GNU Global source code tagging system.
      helm-gtags                            ; GNU GLOBAL helm interface
      persp-mode                            ; named perspectives(set of buffers/window configs) for emacs
      yasnippet                             ; A template system for Emacs, It allows you to type an abbreviation and automatically expand it into function templates.
      yasnippet-snippets                    ; a collection of yasnippet snippets for many languages
      helm-c-yasnippet                      ; Helm source for yasnippet
      auto-yasnippet                        ; quickly create disposable yasnippets
      company                               ; Modular in-buffer completion framework for Emacs
      helm-company                          ; Helm interface for company-mode
      expand-region                         ; Emacs extension to increase selected region by semantic units.
      ibuffer-vc                            ; Group buffers in ibuffer list by VC project
      flycheck                              ; On the fly syntax checking for GNU Emacs
      golden-ratio                          ; Automatic resizing of Emacs windows to the golden ratio
      company-c-headers                     ; Auto-completion for C/C++ headers using Company
      pdf-tools                             ; Emacs support library for PDF files.
      calfw                                 ; A calendar framework for Emacs
      calfw-org                             ; A calendar framework for Emacs org-mode
      evil-org                              ; Supplemental evil-mode keybindings to emacs org-mode
      org-brain                             ; Org-mode wiki + concept-mapping
      org-ref                               ; org-mode modules for citations, cross-references, bibliographies in org-mode and useful bibtex tools to go with it.
      anki-editor                           ; Emacs minor mode for making Anki cards with Org
      org-plus-contrib                      ; Org-mode Contributed Packages (https://orgmode.org/worg/org-contrib/)
      general                               ; Convenience wrappers for keybindings
      auto-package-update                   ; Automatically update Emacs packages.
      forge                                 ; Work with Git forges from the comfort of Magit
      helm-swoop                            ; helm-swoop allows to show interactively lines (in one or multiple buffers) that match a pattern in another (helm) buffer
      helm-ag                               ; The silver searcher with helm interface
      macrostep                             ; interactive macro-expander for Emacs
      evil-exchange                         ; Port of vim-exchange
      evil-replace-with-register			; Port of vim ReplaceWithRegister
      evil-visualstar                       ; Port of one of the many visual-star plugins for Vim. Start a * or # search from the visual selection
      evil-lion                             ; Evil align operator
      evil-numbers                          ; Increment and decrement numbers in Emacs
      evil-args                             ; Motions and text objects for delimited arguments in Evil
      evil-indent-plus                      ; Better indent textobjects for evil
      evil-visual-mark-mode                 ; Display evil marks on buffer
      anzu                                  ; Emacs port of anzu.vim. anzu.el provides a minor mode which displays current match and total matches information in the mode-line
      evil-anzu                             ; anzu for Evil
      evil-mc                               ; Multiple cursors implementation for evil-mode
      avy                                   ; Jump to things in Emacs tree-style
      delight                               ; Enables you to customise the mode names displayed in the mode line.
      helm-make                             ; Select a Makefile target with helm
      git-timemachine                       ; Git time machine
      gitignore-mode                        ; Emacs major modes for Git ignore files
      gitconfig-mode                        ; Emacs major modes for Git config files
      gitattributes-mode                    ; Emacs major modes for Git attributes files
      define-word                           ; Lets you see the definition of a word or a phrase at point, without having to switch to a browser
      magit-gitflow                         ; GitFlow plugin for magit
      linum-relative                        ; Display relative line number in the left margin in emacs
      evil-textobj-line                     ; Evil Line text object
      exato                                 ; This package provides the x text object to manipulate html/xml tag attributes
      evil-textobj-syntax                   ; This package is a port of vim-textobj-syntax for emacs. It provides evil text objects for consecutive items with same syntax highlight.
      evil-cleverparens                     ; Evil normal-state minor-mode for editing lisp-like languages
      emamux                                ; tmux manipulation from Emacs
      which-key                             ; Emacs package that displays available keybindings in popup
      helpful                               ; A better Emacs *help* buffer
      deft                                  ; Deft is an Emacs mode for quickly browsing, filtering, and editing directories of plain text notes
      howm                                  ; a note-taking tool on Emacs. It is similar to emacs-wiki.el
      undo-propose                          ; Navigate the emacs undo history by staging undo's in a temporary buffer
      org-projectile                        ; Manage org-mode TODOs for your projectile projects
      f                                     ; Modern API for working with files and directories in Emacs
      hl-todo                               ; Highlight TODO keywords
      magit-todos                           ; Show source files' TODOs (and FIXMEs, etc) in Magit status buffer
      rg                                    ; Emacs search tool based on ripgrep
      helm-rg                               ; Search massive codebases extremely fast, using ripgrep and helm
      helm-firefox                          ; Display firefox bookmarks with emacs helm interface
      org-pomodoro                          ; pomodoro technique for org-mode
      org-present                           ; Ultra-minimalist presentation minor-mode for Emacs org-mode
      doom-modeline                         ; A fancy and fast mode-line inspired by minimalism design
      hide-mode-line                        ; An Emacs plugin that hides (or masks) the current buffer's mode-line
      eshell-z                              ; cd to frequent directory in eshell, Emacs port of z
      org-web-tools                         ; View, capture, and archive Web pages in Org-mode
      transpose-frame                       ; Transpose windows arrangement in a frame
      helm-org-rifle                        ; searches rapidly through org files
      org-ql                                ; An Org-mode query language, including search commands and saved views
      org-board                             ; Org mode's web archiver
      org-timeline                          ; Add graphical view of agenda timeline to agenda buffer
      org-super-agenda                      ; Supercharge your Org daily/weekly agenda by grouping items
      origami                               ; A folding minor mode for Emacs (works with org agenda)
      nov                                   ; Major mode for reading EPUBs in Emacs
      org-noter                             ; Emacs document annotator, using Org-mode
      org-roam                              ; Rudimentary Roam replica with Org-mode
      org-journal                           ; A simple org-mode based journaling mode
      org-download                          ; Drag and drop images to Emacs org-mode
      el-patch                              ; el-patch provides a way to customize the behavior of Emacs Lisp functions
      fzf                                   ; A front-end for fzf
      company-quickhelp                     ; Documentation popup for Company
      company-quickhelp-terminal            ; Terminal support for company-quickhelp
      popup                                 ; Visual Popup Interface Library for Emacs
      elpy                                  ; Emacs Python Development Environment
      highlight-indentation                 ; Minor modes to highlight indentation guides in emacs
      realgud                               ; The Grand "Cathedral" Debugger rewrite
      company-statistics                    ; Sort completion candidates by previous completion choices
      company-web                           ; Emacs company backend for html, jade, slim
      blacken                               ; Use the python black package to reformat your python buffers
      py-isort                              ; py-isort.el integrates isort into Emacs
      proxy-mode                            ; A minor mode to toggle proxy for Emacs. Supports HTTP proxy and socks v4, v5 proxy with Emacs built-in functions
      python-docstring                      ; Emacs minor-mode for editing Python docstrings
      sphinx-doc                            ; Generate Sphinx friendly docstrings for Python functions in Emacs
      pyenv-mode                            ; Integrate pyenv with python-mode
      list-environment                      ; A tabulated process environment editor
      format-all                            ; Auto-format source code in many languages with one command
      pippel                                ; Emacs frontend to python package manager pip
      elisp-slime-nav                       ; Slime-style navigation of Emacs Lisp source with M-. & M-,
      keyfreq                               ; Track Emacs commands frequency
      elmacro                               ; Package to display keyboard macros or latest interactive commands as emacs lisp
      ace-window                            ; Quickly switch windows in Emacs
      emr                                   ; language-specific refactoring in Emacs
      eros                                  ; Evaluation Result inline OverlayS for Emacs Lisp
      nix-mode                              ; An Emacs major mode for editing Nix expressions
      eshell-prompt-extras                  ; Display extra information and color for your eshell prompt
      exec-path-from-shell                  ; Make Emacs use the PATH set up by the user's shell
      eshell-up                             ; Quickly go to a specific parent directory in eshell
      eshell-did-you-mean                   ; command not found ("did you mean…" feature) in Eshell
      fish-completion                       ; Emacs fish completion
      fish-mode                             ; Emacs major mode for fish shell scripts
                                            ;;      vterm ; Emacs libvterm integration
      json-reformat                         ; Reformat tool for JSON
      json-snatcher                         ; Get the path to a JSON element in Emacs
      json-mode                             ; Major mode for editing JSON files with emacs
      dockerfile-mode                       ; An emacs mode for handling Dockerfiles
      docker                                ; Manage docker from Emacs
      jq-mode                               ; Emacs major mode for editing jq queries, can also be used interactively in a JSON buffer
      lsp-mode                              ; Emacs client/library for the Language Server Protocol
      helm-lsp                              ; Helm lsp integration
      rainbow-delimiters                    ; Emacs rainbow delimiters mode which highlights delimiters such as parentheses, brackets or braces according to their depth
      page-break-lines                      ; Emacs: display ugly ^L page breaks as tidy horizontal lines
      ert-runner                            ; Ert-runner is a tool for Emacs projects tested using Ert
      overseer                              ; Ert-runner Integration Into Emacs
      helm-bibtex                           ; A bibliography manager based on Helm
      bibtex-completion                     ; A BibTeX backend for completion frameworks
      quickrun                              ; Run command quickly. This packages is inspired quickrun.vim
      mmm-mode                              ; a minor mode for Emacs that allows Multiple Major Modes to coexist in one buffer
  ))

; activate all the packages
(package-initialize)

; fetch the list of packages available
(unless package-archive-contents
  (package-refresh-contents))

; do package-refresh-contents according to the value of argument 0
(if (string= "refresh" (elt argv 0))
  (package-refresh-contents))

; install the missing packages
(dolist (package package-list)
  (unless (package-installed-p package)
    (package-install package)))

(defun my-download-file-func (my-url-path my-download-package-dir-name my-download-files)
    (require 'url)
    (let ((my-download-dir (concat "~/.emacs.d/custom/" my-download-package-dir-name "/")))
        (add-to-list 'load-path my-download-dir)
        (make-directory my-download-dir t)
        (mapcar (lambda (arg)
                (let ((local-file (concat my-download-dir (car (last (split-string arg "/"))))))
                    (unless (file-exists-p local-file)
                    (url-copy-file (concat my-url-path arg) local-file t))))
                my-download-files)
        (byte-recompile-directory my-download-dir 0)
     )
 )

(defun my-download-file-github-func (my-download-github-repo my-download-files)
    (let ((my-download-github-full-path (concat "https://raw.githubusercontent.com/" my-download-github-repo "/master/"))
        ;; Use the repo name as dir name
        (my-download-package-dir-name (car (last (split-string my-download-github-repo "/")))))
        (my-download-file-func my-download-github-full-path my-download-package-dir-name my-download-files)
     )
 )

; Install Bookmark+ from the EmacsWiki
(let ((bookmarkplus-dir-name "bookmark-plus")
    (emacswiki-base "https://www.emacswiki.org/emacs/download/")
    (bookmark-files '("bookmark+.el" "bookmark+-mac.el" "bookmark+-bmu.el" "bookmark+-key.el" "bookmark+-lit.el" "bookmark+-1.el")))
    (my-download-file-func emacswiki-base bookmarkplus-dir-name bookmark-files)
)

;; Install from github

;; (my-download-file-github-func "hekinami/justify-kp" '("justify-kp.el"))

;; aweshell -- Awesome shell extension base on eshell with wonderful features!
(my-download-file-github-func "manateelazycat/aweshell" '("aweshell.el"))

;; doctest-mode.el --- Major mode for editing Python doctest files
(my-download-file-github-func "xwzliang/el-doctest-mode" '("doctest-mode.el"))

;; Delete anki-editor elc file if existed, this file will cause note id cannot be added.
(let ((filename (concat (concat (expand-file-name "~/.emacs.d/elpa/") (car (directory-files (expand-file-name "~/.emacs.d/elpa/") nil "^anki-editor"))) "/anki-editor.elc")))
    (if (file-exists-p filename)
        (delete-file filename)))

_EOF_

emacs --script $install_package_script || emacs --script $install_package_script refresh
