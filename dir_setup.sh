#!/usr/bin/env bash

my_dirs=(
	~/bin
	~/tmp
	~/pipes/zotero
	~/pipes/pdf_img
	~/Downloads/git
	~/Downloads/books
	~/Downloads/bin
	~/Downloads/tutorials
	~/Downloads/videos
	~/Downloads/audios
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
