# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-14

First public release.

### Tracing
- Built-in tracer compiled into patched QEMU 10.0.3 (`qemu-patch/`): about 7× faster than the
  plugin with identical output. Default engine for arm64 (`--engine builtin|plugin`).
- Portable QEMU plugin engine for any QEMU 10+, arm64 and x86_64.
- Only the target app is recorded: libraries are found from the app's memory map, and the
  process is confirmed through its page-table base.
- Register capture before each instruction, including float registers, plus the memory behind
  pointer arguments, so strings are visible.
- Hard trace-size cap for both engines (`--max-size`, 2 GB by default).
- Versioned binary trace format (v2) with JSONL, CSV and Parquet export.

### Running apps
- `droidtrace prepare` boots Android once and saves a snapshot; `droidtrace run` resumes it in seconds.
- Android-x86 9.0 support with `scripts/get-android-x86.sh` (download plus checksum check).
- `droidtrace doctor`, `view`, `info` and `export` commands.
- Harmless demo APK (`tests/apk/`) that decrypts a hidden URL in native code.

### Live viewer
- Streams instructions into the browser as the app runs, with readable values: text, numbers,
  characters, floats and library pointers. Changed values are highlighted.
- Deep links: `?find=<text>` jumps to the first instruction whose registers contain the text,
  `?cols=rdi,rcx` picks register columns, and `?once=1` opens a finished trace without streaming.
- Text that is still being written is shown as it builds up (`"http://c2.exam…"`).

### Project
- One-step installer, Docker image, CI (unit tests, lint, format, types, end-to-end tests on
  real QEMU, CodeQL), and a deployment guide for shared and air-gapped environments.
