"""Assertions shared by the plugin and built-in tracer e2e tests."""

import json
import sys

with open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/w/t.jsonl") as fh:
    rows = [json.loads(line) for line in fh]
assert rows, "no records (TB flush after reload failed?)"
assert [r["seq"] for r in rows] == list(range(len(rows))), "seq not ordered"
assert all(r["pc"] == r["vaddr"] for r in rows), "pc mismatch"
assert all(r["lib"] == "libtarget.so" for r in rows), "attribution"
assert not any(r["x0"] == "0x1" and r["x1"] == "0x2" for r in rows), "pre-trace call leaked"
i = next(i for i, r in enumerate(rows) if r["x0"] == "0x1111" and r["x1"] == "0x2222")
ret = next(j for j in range(i, len(rows)) if rows[j]["insn"].startswith("ret"))
assert int(rows[ret]["x0"], 16) == (0x1111 * 3 + 0x2222) ^ 0x5A, "return value"
s = next(r for r in rows if (r.get("x0_str") or "").startswith("http://c2"))
print("secret_fn entry:", rows[i]["lib_offset"], "returns", rows[ret]["x0"])
print("str_fn:", s["lib_offset"], s["insn"], "x0 ->", repr(s["x0_str"]), " v0 ->", s["v0_f"])
assert s["v0_f"] == "2.5"
print("E2E PASS:", len(rows), "instructions")
