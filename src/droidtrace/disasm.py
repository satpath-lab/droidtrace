"""Optional disassembly via capstone."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .format import Arch


@lru_cache(maxsize=4)
def _cs(arch: Arch) -> Any:
    try:
        import capstone as cs
    except ImportError:
        return None
    if arch == Arch.AARCH64:
        return cs.Cs(cs.CS_ARCH_ARM64, cs.CS_MODE_ARM)
    if arch == Arch.X86_64:
        return cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64)
    return None


def disassemble(arch: Arch, code: bytes, addr: int) -> str:
    md = _cs(arch)
    if md is None:
        return code.hex()
    for i in md.disasm(code, addr, 1):
        return f"{i.mnemonic} {i.op_str}".strip()
    return code.hex()
