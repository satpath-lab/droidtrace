"""Parse /proc/<pid>/maps and build the plugin's range file."""

from __future__ import annotations

import fnmatch
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MapEntry:
    start: int
    end: int
    perms: str
    offset: int
    path: str

    @property
    def executable(self) -> bool:
        return "x" in self.perms

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def parse_maps(text: str) -> list[MapEntry]:
    out: list[MapEntry] = []
    for line in text.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 5:
            continue
        addr, perms, off = parts[0], parts[1], parts[2]
        path = parts[5].strip() if len(parts) == 6 else ""
        try:
            s, e = (int(x, 16) for x in addr.split("-"))
            out.append(MapEntry(s, e, perms, int(off, 16), path))
        except ValueError:
            continue
    return out


def select_ranges(
    entries: Iterable[MapEntry],
    include: list[str],
    exclude: list[str] | None = None,
    anchor_globs: list[str] | None = None,
) -> list[tuple[MapEntry, bool]]:
    """Return executable mappings matching include globs, with anchor flag.

    Globs match either the basename or the full path. Anchors are mappings unique to the
    target process (typically the APK's own native libs under /data/app); the plugin uses
    the first instruction hit inside an anchor to learn the target's address space id.
    """
    exclude = exclude or []
    anchor_globs = anchor_globs or ["/data/app/*", "/data/data/*"]

    def m(e: MapEntry, globs: list[str]) -> bool:
        return any(fnmatch.fnmatch(e.name, g) or fnmatch.fnmatch(e.path, g) for g in globs)

    sel = []
    for e in entries:
        if not e.executable or not e.path or e.path.startswith("["):
            continue
        if m(e, include) and not m(e, exclude):
            sel.append((e, m(e, anchor_globs)))
    return sel


def render_ranges(selected: Iterable[tuple[MapEntry, bool]]) -> str:
    lines = ["# start end file_offset flags path"]
    for e, anchor in selected:
        lines.append(f"{e.start:x} {e.end:x} {e.offset:x} {'A' if anchor else '-'} {e.path}")
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, content: str) -> None:
    """Write via rename so the plugin never reads a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".ranges.")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, path)
