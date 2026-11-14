"""Environment checks and guest image setup."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import IMAGES, RunConfig

REQUIRED_IMAGES = ["kernel", "system.qcow2", "userdata.qcow2"]


def checks(cfg: RunConfig) -> list[tuple[str, bool, str]]:
    qemu = cfg.emulator.qemu_binary or f"qemu-system-{cfg.emulator.arch}"
    out: list[tuple[str, bool, str]] = []
    q = shutil.which(qemu)
    ver = ""
    if q:
        ver = subprocess.run([q, "--version"], capture_output=True, text=True).stdout.split("\n")[0]
    out.append(("QEMU", bool(q), ver or f"{qemu} not found"))
    from .emulator import engine_for

    if engine_for(cfg.emulator) == "builtin":
        built_in = q is not None and b"dtrace_a64_want" in Path(q).read_bytes()
        out.append(
            (
                "Built-in tracer",
                built_in,
                "patched QEMU found"
                if built_in
                else "QEMU is not patched (qemu-patch/apply.sh) - or use --engine plugin",
            )
        )
    else:
        plug = Path(cfg.emulator.plugin_path)
        out.append(("Tracing plugin", plug.exists(), str(plug)))
    out.append(("adb", bool(shutil.which("adb")), shutil.which("adb") or "not found"))
    aapt = shutil.which("aapt2") or shutil.which("aapt")
    out.append(("aapt (package name)", bool(aapt), aapt or "optional; pass --package instead"))
    e = cfg.emulator
    files = [f for f in (e.kernel, e.initrd, e.cdrom, *e.disks) if f]
    missing = [f for f in files if not Path(f).exists()]
    ok = bool(e.kernel or e.cdrom or e.disks) and not missing
    out.append(
        (
            "Android guest image",
            ok,
            ", ".join(files)
            if ok
            else f"missing: {', '.join(missing)}"
            if missing
            else f"none configured (put an image in {IMAGES} or pass --config)",
        )
    )
    return out


def import_image(src: Path) -> list[str]:
    """Copy a prepared guest image directory into ~/.droidtrace/images/arm64."""
    IMAGES.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in REQUIRED_IMAGES + ["initrd.img", "vendor.qcow2"]:
        f = src / name
        if f.exists():
            shutil.copy2(f, IMAGES / name)
            copied.append(name)
    return copied
