#!/usr/bin/env bash

go_packages_to_install=(
    github.com/lighttiger2505/sqls				# An implementation of the Language Server Protocol for SQL
)

for go_package in "${go_packages_to_install[@]}"; do
    go get $go_package
done
