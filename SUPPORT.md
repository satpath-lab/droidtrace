# Getting help

- **Something doesn't work?** Run `droidtrace doctor` first; it checks every piece and says
  what is missing. Then look at [docs/operations.md](docs/operations.md#troubleshooting).
- **Found a bug?** Open an issue using the bug template. Include your OS, `droidtrace doctor`
  output and the `qemu.log` from the run folder.
- **Have an idea?** Open a feature request; I'm happy to discuss it.
- **Security problem?** Please don't open a public issue; follow [SECURITY.md](SECURITY.md).

## Versions and compatibility

| Component | Supported |
|---|---|
| DroidTrace | latest release (semantic versioning; see [CHANGELOG.md](CHANGELOG.md)) |
| Python | 3.10 – 3.13 |
| QEMU | 10.0.3 (built-in engine), 10.0+ (plugin engine) |
| Host | Linux x86_64 / arm64, macOS on Apple Silicon (via Docker) |
| Guest | Android-x86 9.0 (tested), arm64 AOSP / Cuttlefish (experimental) |

The trace file format is versioned (`DT_FORMAT_VERSION`); a new version is always called out in
the changelog.
