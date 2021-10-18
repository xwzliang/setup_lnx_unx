#!/usr/bin/env bash

go_packages_to_install=(
    github.com/lighttiger2505/sqls				# An implementation of the Language Server Protocol for SQL
    github.com/iawia002/annie					# Fast and simple video download library and CLI tool written in Go
    github.com/shuLhan/go-bindata/...			# This package converts any file into managable Go source code. Useful for embedding binary data into a go program
)

for go_package in "${go_packages_to_install[@]}"; do
    go get -u $go_package
    echo -e "${go_package} installed\n"
done

cp ~/go/bin/* ~/bin/
