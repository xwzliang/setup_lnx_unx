#!/usr/bin/env bash

npm_packages_to_install=(
    moment								# A JavaScript date library for parsing, validating, manipulating, and formatting dates
    faker								# generate massive amounts of realistic fake data in Node.js and the browser
    @types/faker						# This package contains type definitions for faker
    @nestjs/jwt							# JWT utilities module for Nest based on the jsonwebtoken package
    @nestjs/passport					# Passport module for Nest framework
    passport-jwt						# A Passport strategy for authenticating with a JSON Web Token
    dayjs								# a minimalist JavaScript library that parses, validates, manipulates, and displays dates and times for modern browsers with a largely Moment.js-compatible API
    express-validator					# An express.js middleware for validator.js
    bash-language-server				# A language server for Bash
    typescript-language-server			# TypeScript & JavaScript Language Server
    typescript							# TypeScript is a language for application-scale JavaScript
    uuid								# RFC4122 (v1, v4, and v5) UUIDs
    bootstrap							# The most popular HTML, CSS, and JavaScript framework for developing responsive, mobile first projects on the web
    jquery								# jQuery JavaScript Library
    express								# Express is a minimal and flexible Node.js web application framework that provides a robust set of features for web and mobile applications
    nodemon								# Nodemon is a utility that will monitor for any changes in your source and automatically restart your server
    body-parser							# Parse incoming request bodies in a middleware before your handlers, available under the req.body property
    ejs									# Embedded JavaScript templates
    lodash								# A modern JavaScript utility library delivering modularity, performance, & extras
    mongodb								# MongoDB driver for Node.js. Provides a high-level API on top of mongodb-core that is meant for end users
    @types/mongodb						# TypeScript definitions for MongoDB
    mongoose							# a MongoDB object modeling tool designed to work in an asynchronous environment
    mongoose-encryption					# Simple encryption and authentication for mongoose documents
    newman								# the cli companion for postman
    dotenv								# Dotenv is a zero-dependency module that loads environment variables from a .env file into process.env
    # md5									# a JavaScript function for hashing messages with MD5
    bcrypt								# A library to help you hash passwords
    passport							# Passport is Express-compatible authentication middleware for Node.js
    passport-local						# Local username and password authentication strategy for Passport
    passport-local-mongoose				# Mongoose plugin that simplifies building username and password login with Passport
    express-session						# Simple session middleware for Express
    mongoose-findorcreate				# Simple plugin for Mongoose which adds a findOrCreate method to models. This is useful for libraries like Passport which require it
    react								# React is a JavaScript library for creating user interfaces
    react-dom							# React package for working with the DOM
    react-scripts						# Configuration and scripts for Create React App
    @material-ui/core					# React components that implement Google's Material Design
    @material-ui/icons					# Material Design Svg Icons converted to Material-UI React components
    serverless							# Serverless Framework - Build web, mobile and IoT applications with serverless architectures using AWS Lambda, Azure Functions, Google CloudFunctions
    serverless-offline					# Emulate AWS λ and API Gateway locally when developing your Serverless project
    @nestjs/cli							# A progressive Node.js framework for building efficient, reliable and scalable server-side applications
    @nestjs/mongoose					# Mongoose module for Nest
    @types/mongoose						# TypeScript definitions for Mongoose
    class-validator						# Class-based validation with Typescript / ES6 / ES5 using decorators or validation schemas
    class-transformer					# Proper decorator-based transformation / serialization / deserialization of plain javascript objects to class constructors
    typeorm								# Data-Mapper ORM for TypeScript
    @nestjs/typeorm						# TypeORM module for Nest framework
    jest								# Delightful JavaScript Testing
    @alicloud/fun						# Fun is a development tool for serverless applications
)

for npm_package in "${npm_packages_to_install[@]}"; do
    if ! npm -g ls $npm_package; then
        echo -e "${npm_package} not installed, will install it\n"
        npm install -g $npm_package
    else
        echo -e "${npm_package} already installed, will skip it"
    fi
done
