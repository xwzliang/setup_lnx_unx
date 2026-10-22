#!/usr/bin/env bash

# MS sql server
mvn org.apache.maven.plugins:maven-dependency-plugin:get -Dartifact=com.microsoft.sqlserver:mssql-jdbc:9.2.1.jre11

# PostgreSQL
mvn org.apache.maven.plugins:maven-dependency-plugin:get -Dartifact=org.postgresql:postgresql:42.2.20

# MySQL
mvn org.apache.maven.plugins:maven-dependency-plugin:get -Dartifact=mysql:mysql-connector-java:8.0.25

# SQLite
mvn org.apache.maven.plugins:maven-dependency-plugin:get -Dartifact=org.xerial:sqlite-jdbc:3.34.0
