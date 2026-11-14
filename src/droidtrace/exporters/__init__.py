"""Trace exporters: jsonl, csv, parquet."""

from __future__ import annotations

import csv
import fnmatch
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..disasm import disassemble
from ..reader import Trace
from ..values import interpret, is_fp


def rows(
    trace: Trace, lib_glob: str | None = None, disasm: bool = True
) -> Iterator[dict[str, Any]]:
    names = trace.header.reg_names
    deref = set(trace.header.deref_regs)
    for r in trace.records():
        lib = trace.lib(r)
        if lib_glob and (lib is None or not fnmatch.fnmatch(lib.name, lib_glob)):
            continue
        row: dict[str, Any] = {
            "seq": r.seq,
            "vcpu": r.vcpu,
            "vaddr": f"0x{r.vaddr:x}",
            "lib": lib.name if lib else None,
            "lib_path": lib.path if lib else None,
            "lib_offset": f"0x{lib.lib_offset(r.vaddr):x}" if lib else None,
            "insn_bytes": r.insn.hex(),
            "verified": bool(r.flags & 1),
        }
        if disasm:
            row["insn"] = disassemble(trace.header.arch, r.insn, r.vaddr)
        # Fixed columns on every row (CSV/Parquet need a stable schema): pointer-capable
        # registers get <reg>_str, floating-point registers get <reg>_f.
        for i, (n, v) in enumerate(zip(names, r.regs, strict=True)):
            row[n] = f"0x{v:x}"
            iv = interpret(trace, n, v, r.mem.get(i))
            if is_fp(n):
                row[f"{n}_f"] = iv["best"]
            elif i in deref:
                row[f"{n}_str"] = iv.get("string")
        yield row


def export(
    trace: Trace, fmt: str, out: Path, lib_glob: str | None = None, disasm: bool = True
) -> int:
    it = rows(trace, lib_glob, disasm)
    n = 0
    if fmt == "jsonl":
        with out.open("w") as f:
            for row in it:
                f.write(json.dumps(row) + "\n")
                n += 1
    elif fmt == "csv":
        with out.open("w", newline="") as f:
            w: csv.DictWriter[str] | None = None
            for row in it:
                if w is None:
                    w = csv.DictWriter(f, fieldnames=list(row))
                    w.writeheader()
                w.writerow(row)
                n += 1
    elif fmt == "parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq

        writer = None
        batch: list[dict[str, Any]] = []
        for row in it:
            batch.append(row)
            if len(batch) >= 100_000:
                tbl = pa.Table.from_pylist(batch)
                writer = writer or pq.ParquetWriter(out, tbl.schema, compression="zstd")
                writer.write_table(tbl)
                n += len(batch)
                batch = []
        if batch:
            tbl = pa.Table.from_pylist(batch)
            writer = writer or pq.ParquetWriter(out, tbl.schema, compression="zstd")
            writer.write_table(tbl)
            n += len(batch)
        if writer:
            writer.close()
    else:
        raise ValueError(f"unknown format {fmt}")
    return n
