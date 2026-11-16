#!/usr/bin/env bash
# 把 dist/TabletRecorder 打成 .deb（在 Linux CI 上运行）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/TabletRecorder"
VER="3.0.0"
PKG="$ROOT/build/deb"
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/usr/lib/tablet-recorder" "$PKG/usr/bin" "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"
cp -R "$APP/." "$PKG/usr/lib/tablet-recorder/"
ln -sf /usr/lib/tablet-recorder/TabletRecorder "$PKG/usr/bin/tablet-recorder"
cp "$ROOT/build/icon-256.png" "$PKG/usr/share/icons/hicolor/256x256/apps/tablet-recorder.png"
cat > "$PKG/usr/share/applications/tablet-recorder.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=安卓平板录屏助手
Comment=Android tablet screen recorder (adb + scrcpy + ffmpeg)
Exec=tablet-recorder
Icon=tablet-recorder
Terminal=false
Categories=AudioVideo;Recorder;
DESK
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: tablet-recorder
Version: $VER
Section: video
Priority: optional
Architecture: amd64
Maintainer: Toobe53 <vsrsopo@outlook.com>
Depends: libwebkit2gtk-4.1-0
Description: Android tablet screen recorder
 Live preview, screen+mic recording with A/V sync, audio meter,
 screenshot and demo push, built on adb + scrcpy + ffmpeg.
CONTROL
dpkg-deb --build --root-owner-group "$PKG" "$ROOT/dist/TabletRecorder-Linux.deb"
echo "built $ROOT/dist/TabletRecorder-Linux.deb"
