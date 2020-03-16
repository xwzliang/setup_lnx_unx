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
