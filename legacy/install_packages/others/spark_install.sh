#!/usr/bin/env bash

cd ~/Downloads/bin/

latest_version=$(lastversion spark)
bin_name=spark-$latest_version-bin-hadoop2.7
tgz_file=spark-$latest_version-bin-hadoop2.7.tgz

wget https://mirrors.tuna.tsinghua.edu.cn/apache/spark/spark-$latest_version/$tgz_file
# aria2c https://ftp.kddi-research.jp/infosystems/apache/spark/spark-$latest_version/$tgz_file

tar xvf $tgz_file

sudo mv $bin_name /opt/spark
