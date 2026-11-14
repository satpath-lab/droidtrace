"""Run configuration (YAML) with validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

HOME = Path(os.environ.get("DROIDTRACE_HOME", Path.home() / ".droidtrace"))
IMAGES = HOME / "images" / "arm64"


def _default_plugin() -> str:
    for c in (
        os.environ.get("DROIDTRACE_PLUGIN"),
        "/opt/droidtrace/libinsntrace.so",
        str(HOME / "libinsntrace.so"),
        "build/libinsntrace.so",
    ):
        if c and Path(c).exists():
            return c
    return "build/libinsntrace.so"


class EmulatorConfig(BaseModel):
    arch: Literal["aarch64", "x86_64"] = "aarch64"
    # builtin: tracer compiled into patched QEMU (~7x faster, aarch64 only)
    # plugin:  TCG plugin, works with any upstream QEMU >= 10.0
    engine: Literal["builtin", "plugin"] = "builtin"
    qemu_binary: str | None = None
    plugin_path: str = Field(default_factory=_default_plugin)
    machine: str = "virt"
    cpu: str = "cortex-a76"
    smp: int = 2
    memory: str = "2G"
    kernel: str | None = Field(default_factory=lambda: _img("kernel"))
    initrd: str | None = Field(default_factory=lambda: _img("initrd.img"))
    disks: list[str] = Field(
        default_factory=lambda: [
            d for d in (_img("system.qcow2"), _img("vendor.qcow2"), _img("userdata.qcow2")) if d
        ]
    )
    append: str = "console=ttyAMA0 androidboot.hardware=qemu"
    cdrom: str | None = None  # e.g. Android-x86 live ISO
    display_device: str | None = None  # e.g. "VGA" (Android needs a display to finish booting)
    console_socket: str | None = None  # serial console as a unix socket (bootstrap commands)
    console_setup: list[str] = Field(default_factory=list)  # run on the root console after boot
    state_disk: str | None = None  # qcow2 holding the saved "booted" snapshot
    boot_snapshot: str = "droidtrace-booted"
    monitor_socket: str | None = None  # QEMU monitor (used to save the snapshot)
    extra_args: list[str] = Field(default_factory=list)
    # Outside 5555-5585: adb auto-probes that range as "emulators" and the duplicate
    # connection knocks ours offline.
    adb_host_port: int = 15555
    snapshot: bool = True  # -snapshot: never write to base images
    network: Literal["isolated", "restricted"] = "isolated"


def _img(name: str) -> str | None:
    p = IMAGES / name
    return str(p) if p.exists() else None


class TraceConfig(BaseModel):
    libraries: list[str] = Field(default_factory=lambda: ["lib*.so"])
    exclude: list[str] = Field(default_factory=lambda: ["libart*.so", "libhwui.so"])
    anchors: list[str] = Field(default_factory=lambda: ["/data/app/*"])
    registers: str = "gpr"  # "gpr" | "all" | "x0:x1:pc"
    strict_process: bool = True
    deref_bytes: int = 32  # memory captured behind pointer args (strings); 0 = off
    max_bytes: int = 2 * 1024**3  # hard cap on trace size
    maps_poll_interval: float = 0.5


class RunConfig(BaseModel):
    emulator: EmulatorConfig = Field(default_factory=EmulatorConfig)
    trace: TraceConfig = Field(default_factory=TraceConfig)
    duration: float = 120.0
    boot_timeout: float = 1200.0
    package: str | None = None
    activity: str | None = None

    @classmethod
    def load(cls, path: Path | None) -> RunConfig:
        if path is None:
            return cls()
        return cls.model_validate(yaml.safe_load(path.read_text()) or {})
