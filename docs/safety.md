# Safe operation

DroidTrace executes **live malware**. Emulation is not a security boundary you should rely on alone.

- Run on dedicated, disposable hosts or VMs; never on a workstation with credentials.
- Default config uses `-snapshot` (guest writes are discarded) and `restrict=on` user networking
  (no egress; only adb is forwarded, bound to 127.0.0.1).
- Run the container as non-root, with `--network none` where possible, `--cap-drop ALL`,
  and a read-only root filesystem.
- Store samples encrypted/zipped with a password; never commit them.
- Traces can contain secrets the malware handles (keys, tokens) — treat them as sensitive.
- `--internet` gives the sample real network access. Use it only on an isolated analysis
  network, and expect the sample to contact its operators.
- Make sure you are authorised to analyse each sample and comply with local law and policy.
