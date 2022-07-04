#!/usr/bin/env bash

# brew install flutter
cd $HOME/git/Downloads/
git clone https://github.com/flutter/flutter.git -b stable

brew install --cask chromedriver

brew install android-studio

### Then open andrioid studio to finish setup and android-sdk downloading.

# Install android studio command line tools
# Have to use an older version of java (java 8)
export JAVA_HOME=$(/usr/libexec/java_home -v 1.8)
~/Library/Android/sdk/tools/bin/sdkmanager --install "cmdline-tools;latest"

# Setup xcode
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -runFirstLaunch

# CocoaPods is used to retrieve the iOS and macOS platform side's plugin code that responds to your plugin usage on the Dart side. Without CocoaPods, plugins will not work on iOS or macOS.
gem install cocoapods

# Accept android licenses
flutter doctor --android-licenses

# Run flutter doctor to see if everything is OK
flutter doctor
