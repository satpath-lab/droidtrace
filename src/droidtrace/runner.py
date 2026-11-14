"""End-to-end orchestration of one analysis run."""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .adb import AdbClient
from .apk import inspect_apk
from .config import RunConfig
from .emulator import Emulator, build_command, has_snapshot, snapshot_matches, trace_env
from .maps import parse_maps, render_ranges, select_ranges, write_atomic

log = logging.getLogger(__name__)


def _console_bootstrap(
    sock_path: str, cmds: list[str], adb: AdbClient, stop: threading.Event
) -> None:
    """Send setup commands (e.g. enable network adb) to the guest's root serial console
    until adb answers. Idempotent commands only."""
    done = False
    while not stop.is_set():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(sock_path)
                s.settimeout(1)
                s.sendall(b"\n")
                for c in cmds:
                    s.sendall(c.encode() + b"\n")
                s.sendall(b"echo DT_CONSOLE_$((6*7))\n")  # marker proves the shell ran them
                buf = b""
                end = time.monotonic() + 3
                while time.monotonic() < end:
                    with contextlib.suppress(TimeoutError):
                        buf += s.recv(65536)
                done = done or b"DT_CONSOLE_42" in buf
        except OSError as e:
            log.debug("console not ready: %s", e)
        stop.wait(30 if done else 2)  # hammer until the shell answers, then relax


def _console_once(sock_path: str, cmd: str, tries: int = 10) -> None:
    for _ in range(tries):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(sock_path)
                s.sendall(b"\n" + cmd.encode() + b"\n")
                time.sleep(1)
                return
        except OSError:
            time.sleep(1)


def monitor_cmd(sock_path: str, cmd: str, wait: float = 2.0) -> str:
    """Send one command to the QEMU human monitor and return its output."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(sock_path)
        s.settimeout(wait)
        s.sendall(cmd.encode() + b"\n")
        buf = b""
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                chunk = s.recv(65536)
            except TimeoutError:
                continue
            if not chunk:
                break
            buf += chunk
        return buf.decode(errors="replace")


def prepare(
    cfg: RunConfig, out_dir: Path, status: Callable[[str], None] = lambda s: log.info(s)
) -> None:
    """Boot Android once and save the running state, so later runs resume in seconds."""
    e = cfg.emulator
    if not (e.state_disk and e.monitor_socket):
        raise ValueError("config needs emulator.state_disk and emulator.monitor_socket")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not Path(e.state_disk).exists():
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", e.state_disk, "1G"], check=True)
    cmd = build_command(
        e, cfg.trace, out_dir / "unused.dtr", out_dir / "ranges.txt", preparing=True
    )
    adb = AdbClient(f"127.0.0.1:{e.adb_host_port}")
    status("booting Android from scratch (this is the slow one-time step)")
    with Emulator(cmd, out_dir / "qemu.log") as emu:
        stop = threading.Event()
        if e.console_socket and e.console_setup:
            threading.Thread(
                target=_console_bootstrap,
                daemon=True,
                args=(e.console_socket, e.console_setup, adb, stop),
            ).start()
        adb.wait_for_boot(cfg.boot_timeout, emu.alive)
        stop.set()
        adb.root()  # saved in the snapshot, so every run can read /proc/<pid>/maps
        # Save with no adb client attached: a connection frozen into the snapshot
        # leaves adbd confused after restore ("offline").
        adb.disconnect()
        subprocess.run(["adb", "kill-server"], capture_output=True, timeout=30)
        status("Android booted; saving snapshot")
        monitor_cmd(e.monitor_socket, f"savevm {e.boot_snapshot}", wait=300)
    if not has_snapshot(e):
        raise RuntimeError("snapshot was not saved; see qemu.log")
    Path(e.state_disk).with_suffix(".json").write_text(
        json.dumps({"memory": e.memory, "cpu": e.cpu, "machine": e.machine})
    )
    status(f"saved snapshot '{e.boot_snapshot}' in {e.state_disk}")


def run(
    cfg: RunConfig,
    apk_path: Path,
    out_dir: Path,
    status: Callable[[str], None] = lambda s: log.info(s),
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    info = inspect_apk(apk_path)
    package = cfg.package or info.package
    if not package:
        raise ValueError("could not determine package name; set `package` in config")

    trace_path = out_dir / "trace.dtr"
    ranges_path = out_dir / "ranges.txt"
    write_atomic(ranges_path, render_ranges([]))

    manifest: dict[str, object] = {
        "droidtrace_version": __version__,
        "apk": {
            "path": str(apk_path),
            "sha256": info.sha256,
            "package": package,
            "native_libs": info.native_libs,
        },
        "config": cfg.model_dump(),
        "started": time.time(),
    }

    cmd = build_command(cfg.emulator, cfg.trace, trace_path, ranges_path)
    adb = AdbClient(f"127.0.0.1:{cfg.emulator.adb_host_port}")
    status("starting emulator")
    env = trace_env(cfg.emulator, cfg.trace, trace_path, ranges_path)
    with Emulator(cmd, out_dir / "qemu.log", env) as emu:
        if has_snapshot(cfg.emulator) and not snapshot_matches(cfg.emulator):
            raise ValueError(
                "the saved snapshot was made with different memory settings; "
                "run `droidtrace prepare` again"
            )
        resumed = has_snapshot(cfg.emulator)
        if resumed:
            status("resuming saved Android snapshot")
        else:
            status("booting Android (tip: `droidtrace prepare` makes later runs start fast)")
        stop_console = threading.Event()
        if cfg.emulator.console_socket and cfg.emulator.console_setup:
            threading.Thread(
                target=_console_bootstrap,
                daemon=True,
                args=(cfg.emulator.console_socket, cfg.emulator.console_setup, adb, stop_console),
            ).start()
        if resumed and cfg.emulator.console_socket:
            # restart adbd once so it forgets any connection frozen in the snapshot
            _console_once(cfg.emulator.console_socket, "stop adbd; start adbd")
        adb.wait_for_boot(cfg.boot_timeout, emu.alive)
        # Keep re-applying the console setup for the whole run: Android's network
        # manager can drop the routing rule at any time, which silently cuts adb off.
        adb.root()
        status(f"installing {apk_path.name}")
        adb.install(apk_path)
        adb.launch(package, cfg.activity or info.launchable_activity)

        status(f"running {package} for {cfg.duration:.0f}s")
        deadline = time.monotonic() + cfg.duration
        last_ranges = ""
        pid: int | None = None
        while time.monotonic() < deadline and emu.alive():
            new_pid = adb.pidof(package)
            if new_pid != pid:
                log.info("target pid: %s", new_pid)
                pid = new_pid
            if pid:
                try:
                    sel = select_ranges(
                        parse_maps(adb.read_maps(pid)),
                        cfg.trace.libraries,
                        cfg.trace.exclude,
                        cfg.trace.anchors,
                    )
                    text = render_ranges(sel)
                    if text != last_ranges:  # new dlopen() / process restart
                        write_atomic(ranges_path, text)
                        last_ranges = text
                        log.info("updated ranges: %d mappings", len(sel))
                except Exception as e:  # process may die mid-read
                    log.debug("maps read failed: %s", e)
            time.sleep(cfg.trace.maps_poll_interval)
        adb.force_stop(package)
        stop_console.set()
        status("stopping emulator, flushing trace")

    manifest["finished"] = time.time()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    status("finished")
    return trace_path
