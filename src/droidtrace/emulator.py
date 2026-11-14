"""QEMU process management."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
from pathlib import Path

from .config import EmulatorConfig, TraceConfig

log = logging.getLogger(__name__)


def engine_for(emu: EmulatorConfig) -> str:
    # The built-in tracer is AArch64-only; x86_64 guests always use the plugin.
    return emu.engine if emu.arch == "aarch64" else "plugin"


def trace_env(emu: EmulatorConfig, trace: TraceConfig, out: Path, ranges: Path) -> dict[str, str]:
    """Environment for the built-in tracer (patched QEMU reads DROIDTRACE_*)."""
    if engine_for(emu) != "builtin":
        return {}
    return {
        "DROIDTRACE_OUT": str(out.resolve()),
        "DROIDTRACE_RANGES": str(ranges.resolve()),
        "DROIDTRACE_DEREF": str(trace.deref_bytes),
        "DROIDTRACE_STRICT": "1" if trace.strict_process else "0",
        "DROIDTRACE_MAX_BYTES": str(trace.max_bytes),
    }


def has_snapshot(emu: EmulatorConfig) -> bool:
    """True if the state disk holds the saved booted snapshot (fast start)."""
    if not emu.state_disk or not Path(emu.state_disk).exists():
        return False
    img = shutil.which("qemu-img") or "qemu-img"
    try:
        out = subprocess.run(
            [img, "snapshot", "-U", "-l", emu.state_disk],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(emu.boot_snapshot in line.split() for line in out.splitlines())


def snapshot_matches(emu: EmulatorConfig) -> bool:
    """A snapshot only restores with the same RAM size it was saved with."""
    meta = Path(emu.state_disk or "").with_suffix(".json")
    if not meta.exists():
        return True  # older snapshot without metadata: let QEMU decide
    import json

    return bool(json.loads(meta.read_text()).get("memory") == emu.memory)


def build_command(
    emu: EmulatorConfig,
    trace: TraceConfig,
    out: Path,
    ranges: Path,
    preparing: bool = False,
) -> list[str]:
    qemu = emu.qemu_binary or f"qemu-system-{emu.arch}"
    plugin_args = ",".join(
        [
            f"{Path(emu.plugin_path).resolve()}",
            f"out={out.resolve()}",
            f"ranges={ranges.resolve()}",
            f"regs={trace.registers}",
            f"strict={'on' if trace.strict_process else 'off'}",
            f"deref={trace.deref_bytes}",
            f"max_bytes={trace.max_bytes}",
        ]
    )
    # isolated: only the adb port is forwarded, guest has no route to the internet.
    netdev = f"user,id=n0,hostfwd=tcp:127.0.0.1:{emu.adb_host_port}-:5555"
    if emu.network == "isolated":
        netdev += ",restrict=on"  # guest cannot open connections to anything but the host forward
    cmd = [
        qemu,
        "-accel",
        "tcg,thread=multi",  # plugins require TCG
        "-machine",
        emu.machine,
        "-smp",
        str(emu.smp),
        "-m",
        emu.memory,
        "-display",
        "none",
        "-monitor",
        f"unix:{emu.monitor_socket},server=on,wait=off" if emu.monitor_socket else "none",
        "-serial",
        f"unix:{emu.console_socket},server=on,wait=off" if emu.console_socket else "null",
        "-netdev",
        netdev,
        "-device",
        "virtio-net-pci,netdev=n0",
    ]
    if engine_for(emu) == "plugin" and not preparing:
        cmd += ["-plugin", plugin_args]
    if emu.cpu:  # must match the CPU the boot snapshot was saved with
        cmd += ["-cpu", emu.cpu]
    if emu.display_device:
        cmd += ["-device", emu.display_device]
    if emu.cdrom:
        cmd += ["-cdrom", emu.cdrom]
    if emu.state_disk:
        cmd += ["-drive", f"file={emu.state_disk},if=none,id=state,format=qcow2"]
        if not preparing and has_snapshot(emu):
            cmd += ["-loadvm", emu.boot_snapshot]
    if emu.kernel:
        cmd += ["-kernel", emu.kernel]
    if emu.initrd:
        cmd += ["-initrd", emu.initrd]
    if emu.append:
        cmd += ["-append", emu.append]
    # Guest-visible disks get a throwaway overlay (snapshot=on), so a run never changes
    # them. A global -snapshot would also hide the saved boot state on the state disk.
    throwaway = emu.snapshot and not preparing
    for d in emu.disks:
        cmd += [
            "-drive",
            f"file={d},if=virtio,format=qcow2" + (",snapshot=on" if throwaway else ""),
        ]
    return cmd + emu.extra_args


class Emulator:
    def __init__(self, cmd: list[str], log_path: Path, env: dict[str, str] | None = None) -> None:
        self.cmd, self.log_path, self.env = cmd, log_path, env or {}
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if not shutil.which(self.cmd[0]) and not Path(self.cmd[0]).exists():
            raise FileNotFoundError(f"QEMU binary not found: {self.cmd[0]}")
        log.info("starting: %s", " ".join(self.cmd))
        self._log = self.log_path.open("wb")
        self.proc = subprocess.Popen(
            self.cmd,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **self.env},
        )

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 30) -> None:
        if not self.proc:
            return
        # SIGTERM lets QEMU run plugin atexit callbacks, which flush the trace.
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            log.warning("QEMU did not exit, killing (trace tail may be truncated)")
            self.proc.kill()
            self.proc.wait()
        self._log.close()

    def __enter__(self) -> Emulator:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
