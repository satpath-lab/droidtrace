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

    def install(self, apk: Path | list[Path], attempts: int = 6) -> None:
        # Right after a snapshot restore the package service can still be waking up
        # ("Broken pipe", "Can't find service: package"); wait for it and retry.
        for i in range(attempts):
            self.ensure_online()
            self.wait_package_service()
            try:
                files = apk if isinstance(apk, list) else [apk]
                if len(files) == 1:
                    self._run("install", "-r", "-g", str(files[0]), timeout=600)
                else:  # split app: base + config splits in one transaction
                    self._run("install-multiple", "-r", "-g", *map(str, files), timeout=900)
                return
            except (AdbError, subprocess.TimeoutExpired):
                if i == attempts - 1:
                    raise
                log.info("install failed, retrying (package service still starting)")
                time.sleep(5)

    def dismiss_dialogs(self) -> None:
        """Close system dialogs such as "System UI isn't responding", which can pop up right
        after a snapshot restore (the phone's clock jumps)."""
        with contextlib.suppress(subprocess.TimeoutExpired, AdbError):
            self.shell(
                "am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS",
                check=False,
                timeout=60,
            )

    def launch(self, package: str, activity: str | None = None) -> None:
        self.ensure_online()
        self.dismiss_dialogs()
        if activity:
            self.shell(f"am start -n {package}/{activity}")
        else:
            self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")

    def wait_package_service(self, timeout: float = 300) -> None:
        """Right after a snapshot restore Android needs a moment before it answers."""
        ready_by = time.monotonic() + timeout
        while time.monotonic() < ready_by:
            try:
                if self.shell("pm path android", check=False, timeout=20).startswith("package:"):
                    return
            except subprocess.TimeoutExpired:
                pass  # system_server still catching up
            time.sleep(3)

    def prepare_device(self) -> None:
        """Get the phone ready for analysis: skip the welcome wizard, no install verification.

        Best effort: a slow phone must not stop the analysis.
        """
        self.wait_package_service()
        with contextlib.suppress(subprocess.TimeoutExpired, AdbError):
            self.shell(
                "settings put global device_provisioned 1; "
                "settings put secure user_setup_complete 1; "
                # Package verification would try to check every install online and can hang.
                "settings put global verifier_verify_adb_installs 0; "
                "settings put global package_verifier_enable 0; "
                # keep the screen on, so the phone panel never goes black
                "svc power stayon true; settings put system screen_off_timeout 2147483647; "
                "input keyevent 224; "
                # one default home screen, so Home doesn't open a "Select a home app" chooser
                "cmd package set-home-activity "
                "com.android.launcher3/com.android.launcher3.Launcher >/dev/null 2>&1; "
                "for p in $(pm list packages | grep -iE 'setupwizard|provision' | cut -d: -f2); "
                "do pm disable-user --user 0 $p >/dev/null 2>&1; done; "
                "input keyevent 3",
                check=False,
                timeout=240,
            )

    def enable_internet(self) -> None:
        """Give Android a real default network (route + DNS) through QEMU's user networking.

        Android-x86 shows the network card as Wi-Fi and never joins a network by itself, so
        apps would see no connection. This registers one directly with netd.
        """
        self.shell(
            "IF=$(ip -o -4 addr | grep 10.0.2.15 | awk '{print $2}' | head -1); "
            "ip route add default via 10.0.2.2 dev $IF 2>/dev/null; "
            "ndc network create 100 >/dev/null 2>&1; "
            "ndc network interface add 100 $IF >/dev/null 2>&1; "
            "ndc network route add 100 $IF 10.0.2.0/24 >/dev/null 2>&1; "
            "ndc network route add 100 $IF 0.0.0.0/0 10.0.2.2 >/dev/null 2>&1; "
            "ndc resolver setnetdns 100 '' 10.0.2.3 >/dev/null 2>&1; "
            "ndc network default set 100 >/dev/null 2>&1",
            check=False,
        )

    def wait_idle(self, max_load: float = 4.0, timeout: float = 1200) -> bool:
        """Wait until the phone stops being busy (e.g. Google Play services' first-time setup).

        Saving the boot snapshot while the phone is busy would make every run start busy.
        """
        deadline = time.monotonic() + timeout
        calm = 0
        while time.monotonic() < deadline:
            try:
                load = float(self.shell("cat /proc/loadavg", check=False, timeout=30).split()[0])
            except (ValueError, IndexError, subprocess.TimeoutExpired):
                load = 99.0
            calm = calm + 1 if load < max_load else 0
            if calm >= 3:
                return True
            time.sleep(20)
        return False

    def abilist(self) -> list[str]:
        out = self.shell("getprop ro.product.cpu.abilist", check=False).strip()
        return [a for a in out.split(",") if a]

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
