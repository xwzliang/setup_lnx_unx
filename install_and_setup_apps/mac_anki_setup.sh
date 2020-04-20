#!/usr/bin/env bash

# Starting with Mac OS X Mavericks, a feature named App Nap has been introduced to the operating system. This feature causes certain applications which are open (but not visible) to be placed in a suspended state. As this behavior causes AnkiConnect to stop working while you have another window in the foreground, App Nap should be disabled for Anki:
defaults write net.ankiweb.dtop NSAppSleepDisabled -bool true
defaults write net.ichi2.anki NSAppSleepDisabled -bool true
defaults write org.qt-project.Qt.QtWebEngineCore NSAppSleepDisabled -bool true
