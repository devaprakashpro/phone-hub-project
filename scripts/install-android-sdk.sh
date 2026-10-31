#!/usr/bin/env bash
# Installs a headless Android SDK (cmdline-tools + platform + build-tools) so the
# PhoneHub Android app can be built from the terminal without Android Studio.
set -euo pipefail

SDK="${ANDROID_HOME:-$HOME/Android}"
CLT_VER="11076708"   # commandlinetools build (Aug 2024); bump if newer
PLATFORM="android-34"
BUILDTOOLS="34.0.0"

echo "==> Installing Android SDK into $SDK"
mkdir -p "$SDK/cmdline-tools"
cd "$SDK/cmdline-tools"

if [ ! -d latest ]; then
  echo "==> Downloading command-line tools…"
  tmp="$(mktemp -d)"
  curl -L "https://dl.google.com/android/repository/commandlinetools-linux-${CLT_VER}_latest.zip" \
       -o "$tmp/clt.zip"
  unzip -q "$tmp/clt.zip" -d "$tmp"
  mv "$tmp/cmdline-tools" latest
  rm -rf "$tmp"
fi

export PATH="$SDK/cmdline-tools/latest/bin:$PATH"
yes | sdkmanager --sdk_root="$SDK" --licenses >/dev/null || true
echo "==> Installing platform-tools, $PLATFORM, build-tools;$BUILDTOOLS …"
sdkmanager --sdk_root="$SDK" \
  "platform-tools" "platforms;${PLATFORM}" "build-tools;${BUILDTOOLS}"

echo
echo "==> Done. Add to your shell rc:"
echo "    export ANDROID_HOME=$SDK"
echo "    export PATH=\$PATH:$SDK/platform-tools:$SDK/cmdline-tools/latest/bin"
echo
echo "Then from android/: ./gradlew assembleDebug   (Gradle wrapper self-bootstraps)"
