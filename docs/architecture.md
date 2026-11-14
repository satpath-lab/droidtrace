# Architecture

## Components

| Component | Language | Responsibility |
|---|---|---|
| `plugin/` (`libinsntrace.so`) | C | Instruments every user-space guest instruction; at execution time checks it against the range table, reads registers, appends a record. |
| `droidtrace.emulator` | Python | Builds the QEMU command line (TCG, isolated network, `-snapshot`) and manages the process. |
| `droidtrace.adb` | Python | Boot wait, install, launch, `pidof`, `/proc/<pid>/maps`. |
| `droidtrace.maps` | Python | Selects executable mappings by glob, marks *anchors*, writes `ranges.txt` atomically. |
| `droidtrace.reader` / `exporters` | Python | mmap reader for `.dtr`, JSONL/CSV/Parquet export, capstone disassembly. |

## Tracing engines

Both engines share the range file, the anchor/ASID logic and the `.dtr` v2 format.

- **Built-in** (`qemu-patch/dtrace-a64.c`): at translation time, an instruction inside a traced
  range gets one direct helper call. The helper copies `xregs`, SP, PC, PSTATE and `v0–v7`
  straight from `CPUARMState`, reads TTBR0 for process filtering, captures memory behind pointer
  arguments, and appends to a 16 MB buffer. Range reloads schedule `tb_flush` on a vCPU via
  `async_run_on_cpu`. About 7× faster than the plugin; AArch64 only.
- **Plugin** (`plugin/src/insntrace.c`): the same logic through the public plugin API. It works
  with unmodified QEMU ≥ 10.0, but each register is read through the gdbstub layer.

## Data flow

1. QEMU boots the Android guest with the plugin loaded and an empty `ranges.txt`.
2. The runner installs and launches the APK, then polls `/proc/<pid>/maps` of the target.
3. Whenever the maps change (new `dlopen`, process restart) `ranges.txt` is rewritten via
   rename; the plugin's reload thread swaps in a new sorted table (lock-free readers).
4. On each instrumented instruction the plugin binary-searches the table. On a hit it reads the
   selected registers (pre-execution state) and appends a fixed-size record under a mutex,
   assigning a global `seq`.
5. On shutdown (SIGTERM) the plugin's atexit callback flushes the trace.

## Process isolation within a full-system guest

All Android apps fork from zygote, so `libc.so` is mapped at the *same address* in every app.
Address ranges alone would therefore capture other processes too. DroidTrace solves this with
**anchor-based address-space learning**:

- Ranges under `/data/app/*` (the APK's own native code) exist only in the target process.
- The first time an instruction runs inside an anchor range, the plugin records the current
  page-table base (`TTBR0_EL1` on AArch64, `CR3` on x86_64) as the target address space.
- From then on, records whose page-table base differs are dropped (`strict=on`) or kept
  without the `PROC_VERIFIED` flag (`strict=off`).

Limitations: an APK with no native code has no anchor; use `strict_process: false` and filter
offline by `asid`, or add a custom anchor (e.g. the app's `base.odex`/`.oat`).

## Why exec-time range checks

Libraries can be mapped after their code would otherwise be translated. Instrumenting all
user-space instructions and filtering at exec time avoids TB flushes and makes hot reload
correct, at the cost of a callback for every user instruction.

## Scaling

- Run many guests in parallel (one container each) via a job queue; each run is self-contained
  in its output directory (`trace.dtr`, `trace.dtr.libs`, `ranges.txt`, `qemu.log`, `manifest.json`).
- Future work: per-vCPU ring buffers instead of a global mutex; zstd streaming compression.
