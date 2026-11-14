/* SPDX-License-Identifier: GPL-2.0-or-later
 * DroidTrace built-in AArch64 instruction tracer (translation-time hook). */
#ifndef DTRACE_A64_H
#define DTRACE_A64_H
#include <stdbool.h>
#include <stdint.h>

/* Called while translating each guest instruction. Returns true if it must be traced and
 * fills *meta (range_id << 1 | anchor) for the runtime helper. Cheap when disabled. */
bool dtrace_a64_want(uint64_t pc, uint32_t *meta);
#endif
