#!/bin/sh
# Apply the DroidTrace built-in tracer to an upstream QEMU source tree (tested: 10.0.3).
#   sh qemu-patch/apply.sh /path/to/qemu-src
set -eu
Q=${1:?usage: apply.sh QEMU_SRC}
HERE=$(cd "$(dirname "$0")" && pwd)
T=$Q/target/arm/tcg
grep -q dtrace-a64 "$T/meson.build" && { echo "already applied"; exit 0; }
cp "$HERE/dtrace-a64.c" "$HERE/dtrace-a64.h" "$T/"
cp "$HERE/../plugin/include/dtrace_format.h" "$HERE/../plugin/include/ranges.h" "$T/"
cp "$HERE/../plugin/src/ranges.c" "$T/dtrace-ranges.c"
sed -i "s/^  'helper-a64.c',/  'helper-a64.c',\n  'dtrace-a64.c',\n  'dtrace-ranges.c',/" "$T/meson.build"
echo 'DEF_HELPER_FLAGS_4(dtrace_insn, TCG_CALL_NO_WG, void, env, i64, i32, i32)' >> "$T/helper-a64.h"
# include + hook right after the instruction word is fetched
sed -i '0,/^#include "qemu\/osdep.h"/s//#include "qemu\/osdep.h"\n#include "dtrace-a64.h"/' "$T/translate-a64.c"
sed -i 's/^    s->insn = insn;$/    s->insn = insn;\n    {\n        uint32_t dt_meta;\n        if (dtrace_a64_want(pc, \&dt_meta)) {\n            gen_helper_dtrace_insn(tcg_env, tcg_constant_i64(pc),\n                                   tcg_constant_i32(insn), tcg_constant_i32(dt_meta));\n        }\n    }/' "$T/translate-a64.c"
# user mode exits via _exit(): flush from preexit_cleanup (weak: other targets lack it)
sed -i 's/^void preexit_cleanup(CPUArchState \*env, int code)$/void dtrace_a64_flush(void) __attribute__((weak));\nvoid preexit_cleanup(CPUArchState *env, int code)/; s/^        qemu_plugin_user_exit();$/        qemu_plugin_user_exit();\n        if (dtrace_a64_flush) {\n            dtrace_a64_flush();\n        }/' "$Q/linux-user/exit.c"
grep -q gen_helper_dtrace_insn "$T/translate-a64.c" || { echo "hook not inserted"; exit 1; }
echo "DroidTrace built-in tracer applied to $Q"
