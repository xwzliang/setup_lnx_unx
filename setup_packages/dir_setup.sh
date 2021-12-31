#!/usr/bin/env bash

my_dirs=(
	~/bin
	~/venv
	~/tmp
    ~/git/Downloads
	~/pipes/zotero
	~/pipes/pdf_img
	~/pipes/pdftohtml
	~/Downloads/git
	~/Downloads/books
	~/Downloads/bin
	~/Downloads/tutorials
	~/Downloads/videos
	~/Downloads/audios
	~/Downloads/tmp
	~/Dropbox/org/roam
)

for my_dir in "${my_dirs[@]}"; do
	mkdir -p $my_dir
done

my_files=(
	~/pipes/zotero/linked_url
	~/pipes/zotero/amazon_book.html
)

for my_file in "${my_files[@]}"; do
	touch $my_file
done
