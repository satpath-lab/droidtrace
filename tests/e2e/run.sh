#!/bin/sh
# End-to-end plugin test using qemu-aarch64 (user mode).
# docker build -t droidtrace-e2e -f tests/e2e/Dockerfile . && docker run --rm -v "$PWD":/src:ro droidtrace-e2e sh /src/tests/e2e/run.sh
set -eu
qemu-aarch64 --version | head -1
cmake -S /src/plugin -B /tmp/b -DQEMU_SRC=/opt/qemu-inc >/dev/null && cmake --build /tmp/b 2>&1 | grep -E "error|warning|Built" || true
W=/tmp/w; mkdir -p $W
gcc -O1 -shared -fPIC /src/tests/e2e/libtarget.c -o $W/libtarget.so
gcc -O1 /src/tests/e2e/host.c -o $W/host -ldl
: > $W/ranges.txt
P=/tmp/b/libinsntrace.so,out=$W/trace.dtr,ranges=$W/ranges.txt,reload_ms=100
qemu-aarch64 -plugin $P $W/host $W/libtarget.so $W/ranges.txt $W/ranges.tmp

echo "--- overhead on untraced code (200M-iteration loop) ---"
t0=$(date +%s.%N); qemu-aarch64 $W/host $W/libtarget.so >/dev/null; \
t1=$(date +%s.%N); qemu-aarch64 $W/host $W/libtarget.so x x 200000000 >/dev/null; t2=$(date +%s.%N)
: > $W/r2.txt
qemu-aarch64 -plugin /tmp/b/libinsntrace.so,out=$W/t2.dtr,ranges=$W/r2.txt,reload_ms=100 \
  $W/host $W/libtarget.so $W/r2.txt $W/r2.tmp 200000000 >/dev/null 2>&1; t3=$(date +%s.%N)
python3 -c "b=$t2-$t1; p=$t3-$t2; print(f'no plugin: {b:.2f}s  with plugin: {p:.2f}s  overhead: {100*(p-b)/b:+.1f}%')"

python3 -m venv /tmp/v && /tmp/v/bin/pip -q install "/src[disasm]" 2>&1 | grep -v notice || true
cd $W && /tmp/v/bin/droidtrace info trace.dtr | head -4
/tmp/v/bin/droidtrace export trace.dtr --format jsonl -o t.jsonl
/tmp/v/bin/python /src/tests/e2e/check.py
