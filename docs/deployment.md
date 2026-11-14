# Deploying DroidTrace in an organisation

This guide is for teams that want to run DroidTrace on shared, locked-down or air-gapped
infrastructure.

## Recommended setup

| Concern | What I recommend |
|---|---|
| Host | A dedicated Linux VM or machine used only for analysis |
| Isolation | Default config: no guest internet (`network: isolated`), snapshot reset per run |
| Container | Run without extra privileges: `--cap-drop ALL --security-opt no-new-privileges` (the installer's wrapper does this) |
| Viewer | Listens on `127.0.0.1` only; use an SSH tunnel to view it remotely |
| Resources | 2 vCPU, 4 GB RAM, 20 GB disk per concurrent analysis |
| Storage | Treat traces as sensitive: they can contain keys and tokens the sample handled |

## Air-gapped installation

1. On a connected machine: `docker build -t droidtrace:local -f docker/Dockerfile .` and
   `scripts/get-android-x86.sh`.
2. Export: `docker save droidtrace:local | gzip > droidtrace-image.tar.gz`, plus `images/x86_64/`.
3. On the isolated host: `docker load < droidtrace-image.tar.gz`, copy `images/`, run
   `./install.sh` (it reuses the loaded image), then `droidtrace prepare`.

## Running many samples

Each run is self-contained in its own folder (`runs/<name>/`): `trace.dtr`, `trace.dtr.libs`,
`ranges.txt`, `qemu.log` and `manifest.json` (APK SHA-256, settings, timestamps). To scale out,
run one container per sample from a job queue, each with its own copy of the snapshot disk and
its own adb port (`emulator.adb_host_port`).

```bash
droidtrace run sample.apk --config configs/android-x86.yaml \
  --no-live --duration 120 --max-size 1000 --out runs/$(sha256sum sample.apk | cut -c1-16)
droidtrace export runs/<id>/trace.dtr --format parquet -o results/<id>.parquet
```

## Pinning and updates

- QEMU is pinned to 10.0.3 in `docker/Dockerfile`; the built-in tracer patch targets that version.
- The trace format is versioned; readers refuse files with an unknown version instead of
  misreading them.
- Dependabot keeps Python packages, GitHub Actions and the base image up to date; CI runs unit
  tests, linting, type checking, end-to-end tests on real QEMU and CodeQL.

## Legal and policy

- Make sure you are authorised to analyse each sample, and follow your organisation's malware
  handling policy.
- DroidTrace is Apache-2.0. A QEMU binary built with `qemu-patch/` is GPL-2.0-or-later; see
  [licensing.md](licensing.md).
