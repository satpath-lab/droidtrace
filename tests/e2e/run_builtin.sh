#!/bin/sh
# End-to-end test of the built-in tracer (patched qemu-aarch64). $QEMU = patched binary.
set -eu
QEMU=${QEMU:-qemu-aarch64}
W=/tmp/wb; rm -rf $W; mkdir -p $W
gcc -O1 -shared -fPIC /src/tests/e2e/libtarget.c -o $W/libtarget.so
gcc -O1 /src/tests/e2e/host.c -o $W/host -ldl
: > $W/ranges.txt
DROIDTRACE_OUT=$W/trace.dtr DROIDTRACE_RANGES=$W/ranges.txt DROIDTRACE_RELOAD_MS=100 \
  DROIDTRACE_MAX_BYTES=50000000 $QEMU $W/host $W/libtarget.so $W/ranges.txt $W/ranges.tmp
[ -x /tmp/v/bin/droidtrace ] || { python3 -m venv /tmp/v && /tmp/v/bin/pip -q install "/src[disasm]" 2>&1 | grep -v notice || true; }
cd $W && /tmp/v/bin/droidtrace info trace.dtr | head -4
/tmp/v/bin/droidtrace export trace.dtr --format jsonl -o t.jsonl
/tmp/v/bin/python /src/tests/e2e/check.py /tmp/wb/t.jsonl
