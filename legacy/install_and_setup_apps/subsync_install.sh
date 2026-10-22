#!/usr/bin/env bash

# subsync: synchronize .srt or .ssa subtitles with the video timeline

# add 12000 milliseconds to all time stamps in source.ass
# subsync +12000 < source.ass > target.ass

cd ~/git/Downloads
git clone https://github.com/xuminic/subsync.git
cd subsync
make
cp subsync ~/bin
