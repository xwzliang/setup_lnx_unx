#!/usr/bin/env bash

go_packages_to_install=(
    github.com/lighttiger2505/sqls				# An implementation of the Language Server Protocol for SQL
    github.com/iawia002/annie					# Fast and simple video download library and CLI tool written in Go
)

for go_package in "${go_packages_to_install[@]}"; do
    go get $go_package
    echo -e "${go_package} installed\n"
done
