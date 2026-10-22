#!/usr/bin/env bash

# sudo snap install flutter --classic

sudo apt-get install -y clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev
# sudo apt-get install -y default-jre default-jdk

# # Install Android Studio
# sudo snap install android-studio --classic

# flutter config --android-studio-dir /snap/android-studio/current/android-studio

# # snap version of sdkmanager
# sudo snap install androidsdk
# androidsdk --install "cmdline-tools;latest"
# $HOME/AndroidSDK/cmdline-tools/latest/bin/sdkmanager --sdk_root=$HOME/Android/Sdk --install "cmdline-tools;latest"

# ### Then open andrioid studio to finish setup and android-sdk downloading.

# # Accept android licenses
# flutter doctor --android-licenses

# # Run flutter doctor to see if everything is OK
# flutter doctor


# snap version has cmake dependency issue, try using git clone to install
cd $HOME/git/Downloads/
git clone https://github.com/flutter/flutter.git -b stable
