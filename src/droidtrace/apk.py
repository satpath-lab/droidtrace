"""Minimal APK metadata extraction (package name, native libs, hash)."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApkInfo:
    path: Path
    sha256: str
    package: str | None
    launchable_activity: str | None
    native_libs: list[str]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_apk(path: Path, aapt: str = "aapt2") -> ApkInfo:
    with zipfile.ZipFile(path) as z:
        libs = sorted(
            {
                n.rsplit("/", 1)[-1]
                for n in z.namelist()
                if n.startswith("lib/") and n.endswith(".so")
            }
        )
    pkg = act = None
    if shutil.which(aapt):
        out = subprocess.run(
            [aapt, "dump", "badging", str(path)], capture_output=True, text=True
        ).stdout
        if m := re.search(r"package: name='([^']+)'", out):
            pkg = m.group(1)
        if m := re.search(r"launchable-activity: name='([^']+)'", out):
            act = m.group(1)
    return ApkInfo(path, sha256(path), pkg, act, libs)
