FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl e2fsprogs fdisk file gawk gettext \
    git libncurses-dev libssl-dev python3 rsync unzip wget xsltproc zlib1g-dev zstd \
    && rm -rf /var/lib/apt/lists/*
