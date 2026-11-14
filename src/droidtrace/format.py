"""Binary trace format constants. Keep in sync with plugin/include/dtrace_format.h."""

from __future__ import annotations

import struct
from enum import IntEnum, IntFlag

MAGIC = b"DTRC"
FORMAT_VERSION = 2
REG_NAME_LEN = 32
MAX_INSN_BYTES = 16

# magic, version, arch, nregs, header_size, start_ns, deref_n, deref_len, reserved
FILE_HEADER = struct.Struct("<4sHHIIQHHI")
RECORD_HEADER = struct.Struct(f"<QQIHBBQ{MAX_INSN_BYTES}s")


class Arch(IntEnum):
    UNKNOWN = 0
    AARCH64 = 1
    X86_64 = 2


class RecordFlags(IntFlag):
    NONE = 0
    PROC_VERIFIED = 1 << 0
    REG_TRUNC = 1 << 1
