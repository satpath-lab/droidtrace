"""Human-readable interpretations of raw 64-bit register values.

Registers carry no type: the same bits may be an int, a pointer, a bool, a char or a
float depending on the instruction that consumes them. We therefore offer every plausible
reading and pick a "best guess" for compact display.
"""

from __future__ import annotations

import struct
from typing import Any

from .reader import Trace

FP_PREFIXES = ("v", "xmm", "d", "q")


def is_fp(name: str) -> bool:
    return name.startswith(FP_PREFIXES) and name[-1].isdigit()


def as_string(mem: bytes) -> str | None:
    """Readable text at the start of memory (a C string, or a buffer still being written).

    Takes the printable prefix up to the first NUL or non-text byte; needs >= 4 characters
    (2 if properly NUL-terminated) so random bytes are not shown as text.
    """
    out = []
    terminated = False
    for b in mem:
        if b == 0:
            terminated = True
            break
        if b in (9, 10, 13) or 0x20 <= b < 0x7F:
            out.append(chr(b))
        else:
            break
    s = "".join(out)
    if len(s) >= 4 or (terminated and len(s) >= 2):
        return s if terminated else s + "…"
    return None


def as_utf16(mem: bytes) -> str | None:
    """Java/JNI strings (jchar*) are UTF-16LE."""
    if len(mem) < 4 or mem[1] != 0 or mem[3] != 0:
        return None
    try:
        s = mem.decode("utf-16-le", "strict").split("\0", 1)[0]
    except UnicodeDecodeError:
        return None
    return s if len(s) >= 2 and s.isprintable() else None


def interpret(t: Trace, name: str, v: int, mem: bytes | None) -> dict[str, Any]:
    out: dict[str, Any] = {"hex": f"0x{v:x}"}
    signed = v - (1 << 64) if v >> 63 else v
    if is_fp(name):
        d = struct.unpack("<d", v.to_bytes(8, "little"))[0]
        f = struct.unpack("<f", (v & 0xFFFFFFFF).to_bytes(4, "little"))[0]
        out["double"] = repr(d)
        out["float"] = repr(f)
        out["best"] = f"{d:.6g}" if v >> 32 else f"{f:.6g}f"
        return out
    out["int"] = str(signed)
    if signed != v:
        out["uint"] = str(v)
    if v in (0, 1):
        out["bool"] = "true" if v else "false"
    if 0x20 <= v <= 0x7E:
        out["char"] = repr(chr(v))
    if signed < 0 and signed >= -(1 << 31):
        out["int32"] = str(signed)
    best = str(signed) if -(1 << 20) < signed < (1 << 20) else out["hex"]
    lib = t.lib_for_addr(v) if v > 0xFFFF else None
    if lib:
        out["ptr"] = f"{lib.name}+0x{lib.lib_offset(v):x}"
        best = out["ptr"]
    if mem:
        out["mem"] = mem.hex(" ")
        s = as_string(mem) or as_utf16(mem)
        if s is not None:
            out["string"] = s
            best = '"' + s + '"'
        elif not lib:
            out["ptr"] = "→ " + mem[:8].hex(" ")
            best = out["hex"]
    out["best"] = best
    return out
