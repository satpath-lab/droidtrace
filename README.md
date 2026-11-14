<div align="center">

# 🔬 DroidTrace

### See every instruction an Android app runs, live.

Drop in an APK and watch its native code execute line by line, with every register
turned into something you can read: text, numbers, pointers.

[![CI](https://github.com/satpath-lab/droidtrace/actions/workflows/ci.yml/badge.svg)](https://github.com/satpath-lab/droidtrace/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![QEMU 10](https://img.shields.io/badge/QEMU-10.0-orange)
![Android](https://img.shields.io/badge/Android-arm64%20%7C%20x86__64-3ddc84)
[![Views](https://hits.sh/github.com/satpath-lab/droidtrace.svg?label=views&color=8957e5)](https://hits.sh/github.com/satpath-lab/droidtrace/)

<img src="docs/images/viewer-decrypted-url.png" alt="DroidTrace catching a hidden URL as it is decrypted" width="960">

<sub>A real capture: the demo app decrypts a hidden URL inside its native code, and the decoded
text shows up in register <code>rdi</code> the moment it is written.</sub>

[Quick start](#-quick-start) •
[How it works](#-how-it-works) •
[Screenshots](#-screenshots) •
[Limitations](#%EF%B8%8F-limitations) •
[Using it at work](#-using-it-at-work) •
[FAQ](#-faq)

</div>

---

## 👋 Why I built this

When I analyse an Android app, the interesting part is usually hidden in its native code
(`.so` files): decrypting strings, checking for root, talking to a server. Reading that code
statically is slow, and debuggers stop the app at every step.

I wanted something simpler: **run the app and get a complete recording of what its native
code did**, instruction by instruction, with the values it worked on. So I built DroidTrace.

## 🕵️ Hidden strings, revealed

Malware rarely stores a server address in plain text. My demo app does what real samples do:
it keeps the URL scrambled and decrypts it only at runtime. DroidTrace catches it in the act:

<table>
<tr>
<td width="55%">
<img src="docs/images/hidden-url-closeup.png" alt="Scrambled bytes in rcx, decrypted URL in rdi" width="100%">
</td>
<td>

**`rcx`** points at what is stored inside the app:
`2..*`uu9ht?";7*6?t34,;63>u=;.?`
— meaningless bytes.

**`rdx`** holds the character being decrypted right now: `'e'`.

**`rdi`** points at the output, which now reads
**`http://c2.example.invalid/gate`**.

No reverse engineering needed: I just ran the app and read the result.

</td>
</tr>
</table>

And in the live viewer you can watch the URL being built, one letter per loop round, in the
`rdi` column (text values are shown in green):

<img src="docs/images/url-growing.png" alt="The rdi column in the live viewer showing the URL being decrypted letter by letter" width="960">

<sub>Open it yourself with <code>http://127.0.0.1:8765/?find=c2.example&cols=rdi,rcx,rax,rdx</code>:
<code>find</code> jumps to the first instruction whose registers contain that text, and
<code>cols</code> picks which registers to show as columns.</sub>

## ✨ What you get

| | |
|---|---|
| 📍 **Where** | which library ran (`libc.so`, the app's own `libpayload.so`, …) and the exact offset |
| 🧠 **What** | the instruction itself, e.g. `mov x0, x1` or `call connect` |
| 🔢 **Values** | every CPU register at that moment |
| 🔤 **Meaning** | values turned into plain text: `"http://evil.example/gate"`, `-1`, `3.14`, `'e'`, `libc.so+0x1234` |
| 🎯 **Focus** | only the app you are analysing is recorded, not the rest of the phone |
| 📡 **Live** | everything streams into your browser while the app is running |
| 💾 **Export** | save the trace and export it to JSONL, CSV or Parquet |

## 🚀 Quick start

**You need:** Docker, about **12 GB of free disk** while installing (around 5 GB once
installed), and **8 GB of RAM** (the virtual phone uses 2 GB). I built and tested it on an
8 GB Apple Silicon Mac; Linux works too.

```bash
# 1. Get the code and install the `droidtrace` command
git clone https://github.com/satpath-lab/droidtrace.git
cd droidtrace
./install.sh

# 2. Download a virtual Android phone (Android-x86 9.0, ~920 MB, checksum verified)
scripts/get-android-x86.sh

# 3. Boot it once and save it (one time only, 10-30 minutes)
droidtrace prepare --config configs/android-x86.yaml

# 4. Run an app and watch it live (starts in seconds from now on)
droidtrace run my-app.apk --config configs/android-x86.yaml
```

Your browser opens at **http://127.0.0.1:8765** and the trace starts flowing.

> 💡 **Try it safely first.** I included a harmless demo app that hides a URL the way malware
> often does. Run it and watch the URL appear:
> ```bash
> droidtrace run tests/apk/droidtrace-demo.apk --config configs/android-x86.yaml
> ```
> Then open **http://127.0.0.1:8765/?find=gate** to jump straight to the moment it is decrypted.

Not sure everything is set up? Run `droidtrace doctor`: it checks each piece and tells you
what is missing.

## 🧭 How it works

<img src="docs/images/how-it-works.png" alt="How DroidTrace works" width="900">

1. **A virtual phone.** DroidTrace starts Android inside QEMU (an emulator). The phone has no
   internet access and is reset after every run.
2. **Your app.** It installs your APK, opens it, and watches which native libraries it loads.
3. **The tracer.** Built into QEMU, it records each instruction those libraries run, together
   with every register value, and checks that it really came from your app.
4. **You.** The live viewer shows it as it happens, and the trace is saved for later.

The slow part (booting Android) happens once, in `droidtrace prepare`. After that every run
starts from a saved snapshot of the booted phone, in seconds.

## 📸 Screenshots

### Following the decryption step by step

<img src="docs/images/viewer-decrypted-url.png" alt="Live viewer with the decrypted URL selected" width="960">

How to read it, from left to right:

- **Left:** the library being traced, `libdtdemo.so`, and how many instructions it ran.
- **Middle:** each instruction in order. Offsets `0x450`-`0x461` are the decryption loop:
  `movzx` loads one scrambled byte, `xor dl, 0x5a` decrypts it, `mov` stores it.
- **Columns:** `rax` counts up to 30 (the URL length) and `rdx` shows each decrypted
  character as a number. Yellow cells changed since the row above.
- **Right:** every register of the selected row, decoded. A few rows later (`0x41a`-`0x41d`) the
  finished URL is passed to the function that would contact the server.
- **✓ target process verified:** the instruction really came from the app, not from another
  process on the phone.

### The end of the run

<img src="docs/images/viewer-overview.png" alt="Live viewer showing the end of a run" width="960">

On row 3815, `call qword ptr [rax + 0x538]` is the native code calling Android's
`NewStringUTF`, handing the decrypted text back to the Java side of the app.

### From the terminal

<img src="docs/images/terminal.png" alt="droidtrace commands in a terminal" width="820">

## 🎛️ Everyday commands

| I want to… | Command |
|---|---|
| check my setup | `droidtrace doctor` |
| run an app and watch it | `droidtrace run app.apk` |
| follow specific libraries | `droidtrace run app.apk --libs 'libnative*.so,libc.so'` |
| watch for longer | `droidtrace run app.apk --duration 300` |
| keep traces small | `droidtrace run app.apk --max-size 500` (MB) |
| reopen a saved trace | `droidtrace view runs/<run>/trace.dtr` |
| jump to a string | open the viewer with `?find=<text>`, e.g. `http://127.0.0.1:8765/?find=gate` |
| get the data out | `droidtrace export runs/<run>/trace.dtr --format csv -o trace.csv` |
| summarise a trace | `droidtrace info runs/<run>/trace.dtr` |

Every run gets its own folder under `runs/` with the trace, the list of libraries, the
emulator log and a `manifest.json` (APK hash, settings, timestamps), so results are easy to
archive and reproduce.

## ⚡ Two tracing engines

| Engine | Speed | Works with |
|---|---|---|
| **Built-in** (default on arm64) | fastest: about **7×** faster than the plugin | patched QEMU 10.0.3, arm64 Android |
| **Plugin** | slower | any QEMU 10+, arm64 and x86_64 Android |

Code outside the libraries you follow runs at normal emulator speed with either engine.

<details>
<summary>📊 Benchmark</summary>

700,000 traced instructions, each with 42 registers and string capture, on QEMU 10.0.3:

| | Time |
|---|---|
| No tracing | 0.04 s |
| Plugin engine | 1.99 s |
| **Built-in engine** | **0.29 s** |

Untraced code: about 2-5 % overhead with the plugin, none with the built-in engine.
</details>

## ✅ What I tested

| Test | Result |
|---|---|
| Android-x86 9.0 boots, `prepare` saves a snapshot, `run` resumes in seconds, all unattended | ✅ |
| Demo APK installs, launches, and its native library is found automatically | ✅ |
| Every instruction of the app's library recorded in order (3,821 in the latest run) | ✅ |
| Only the app's own process recorded (every record verified) | ✅ |
| Hidden URL readable the moment it is decrypted | ✅ |
| Live viewer, `view`, `info`, export to JSONL / CSV / Parquet | ✅ |
| Built-in and plugin engines produce identical traces (arm64 test program on real QEMU) | ✅ |
| Size cap stops recording before the disk fills | ✅ |
| Automated checks: unit tests, linting, type checking, end-to-end tests in CI | ✅ |
| Full arm64 Android image (AOSP / Cuttlefish) | ⏳ next, see limitations |

## ⚠️ Limitations

I want you to know exactly what DroidTrace can and cannot do:

- **It is slower than a real phone.** To see each instruction, the phone is emulated in
  software (no hardware acceleration). The first boot takes 10-30 minutes, and traced code
  runs much slower than normal. Follow only the libraries you care about.
- **It records native code only.** Java/Kotlin code runs inside Android's runtime (ART) and is
  not shown as Java source. DroidTrace is built for `.so` libraries.
- **Traces grow fast.** Each instruction takes a few hundred bytes, so millions of instructions
  mean gigabytes. A size cap (2 GB by default) stops recording when it is reached.
- **arm64 Android is not tested end to end yet.** The fast built-in engine is tested on arm64
  programs, and the full Android flow on Android-x86. A real arm64 Android image (AOSP or
  Cuttlefish) is my next step.
- **x86_64 Android needs x86_64 libraries in the APK.** Many apps ship arm64 code only; those
  need an arm64 Android image.
- **The Android Studio emulator cannot be used.** It is based on a very old QEMU without
  tracing support.
- **The phone's screen is not shown.** Android runs without a display; you see what the app
  does through the trace.
- **Some malware hides from emulators.** Apps that detect emulation may behave differently or do
  nothing. Packed or anti-tamper protected apps were not tested.
- **Text is best-effort.** It is shown when a register points at readable memory; only the
  first 32 bytes are captured.
- **The fast engine is pinned to QEMU 10.0.3.** Other QEMU versions need the plugin engine or a
  small update to the patch.

## 🏢 Using it at work

I designed DroidTrace so a security team can adopt it without surprises:

- **Isolated by default.** No internet for the phone, a clean snapshot on every run, the viewer
  only listens on `127.0.0.1`, and the container runs without extra privileges.
- **Reproducible.** Pinned QEMU version, versioned trace format, one Docker image, and a
  `manifest.json` per run with the APK's SHA-256 and the exact settings.
- **Bounded.** Hard limits on trace size and phone memory, so a run cannot exhaust a host.
- **Automatable.** Everything is a CLI command with machine-readable output (JSONL / CSV /
  Parquet), easy to drive from a pipeline or a job queue.
- **Open and auditable.** Apache-2.0 code, documented file format, CI with tests, linting,
  type checking, CodeQL and Dependabot.

Read [docs/deployment.md](docs/deployment.md) for running it on shared or air-gapped
infrastructure, and [SECURITY.md](SECURITY.md) for how to report problems.

## ❓ FAQ

<details>
<summary><b>Is it safe to run real malware with this?</b></summary>

It is built for that, but no sandbox is perfect. Use a spare machine or VM, keep the default
isolation on, and read [docs/safety.md](docs/safety.md).
</details>

<details>
<summary><b>Why not just use Frida?</b></summary>

Frida is great for hooking specific functions. DroidTrace records <i>everything</i> a library
does, without injecting anything into the app, which is harder for malware to notice and gives
you a complete history to search afterwards.
</details>

<details>
<summary><b>Can I trace Java code?</b></summary>

Not as Java. DroidTrace sees machine instructions, so it is aimed at native libraries.
</details>

<details>
<summary><b>How big do traces get?</b></summary>

A few hundred bytes per instruction. The demo run is 2 MB. Use `--libs` to follow less code
and `--max-size` to cap the file.
</details>

## 📂 Project layout

```
qemu-patch/   fast built-in tracer (a patch for QEMU)
plugin/       portable tracer (a QEMU plugin)
src/          the droidtrace command and the live viewer
configs/      ready-made settings (Android-x86, arm64)
scripts/      helpers, e.g. downloading Android-x86
tests/        unit tests, end-to-end tests and the demo APK
docs/         guides: architecture, file format, deployment, safety, operations
docker/       the image that bundles everything
```

## 🤝 Contributing

Issues and pull requests are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); for help,
see [SUPPORT.md](SUPPORT.md).

## 📄 License

Apache-2.0, see [LICENSE](LICENSE). The QEMU patch in `qemu-patch/` is GPL-2.0-or-later, like
QEMU itself; details in [docs/licensing.md](docs/licensing.md).

If DroidTrace helps your research, you can cite it using [CITATION.cff](CITATION.cff).
