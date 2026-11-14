# Built-in tracer (QEMU patch)

A small patch to upstream QEMU **10.0.3** that compiles DroidTrace's tracer directly into the
AArch64 translator. It writes the same `.dtr` v2 format as the TCG plugin, so the reader,
exporters and live viewer work unchanged.

```bash
sh qemu-patch/apply.sh /path/to/qemu-10.0.3
cd /path/to/qemu-10.0.3 && ./configure --target-list=aarch64-softmmu,aarch64-linux-user && make
DROIDTRACE_OUT=trace.dtr DROIDTRACE_RANGES=ranges.txt ./build/qemu-system-aarch64 ...
```

## Why it is faster

| | Plugin | Built-in |
|---|---|---|
| Per traced instruction | plugin dispatch, then one gdbstub register lookup per register (42) | one direct helper call, then `memcpy` from `CPUARMState` |
| Measured (0.70M traced insns, 42 regs + strings, QEMU 10.0.3 user mode) | 1.99 s | **0.29 s (≈7×)** |
| Untraced code | ~2–5 % overhead | ~0 % (no hook emitted) |
| QEMU | any upstream ≥ 10.0 | patched 10.0.3, AArch64 only |

## What it changes

- `target/arm/tcg/dtrace-a64.c` (new): range lookup at translation time, runtime helper,
  buffered writer with a hard size cap, range-file hot reload with a TB flush.
- `target/arm/tcg/translate-a64.c`: one hook after each instruction is fetched.
- `target/arm/tcg/helper-a64.h`: helper declaration.
- `linux-user/exit.c`: flush the buffer on `exit_group` (user mode exits via `_exit`).

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DROIDTRACE_OUT` | unset (disabled) | trace output file |
| `DROIDTRACE_RANGES` | unset | range file (hot-reloaded) |
| `DROIDTRACE_DEREF` | 32 | bytes captured behind pointer args x0–x7 (0 = off) |
| `DROIDTRACE_STRICT` | 1 | drop instructions from other address spaces |
| `DROIDTRACE_MAX_BYTES` | 2 GiB | hard cap; tracing stops when reached |
| `DROIDTRACE_RELOAD_MS` | 250 | range poll / flush interval |

## Porting

The Android SDK emulator is a QEMU 2.12 fork (`external/qemu` in AOSP). The same hook
(after the instruction fetch in `aarch64_tr_translate_insn`) applies there, but the helper
and translator APIs differ, and the emulator must run with TCG rather than HVF or KVM for
any instruction-level tracing.
