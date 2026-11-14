# Operations

## Android-x86 (easiest, works on any machine with Docker)

```bash
scripts/get-android-x86.sh                              # download + verify + unpack
droidtrace prepare --config configs/android-x86.yaml    # boot once, save snapshot
droidtrace run app.apk --config configs/android-x86.yaml
```

What `prepare` does for you on Android-x86, through the guest's root serial console:

- skips app precompilation at boot (`pm.dexopt.*`), which otherwise takes hours under emulation;
- uses the TSC clock instead of HPET (much cheaper to emulate);
- gives the network card an IPv4 address (Android-x86 treats it as Wi-Fi and leaves it unset);
- enables adb over the network and switches it to root;
- saves the running phone as the `droidtrace-booted` snapshot in `images/x86_64/state.qcow2`.

Every `run` restores that snapshot, so a clean phone is ready in seconds and nothing from
a previous run (or a previous malware sample) is left behind.


## Preparing a guest image
1. Build AOSP for an arm64 QEMU-compatible target (or use Cuttlefish with the QEMU VMM).
2. Convert images to qcow2 and place them under `images/arm64/` (git-ignored).
3. Enable `adbd` on boot and `ro.debuggable=1` so `adb root` works (needed for `/proc/<pid>/maps`).
4. Boot once, verify `adb -s 127.0.0.1:5555 shell getprop sys.boot_completed` returns `1`.

## Keeping disk and memory under control

- **Cap Docker's disk** (Docker Desktop → Settings → Resources → Disk usage limit, e.g. 12 GB).
  Docker's disk file never shrinks on its own; without a cap, a full build cache can fill the
  whole machine.
- After building, `docker builder prune -af` frees the QEMU build cache (several GB).
- The snapshot file is about the size of the phone's RAM (`memory:` in the config, 2 GB by default).
- Every trace is capped by `--max-size` (2 GB by default).
- On an 8 GB machine keep `memory: 2G`; Docker Desktop's VM usually gets ~4 GB in total.

## Tuning
- Restrict `trace.libraries` aggressively; a full libc trace produces GBs per second.
- `registers: "x0:x1:x2:x3:sp:pc"` cuts record size by ~5×.
- Use more `smp` only if the target is multi-threaded; the global write lock serialises output.

## Troubleshooting
| Symptom | Cause |
|---|---|
| 0 records | No ranges matched; check `ranges.txt` and globs |
| "saved snapshot was made with different memory settings" | You changed `memory:`; run `droidtrace prepare` again |
| Install fails right after resume | Android is still waking up; DroidTrace retries for up to 5 min |
| adb shows `offline` | Use the default port 15555; ports 5555-5585 clash with adb's emulator scan |
| Records from other apps | No anchor hit; app has no native libs under `/data/app` |
| `register 'TTBR0_EL1' not available` | QEMU < 9.0 or CPU model without sysreg XML |
