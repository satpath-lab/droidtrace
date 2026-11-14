import json

import pytest
from conftest import synth

from droidtrace.exporters import export
from droidtrace.reader import TraceFormatError, open_trace


def test_roundtrip(tmp_path):
    p = tmp_path / "t.dtr"
    synth.write(p, 5)
    t = open_trace(p)
    assert t.header.reg_names == ["x0", "x1", "sp", "pc"]
    recs = list(t.records())
    assert [r.seq for r in recs] == list(range(5))
    assert recs[2].regs[3] == recs[2].vaddr
    lib = t.lib(recs[0])
    assert lib.name == "libnative-lib.so"
    assert lib.lib_offset(recs[1].vaddr) == 0x1004


def test_torn_tail_ignored(tmp_path):
    p = tmp_path / "t.dtr"
    synth.write(p, 3)
    with p.open("ab") as f:
        f.write(b"\x01" * 10)
    assert len(list(open_trace(p).records())) == 3


def test_bad_magic(tmp_path):
    p = tmp_path / "bad.dtr"
    p.write_bytes(b"XXXX" + b"\0" * 40)
    with pytest.raises(TraceFormatError):
        open_trace(p)


@pytest.mark.parametrize("fmt", ["jsonl", "csv"])
def test_export(tmp_path, fmt):
    p = tmp_path / "t.dtr"
    synth.write(p, 4)
    out = tmp_path / f"o.{fmt}"
    assert export(open_trace(p), fmt, out, lib_glob="libnative*", disasm=False) == 4
    if fmt == "jsonl":
        row = json.loads(out.read_text().splitlines()[0])
        assert row["lib"] == "libnative-lib.so" and row["pc"] == row["vaddr"]


def test_deref_string(tmp_path):
    from droidtrace.values import interpret

    p = tmp_path / "t.dtr"
    synth.write(p, 2)
    t = open_trace(p)
    r0, r1 = list(t.records())
    assert r0.mem[0].startswith(b"hello\0") and r1.mem == {}
    assert interpret(t, "x0", r0.regs[0], r0.mem.get(0))["string"] == "hello"


def test_interpret_types(tmp_path):
    import struct

    from droidtrace.values import interpret

    p = tmp_path / "t.dtr"
    synth.write(p, 1)
    t = open_trace(p)
    assert interpret(t, "x1", (1 << 64) - 5, None)["int"] == "-5"
    assert interpret(t, "x1", 1, None)["bool"] == "true"
    assert interpret(t, "x1", 0x41, None)["char"] == "'A'"
    bits = struct.unpack("<Q", struct.pack("<d", 3.25))[0]
    assert interpret(t, "v0", bits, None)["best"] == "3.25"
    assert interpret(t, "x2", 0x7A00001234, None)["ptr"] == "libnative-lib.so+0x1234"


def test_export_stable_columns(tmp_path):
    """Rows must all have the same columns even when only some carry strings."""
    from droidtrace.exporters import rows

    p = tmp_path / "t.dtr"
    synth.write(p, 4)  # x0 points at a string on even rows only
    rs = list(rows(open_trace(p), disasm=False))
    assert len({tuple(r) for r in rs}) == 1
    assert rs[0]["x0_str"] == "hello" and rs[1]["x0_str"] is None
    out = tmp_path / "o.csv"
    t = open_trace(p)
    from droidtrace.exporters import export

    assert export(t, "csv", out, disasm=False) == 4


def test_partial_string_prefix():
    from droidtrace.values import as_string

    assert as_string(b"hello\0junk") == "hello"
    assert as_string(b"http://c2.ex\x90\x32\x66") == "http://c2.ex…"  # buffer still being written
    assert as_string(b"\x90\x32ab") is None
    assert as_string(b"ok\0") == "ok"
