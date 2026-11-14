"""Reading apps: a single APK, or a split app (.apks / .xapk / .apkm / a folder of APKs).

Apps from Google Play are often delivered as *split APKs*: a `base.apk` plus extra APKs for
the CPU type (`split_config.arm64_v8a.apk`), screen density and language. DroidTrace accepts
all common containers and installs the right pieces with `adb install-multiple`.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ABIS = ("arm64-v8a", "armeabi-v7a", "armeabi", "x86_64", "x86", "mips64", "mips")
BUNDLE_SUFFIXES = (".apks", ".xapk", ".apkm")


@dataclass(frozen=True)
class ApkInfo:
    path: Path  # what the user passed (an .apk, a bundle or a folder)
    sha256: str
    package: str | None
    launchable_activity: str | None
    native_libs: list[str]
    abis: list[str]  # CPU types the app ships native code for, e.g. ["arm64-v8a"]
    files: list[Path] = field(default_factory=list)  # APKs to install (base first)
    abi_splits: dict[str, Path] = field(default_factory=dict)  # ABI -> its split APK

    def install_files(self, device_abis: list[str]) -> list[Path]:
        """APKs to install on a device: base + generic splits + the best matching ABI split."""
        if not self.abi_splits:
            return self.files
        chosen = next((self.abi_splits[a] for a in device_abis if a in self.abi_splits), None)
        generic = [f for f in self.files if f not in self.abi_splits.values()]
        return generic + ([chosen] if chosen else [])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(path.glob("*.apk")):
            h.update(f.name.encode())
            h.update(bytes.fromhex(sha256(f)))
        return h.hexdigest()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _split_abi(name: str) -> str | None:
    """'split_config.arm64_v8a.apk' / 'config.x86_64.apk' -> 'arm64-v8a' / 'x86_64'."""
    stem = name.rsplit("/", 1)[-1].lower().removesuffix(".apk")
    for abi in ABIS:
        if stem.endswith(abi.replace("-", "_")) or stem.endswith(abi):
            return abi
    return None


def _native(apk: Path) -> tuple[set[str], set[str]]:
    with zipfile.ZipFile(apk) as z:
        so = [n for n in z.namelist() if n.startswith("lib/") and n.endswith(".so")]
    return ({n.rsplit("/", 1)[-1] for n in so}, {n.split("/")[1] for n in so if n.count("/") >= 2})


def _badging(apk: Path, aapt: str) -> tuple[str | None, str | None]:
    if not shutil.which(aapt):
        return None, None
    out = subprocess.run([aapt, "dump", "badging", str(apk)], capture_output=True, text=True).stdout
    pkg = m.group(1) if (m := re.search(r"package: name='([^']+)'", out)) else None
    act = m.group(1) if (m := re.search(r"launchable-activity: name='([^']+)'", out)) else None
    return pkg, act


def _unpack_bundle(path: Path) -> list[Path]:
    """Extract the APKs inside an .apks/.xapk/.apkm file to a temporary folder."""
    out = Path(tempfile.mkdtemp(prefix="droidtrace-app-"))
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith(".apk") and not n.startswith("/") and ".." not in n:
                target = out / n.replace("/", "_")  # flatten "splits/base-master.apk"
                with z.open(n) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    return sorted(out.glob("*.apk"))


def _order_base_first(apks: list[Path]) -> list[Path]:
    def is_base(p: Path) -> bool:
        n = p.name.lower()
        return (
            n in ("base.apk", "base-master.apk")
            or n.endswith("_base-master.apk")
            or ("split" not in n and "config." not in n)
        )

    base = [p for p in apks if is_base(p)]
    return base[:1] + [p for p in apks if p not in base[:1]]


def inspect_apk(path: Path, aapt: str = "aapt2") -> ApkInfo:
    """Inspect an .apk, an .apks/.xapk/.apkm bundle, or a folder of split APKs."""
    if path.is_dir():
        apks = sorted(path.glob("*.apk"))
    elif path.suffix.lower() in BUNDLE_SUFFIXES:
        apks = _unpack_bundle(path)
    else:
        apks = [path]
    if not apks:
        raise ValueError(f"no APK files found in {path}")
    apks = _order_base_first(apks)

    libs: set[str] = set()
    abis: set[str] = set()
    abi_splits: dict[str, Path] = {}
    for apk in apks:
        lib_names, lib_abis = _native(apk)
        libs |= lib_names
        abis |= lib_abis
        split_abi = _split_abi(apk.name) if apk is not apks[0] else None
        if split_abi:
            abi_splits[split_abi] = apk
            abis.add(split_abi)
    pkg, act = _badging(apks[0], aapt)
    return ApkInfo(path, sha256(path), pkg, act, sorted(libs), sorted(abis), apks, abi_splits)
