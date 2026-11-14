#!/usr/bin/env bash
# Build the benign DroidTrace test APK (x86_64 + arm64 native libs).
# Needs: Android SDK (build-tools, platforms/android-34), a JDK, Docker (for clang/lld).
set -euo pipefail
cd "$(dirname "$0")"
SDK=${ANDROID_HOME:-$HOME/Library/Android/sdk}
BT=$(ls -d "$SDK"/build-tools/* | sort -V | tail -1)
JAR=$(ls "$SDK"/platforms/android-*/android.jar | sort -V | tail -1)
JH=$(/usr/libexec/java_home 2>/dev/null || dirname "$(dirname "$(readlink -f "$(command -v javac)")")")
OUT=build; rm -rf $OUT; mkdir -p $OUT/classes $OUT/apk/lib/x86_64 $OUT/apk/lib/arm64-v8a $OUT/inc
cp "$JH"/include/jni.h "$OUT"/inc/; cp "$JH"/include/*/jni_md.h "$OUT"/inc/
: > "$OUT"/inc/stdio.h  # jni.h includes stdio.h; the library uses no libc

docker run --rm -v "$PWD":/w -w /w debian:trixie sh -c '
  apt-get update -qq && apt-get install -y -qq clang lld >/dev/null 2>&1
  for t in x86_64:x86_64 aarch64:arm64-v8a; do
    clang --target=${t%%:*}-linux-android21 -O1 -fPIC -shared -nostdlib -fuse-ld=lld \
      -Wl,-soname,libdtdemo.so -ffreestanding -Ibuild/inc jni/dtdemo.c -o build/apk/lib/${t##*:}/libdtdemo.so
  done'

javac --release 11 -nowarn -cp "$JAR" -d $OUT/classes src/org/droidtrace/demo/*.java
"$BT"/d8 --min-api 21 --lib "$JAR" --output $OUT/apk $(find $OUT/classes -name '*.class')
"$BT"/aapt2 link --manifest AndroidManifest.xml -I "$JAR" -o $OUT/base.apk
(cd $OUT/apk && zip -qr ../base.apk classes.dex lib)
"$BT"/zipalign -f -p 4 $OUT/base.apk $OUT/aligned.apk
[ -f $OUT/../debug.keystore ] || keytool -genkeypair -keystore debug.keystore -storepass android \
  -keypass android -alias dt -keyalg RSA -validity 3650 -dname "CN=DroidTrace Test" >/dev/null 2>&1
"$BT"/apksigner sign --ks debug.keystore --ks-pass pass:android --out droidtrace-demo.apk $OUT/aligned.apk
rm -rf $OUT
echo "built: $(pwd)/droidtrace-demo.apk"
