#!/usr/bin/env bash

my_dirs=(
	~/bin
	~/tmp
	~/git/Downloads
	~/pipes/zotero
	~/pipes/pdf_img
	~/Downloads/books
	~/Downloads/bin
	~/Downloads/tutorials
	~/Downloads/videos
	~/Downloads/audios
)

for my_dir in "${my_dirs[@]}"; do
	mkdir -p $my_dir
done
