#!/usr/bin/env python3
"""Generate a small synthetic .dtr trace for testing exporters (no emulator needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from droidtrace.format import FILE_HEADER, FORMAT_VERSION, MAGIC, RECORD_HEADER, REG_NAME_LEN  # noqa: E402


def write(path: Path, n: int = 10, regs: tuple[str, ...] = ("x0", "x1", "sp", "pc")) -> None:
    with path.open("wb") as f:
        dl = 16
        f.write(
            FILE_HEADER.pack(
                MAGIC,
                FORMAT_VERSION,
                1,
                len(regs),
                FILE_HEADER.size + REG_NAME_LEN * len(regs) + 2,
                0,
                1,
                dl,
                0,
            )
        )
        for r in regs:
            f.write(r.encode().ljust(REG_NAME_LEN, b"\0"))
        f.write((0).to_bytes(2, "little"))  # deref x0
        base = 0x7A00001000
        for i in range(n):
            va = base + 4 * i
            insn = bytes.fromhex("1f2003d5")  # nop
            f.write(RECORD_HEADER.pack(i, va, 1, 0, 4, 1, 0x4000, insn.ljust(16, b"\0")))
            for j, _ in enumerate(regs):
                f.write((va if regs[j] == "pc" else i * 10 + j).to_bytes(8, "little"))
            s = b"hello\0" if i % 2 == 0 else b""
            f.write(bytes([len(s) and dl]) + s.ljust(dl, b"\0"))
    path.with_name(path.name + ".libs").write_text(
        f"1 {base:x} {base + 0x10000:x} 1000 A /data/app/x/lib/arm64/libnative-lib.so\n"
    )


if __name__ == "__main__":
    write(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 10)
