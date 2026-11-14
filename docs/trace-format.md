# Trace format (`.dtr`, version 1)

Little-endian. Defined in `plugin/include/dtrace_format.h` and `src/droidtrace/format.py`.

## File header (24 bytes + names)

| Offset | Type | Field |
|---|---|---|
| 0 | char[4] | magic `DTRC` |
| 4 | u16 | version (1) |
| 6 | u16 | arch: 1 = aarch64, 2 = x86_64 |
| 8 | u32 | `nregs` |
| 12 | u32 | `header_size` = 24 + 32·nregs |
| 16 | u64 | start time, Unix ns |
| 24 | char[32]·nregs | register names, NUL-padded |

## Record (48 + 8·nregs bytes)

| Offset | Type | Field |
|---|---|---|
| 0 | u64 | `seq` — global execution order |
| 8 | u64 | `vaddr` |
| 16 | u32 | `range_id` → `.libs` sidecar |
| 20 | u16 | `vcpu` |
| 22 | u8 | `insn_len` |
| 23 | u8 | flags: bit0 `PROC_VERIFIED`, bit1 `REG_TRUNC` |
| 24 | u64 | `asid` (page-table base) |
| 32 | u8[16] | instruction bytes |
| 48 | u64·nregs | register values *before* the instruction executes |

Records are written in `seq` order. A truncated trailing record (crash) is ignored by readers.

## `.libs` sidecar

Text, one line per range, appended when first seen:

```
<id> <start hex> <end hex> <file_offset hex> <A|-> <path>
```

Library-relative offset = `vaddr - start + file_offset` (matches offsets in IDA/Ghidra
when the library is loaded at base 0).
