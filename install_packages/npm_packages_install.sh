#!/usr/bin/env bash

npm_packages_to_install=(
    bash-language-server				# A language server for Bash
    bootstrap							# The most popular HTML, CSS, and JavaScript framework for developing responsive, mobile first projects on the web
    jquery								# jQuery JavaScript Library
    express								# Express is a minimal and flexible Node.js web application framework that provides a robust set of features for web and mobile applications
    nodemon								# Nodemon is a utility that will monitor for any changes in your source and automatically restart your server
    body-parser							# Parse incoming request bodies in a middleware before your handlers, available under the req.body property
    ejs									# Embedded JavaScript templates
    lodash								# A modern JavaScript utility library delivering modularity, performance, & extras
    mongodb								# MongoDB driver for Node.js. Provides a high-level API on top of mongodb-core that is meant for end users
    mongoose							# a MongoDB object modeling tool designed to work in an asynchronous environment
)

for npm_package in "${npm_packages_to_install[@]}"; do
    if ! npm -g ls $npm_package; then
        echo -e "${npm_package} not installed, will install it\n"
        npm install -g $npm_package
    else
        echo -e "${npm_package} already installed, will skip it"
    fi
done
