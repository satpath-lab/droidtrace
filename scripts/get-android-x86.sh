#!/usr/bin/env bash
# Download Android-x86 9.0 (64-bit), check it against the official checksum, and unpack
# the boot files DroidTrace needs into images/x86_64/.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=images/x86_64
ISO=android-x86_64-9.0-r2.iso
SHA1=1cc85b5ed7c830ff71aecf8405c7281a9c995aa0   # from android-x86.org release notes
URL="https://downloads.sourceforge.net/project/android-x86/Release%209.0/$ISO"
mkdir -p "$DIR"

if [ ! -f "$DIR/$ISO" ]; then
  echo "==> Downloading $ISO (about 920 MB)"
  curl -fL --retry 3 -o "$DIR/$ISO.part" "$URL"
  mv "$DIR/$ISO.part" "$DIR/$ISO"
fi

echo "==> Checking file"
got=$( (command -v sha1sum >/dev/null && sha1sum "$DIR/$ISO" || shasum -a 1 "$DIR/$ISO") | cut -d' ' -f1)
[ "$got" = "$SHA1" ] || { echo "Checksum mismatch ($got). Delete $DIR/$ISO and retry."; exit 1; }

echo "==> Extracting boot files"
if command -v bsdtar >/dev/null; then X="bsdtar -xf"; elif tar --version 2>/dev/null | grep -q bsdtar; then X="tar -xf"
elif command -v 7z >/dev/null; then X="7z x -y -bd"; else
  echo "Need bsdtar or 7z (Debian/Ubuntu: apt install libarchive-tools)"; exit 1; fi
(cd "$DIR" && $X "$ISO" kernel initrd.img >/dev/null)
echo "==> Ready. Next: droidtrace prepare --config configs/android-x86.yaml"
