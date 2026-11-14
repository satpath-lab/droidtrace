"""Thin, testable wrapper around the adb CLI."""

from __future__ import annotations

import contextlib
import logging
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


class AdbError(RuntimeError):
    pass


class AdbClient:
    def __init__(self, serial: str, adb: str = "adb", timeout: float = 60.0) -> None:
        self.serial, self.adb, self.timeout = serial, adb, timeout

    def _run(self, *args: str, timeout: float | None = None, check: bool = True) -> str:
        cmd = [self.adb, "-s", self.serial, *args]
        log.debug("adb: %s", " ".join(cmd))
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout or self.timeout)
        if check and p.returncode != 0:
            raise AdbError(f"{' '.join(cmd)} failed: {p.stderr.strip()}")
        return p.stdout

    def connect(self) -> None:
        # Right after a snapshot restore the guest network can stall; a hung connect is
        # just "not ready yet".
        with contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run([self.adb, "connect", self.serial], capture_output=True, timeout=15)

    def disconnect(self) -> None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            subprocess.run([self.adb, "disconnect", self.serial], capture_output=True, timeout=15)

    def shell(self, cmd: str, **kw: object) -> str:
        return self._run("shell", cmd, **kw)  # type: ignore[arg-type]

    def state(self) -> str:
        """adb's view of the device: "device", "offline", "unauthorized" or "" (absent)."""
        for line in self._run("devices", check=False).splitlines():
            parts = line.split()
            if parts and parts[0] == self.serial:
                return parts[1] if len(parts) > 1 else ""
        return ""

    def ensure_online(self, timeout: float = 180) -> None:
        """Wait until adb sees the device as usable, repairing a stuck "offline" transport."""
        deadline = time.monotonic() + timeout
        offline = 0
        while time.monotonic() < deadline:
            st = self.state()
            if st == "device":
                return
            if st == "offline":
                offline += 1
                if offline >= 4:
                    subprocess.run([self.adb, "kill-server"], capture_output=True, timeout=30)
                    offline = 0
            else:
                self.connect()
            time.sleep(3)
        raise AdbError(f"{self.serial} did not come online")

    def wait_for_boot(self, timeout: float = 900, alive: Callable[[], bool] = lambda: True) -> None:
        deadline = time.monotonic() + timeout
        offline_streak = 0
        while time.monotonic() < deadline:
            if not alive():
                raise AdbError("the emulator stopped while booting; see qemu.log")
            st = self.state()
            if st != "device":
                if st == "offline":
                    offline_streak += 1
                    # A device is briefly "offline" during every handshake; only a long
                    # streak means the transport is stuck and needs a fresh adb server.
                    if offline_streak >= 6:
                        subprocess.run([self.adb, "kill-server"], capture_output=True, timeout=30)
                        offline_streak = 0
                else:
                    offline_streak = 0
                    self.connect()
                time.sleep(5)
                continue
            offline_streak = 0
            try:
                if self.shell("getprop sys.boot_completed", check=False).strip() == "1":
                    return
            except (subprocess.TimeoutExpired, AdbError):
                pass
            time.sleep(5)
        raise AdbError("guest did not finish booting in time")

    def install(self, apk: Path, attempts: int = 6) -> None:
        # Right after a snapshot restore the package service can still be waking up
        # ("Broken pipe", "Can't find service: package"); wait for it and retry.
        for i in range(attempts):
            self.ensure_online()
            ready_by = time.monotonic() + 300
            while time.monotonic() < ready_by:
                try:
                    if self.shell("pm path android", check=False, timeout=20).startswith(
                        "package:"
                    ):
                        break
                except subprocess.TimeoutExpired:
                    pass  # system_server still catching up after the restore
                time.sleep(3)
            try:
                self._run("install", "-r", "-g", str(apk), timeout=600)
                return
            except (AdbError, subprocess.TimeoutExpired):
                if i == attempts - 1:
                    raise
                log.info("install failed, retrying (package service still starting)")
                time.sleep(5)

    def launch(self, package: str, activity: str | None = None) -> None:
        self.ensure_online()
        if activity:
            self.shell(f"am start -n {package}/{activity}")
        else:
            self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")

    def pidof(self, package: str) -> int | None:
        out = self.shell(f"pidof {package}", check=False).split()
        return int(out[0]) if out else None

    def read_maps(self, pid: int) -> str:
        out = self.shell(f"cat /proc/{pid}/maps", check=False)
        if not out.strip():  # adbd not running as root: try su (Android-x86, rooted images)
            out = self.shell(f"su 0 cat /proc/{pid}/maps", check=False)
        return out

    def root(self) -> None:
        self._run("root", check=False)
        time.sleep(3)
        self.disconnect()
        for _ in range(10):
            try:
                self.ensure_online(60)
                if self.shell("id -u", check=False, timeout=20).strip() == "0":
                    return
            except (AdbError, subprocess.TimeoutExpired):
                pass
            time.sleep(2)

    def force_stop(self, package: str) -> None:
        self.shell(f"am force-stop {package}", check=False)
