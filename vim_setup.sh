#!/usr/bin/env  bash

vim_dir=$HOME/.vim
mkdir -p $vim_dir

# Define my filetypes in filetype.vim
cat << _EOF_ >$vim_dir/filetype.vim
" my filetype file
if exists("did_load_filetypes")
  finish
endif
augroup filetypedetect
  au! BufRead,BufNewFile *.sh		setfiletype bash | set syntax=sh
  au! BufRead,BufNewFile *.py		setfiletype python3 | set syntax=python
  " let is_bash=1 and set ft=sh to tell vim to use bash highlight mode instead of multipurpose default (sh, bash and ksh)
  au! BufRead,BufNewFile *.bats		setfiletype bats | set syntax=sh | let is_bash=1 | set ft=sh
augroup END
_EOF_
