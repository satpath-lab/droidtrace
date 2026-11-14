"""The virtual phone's screen and controls, for the live viewer.

The screen is read straight from QEMU's display (monitor `screendump`), so it works even
though Android runs without a window. Taps, keys and text go through adb.
"""

from __future__ import annotations

import os
import socket
import struct
import tempfile
import threading
import time
import zlib
from pathlib import Path

from .adb import AdbClient

KEYS = {"back": 4, "home": 3, "recents": 187, "enter": 66, "delete": 67}


def ppm_to_png(ppm: bytes) -> tuple[bytes, int, int]:
    """Convert a binary PPM (P6, 8-bit) to PNG without any image library."""
    if not ppm.startswith(b"P6"):
        raise ValueError("not a P6 PPM")
    fields: list[bytes] = []
    i = 2
    while len(fields) < 3:  # width, height, maxval (skipping whitespace and comments)
        while ppm[i : i + 1].isspace():
            i += 1
        if ppm[i : i + 1] == b"#":
            i = ppm.index(b"\n", i) + 1
            continue
        j = i
        while not ppm[j : j + 1].isspace():
            j += 1
        fields.append(ppm[i:j])
        i = j
    w, h = int(fields[0]), int(fields[1])
    px = ppm[i + 1 : i + 1 + w * h * 3]
    stride = w * 3
    raw = b"".join(b"\0" + px[y * stride : (y + 1) * stride] for y in range(h))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 3))
        + chunk(b"IEND", b"")
    )
    return png, w, h


class Phone:
    def __init__(self, monitor_socket: str, adb: AdbClient, min_interval: float = 0.4) -> None:
        self.monitor_socket, self.adb, self.min_interval = monitor_socket, adb, min_interval
        self._lock = threading.Lock()
        self._last = 0.0
        self._png: bytes | None = None
        self.size = (0, 0)

    def _monitor(self, cmd: str, wait: float = 1.5) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(self.monitor_socket)
            s.settimeout(0.3)
            s.sendall(cmd.encode() + b"\n")
            end = time.monotonic() + wait
            while time.monotonic() < end:  # drain the prompt so QEMU finishes the command
                try:
                    if not s.recv(65536):
                        break
                except TimeoutError:
                    pass

    def screenshot(self) -> bytes | None:
        """PNG of the phone screen (cached briefly so many viewers don't overload QEMU)."""
        with self._lock:
            if self._png is not None and time.monotonic() - self._last < self.min_interval:
                return self._png
            fd, path = tempfile.mkstemp(suffix=".ppm")
            os.close(fd)
            try:
                self._monitor(f"screendump {path}")
                for _ in range(20):  # QEMU writes the file asynchronously
                    data = Path(path).read_bytes()
                    if len(data) > 32:
                        break
                    time.sleep(0.05)
                self._png, w, h = ppm_to_png(data)
                self.size = (w, h)
                self._last = time.monotonic()
            except (OSError, ValueError):
                return self._png
            finally:
                Path(path).unlink(missing_ok=True)
            return self._png

    def tap(self, x: int, y: int) -> None:
        # 224 = WAKEUP: does nothing if the screen is already on
        self.adb.shell(f"input keyevent 224; input tap {int(x)} {int(y)}", check=False)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self.adb.shell(
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}", check=False
        )

    def key(self, name: str) -> None:
        if name in KEYS:
            self.adb.shell(f"input keyevent {KEYS[name]}", check=False)

    def text(self, value: str) -> None:
        # adb's `input text` needs spaces as %s and shell metacharacters escaped
        safe = "".join(c if c.isalnum() or c in "@._-:/" else f"\\{c}" for c in value)
        self.adb.shell(f"input text {safe.replace(' ', '%s')}", check=False)
