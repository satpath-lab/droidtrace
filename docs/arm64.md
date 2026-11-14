# Tracing arm64-v8a apps

Most Android apps today ship their native code only for **arm64-v8a** (`lib/arm64-v8a/*.so`
inside the APK). Here is what that means for DroidTrace and how to trace them.

## Why the quick-start phone can't run them

The quick start uses **Android-x86**, an x86_64 build of Android. It can run x86_64 and x86
native code, and translate 32-bit ARM code, but it **cannot run arm64-v8a code**.

DroidTrace checks this for you. If an APK only has arm64-v8a code and the phone is x86_64, it
stops before installing and tells you, instead of failing in a confusing way:

```text
this APK only contains native code for arm64-v8a, but this virtual phone runs x86_64, x86,
armeabi-v7a, armeabi. Use a matching Android image (for arm64-v8a apps see docs/arm64.md).
```

Check which code an APK contains with: `unzip -l app.apk | grep lib/`

## What is already in place for arm64

- The **fast built-in tracer** (`qemu-patch/`) was written for arm64 first, and is tested on
  arm64 programs running on real QEMU: same results as the plugin, about 7× faster.
- Register names, float registers (`v0`–`v7`), string capture and process verification
  (`TTBR0_EL1`) are all arm64-aware.

The missing piece is an **arm64 Android image that boots on normal (upstream) QEMU**. I have
not tested a full arm64 Android end to end yet, so treat the steps below as experimental, and
please open an issue with what you find.

## Option A: Cuttlefish arm64 (recommended)

[Cuttlefish](https://source.android.com/docs/devices/cuttlefish) is Google's official virtual
Android device. It can run on QEMU, which lets it use DroidTrace's patched QEMU.

**You need:** a Linux machine (ideally arm64, e.g. a cloud ARM server; on x86_64 it works but
is much slower), about 30 GB of disk and 8 GB of RAM.

```bash
# 1. Build the patched QEMU (or copy /opt/qemu out of the DroidTrace Docker image)
curl -sfL https://download.qemu.org/qemu-10.0.3.tar.xz | tar xJ
sh droidtrace/qemu-patch/apply.sh qemu-10.0.3
cd qemu-10.0.3 && ./configure --target-list=aarch64-softmmu --enable-slirp && make -j4 && cd ..

# 2. Install Cuttlefish and download an arm64 phone image (aosp_cf_arm64_phone) from
#    https://ci.android.com, following Google's Cuttlefish guide.

# 3. Tell the patched QEMU where to write the trace, then start Cuttlefish on it
eval "$(droidtrace attach-env --out runs/arm64-app)"
launch_cvd --vm_manager=qemu_cli --qemu_binary_dir="$PWD/qemu-10.0.3/build" --daemon

# 4. Trace the app on the running phone
droidtrace run app.apk --attach 127.0.0.1:6520 --out runs/arm64-app
```

`--attach` skips starting a phone and uses the one at that adb address. Everything else works
the same: library discovery, process verification, the live viewer and exports.

## Option B: your own AOSP build

If you build AOSP yourself, any arm64 target that boots on QEMU's `virt` machine works. Point
the `emulator:` section of a config at its kernel, initrd and disk images (see
`configs/default.yaml`) and use `droidtrace prepare` / `run` as usual.

## Why not the Android Studio emulator?

It is based on QEMU 2.12 from 2018, which has no tracing support, and it uses hardware
acceleration, which skips the software CPU that instruction tracing needs.
