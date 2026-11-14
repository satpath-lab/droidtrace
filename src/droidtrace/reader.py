"""Streaming reader for .dtr trace files and their .libs sidecar."""

from __future__ import annotations

import mmap
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .format import (
    FILE_HEADER,
    FORMAT_VERSION,
    MAGIC,
    RECORD_HEADER,
    REG_NAME_LEN,
    Arch,
    RecordFlags,
)


class TraceFormatError(ValueError):
    pass


@dataclass(frozen=True)
class LibRange:
    id: int
    start: int
    end: int
    file_offset: int
    anchor: bool
    path: str

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    def lib_offset(self, vaddr: int) -> int:
        """Offset of vaddr within the library file (as used by disassemblers/IDA)."""
        return vaddr - self.start + self.file_offset


@dataclass(frozen=True)
class Record:
    seq: int
    vaddr: int
    range_id: int
    vcpu: int
    insn: bytes
    flags: RecordFlags
    asid: int
    regs: tuple[int, ...]
    mem: dict[int, bytes] = field(default_factory=dict)  # reg index -> bytes at *reg


@dataclass
class TraceHeader:
    version: int
    arch: Arch
    reg_names: list[str]
    header_size: int
    start_unix_ns: int
    deref_regs: list[int] = field(default_factory=list)
    deref_len: int = 0

    @property
    def record_size(self) -> int:
        return (
            RECORD_HEADER.size
            + 8 * len(self.reg_names)
            + len(self.deref_regs) * (1 + self.deref_len)
        )


class RecordDecoder:
    def __init__(self, h: TraceHeader) -> None:
        self.h = h
        self.regs = struct.Struct(f"<{len(h.reg_names)}Q")
        self.mem_off = RECORD_HEADER.size + self.regs.size
        self.size = h.record_size

    def decode(self, buf: bytes | mmap.mmap, off: int) -> Record:
        seq, va, rid, vcpu, ilen, fl, asid, insn = RECORD_HEADER.unpack_from(buf, off)
        regs = self.regs.unpack_from(buf, off + RECORD_HEADER.size)
        mem: dict[int, bytes] = {}
        o = off + self.mem_off
        dl = self.h.deref_len
        for idx in self.h.deref_regs:
            n = min(buf[o], dl)
            if n:
                mem[idx] = bytes(buf[o + 1 : o + 1 + n])
            o += 1 + dl
        return Record(seq, va, rid, vcpu, insn[:ilen], RecordFlags(fl), asid, regs, mem)


@dataclass
class Trace:
    path: Path
    header: TraceHeader
    libs: dict[int, LibRange] = field(default_factory=dict)

    @property
    def record_size(self) -> int:
        return self.header.record_size

    def __len__(self) -> int:
        return (self.path.stat().st_size - self.header.header_size) // self.record_size

    def records(self) -> Iterator[Record]:
        dec = RecordDecoder(self.header)
        if self.path.stat().st_size <= self.header.header_size:
            return
        with self.path.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            off = self.header.header_size
            end = len(mm) - (len(mm) - off) % dec.size  # ignore torn tail record
            while off < end:
                yield dec.decode(mm, off)
                off += dec.size

    def lib(self, rec: Record) -> LibRange | None:
        return self.libs.get(rec.range_id)

    def lib_for_addr(self, addr: int) -> LibRange | None:
        for lib in self.libs.values():
            if lib.start <= addr < lib.end:
                return lib
        return None


def header_bytes_needed(head: bytes) -> int:
    """Total header size implied by the fixed part (validated)."""
    if len(head) < FILE_HEADER.size:
        raise TraceFormatError("file too small")
    magic, version, _a, nregs, _h, _s, dn, _dl, _r = FILE_HEADER.unpack_from(head)
    if magic != MAGIC:
        raise TraceFormatError(f"bad magic {magic!r}")
    if version != FORMAT_VERSION:
        raise TraceFormatError(f"unsupported version {version} (expected {FORMAT_VERSION})")
    if nregs > 4096 or dn > nregs:
        raise TraceFormatError("corrupt header")
    return int(FILE_HEADER.size + nregs * REG_NAME_LEN + dn * 2)


def _read_header(data: bytes) -> TraceHeader:
    need = header_bytes_needed(data)
    _m, version, arch, nregs, hsize, start, dn, dl, _r = FILE_HEADER.unpack_from(data)
    if hsize != need or len(data) < need:
        raise TraceFormatError("corrupt header")
    names = []
    for i in range(nregs):
        o = FILE_HEADER.size + i * REG_NAME_LEN
        names.append(data[o : o + REG_NAME_LEN].split(b"\0", 1)[0].decode("ascii", "replace"))
    o = FILE_HEADER.size + nregs * REG_NAME_LEN
    deref = list(struct.unpack_from(f"<{dn}H", data, o))
    if any(i >= nregs for i in deref):
        raise TraceFormatError("corrupt deref table")
    return TraceHeader(version, Arch(arch), names, hsize, start, deref, dl)


def parse_libs(path: Path) -> dict[int, LibRange]:
    libs: dict[int, LibRange] = {}
    if not path.exists():
        return libs
    for line in path.read_text().splitlines():
        parts = line.split(" ", 5)
        if len(parts) != 6:
            continue
        rid, s, e, o, fl, p = parts
        libs[int(rid)] = LibRange(int(rid), int(s, 16), int(e, 16), int(o, 16), fl == "A", p)
    return libs


def read_header_from(f) -> bytes:  # type: ignore[no-untyped-def]
    head = f.read(FILE_HEADER.size)
    need = header_bytes_needed(head)
    return bytes(head + f.read(need - len(head)))


def open_trace(path: str | Path) -> Trace:
    p = Path(path)
    with p.open("rb") as f:
        head = read_header_from(f)
    return Trace(p, _read_header(head), parse_libs(p.with_name(p.name + ".libs")))
