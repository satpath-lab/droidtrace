/* SPDX-License-Identifier: GPL-2.0-or-later
 *
 * DroidTrace built-in AArch64 tracer.
 *
 * Unlike the TCG plugin, this runs inside QEMU's own translator: for each instruction in a
 * traced range we emit one direct helper call that copies the architectural state straight
 * out of CPUARMState (no gdbstub register marshalling, no plugin dispatch) into an in-memory
 * buffer. Output is the same .dtr v2 format as the plugin.
 *
 * Configuration (environment variables, read once):
 *   DROIDTRACE_OUT        trace file (enables tracing)
 *   DROIDTRACE_RANGES     range file, hot-reloaded on mtime change
 *   DROIDTRACE_DEREF      bytes captured behind pointer args x0..x7 (default 32, 0 = off)
 *   DROIDTRACE_STRICT     1 (default) = drop instructions from other address spaces
 *   DROIDTRACE_MAX_BYTES  hard cap on trace size (default 2 GiB); tracing stops at the cap
 *   DROIDTRACE_RELOAD_MS  range poll interval (default 250)
 */
#include "qemu/osdep.h"
#include "qemu/atomic.h"
#include "qemu/thread.h"
#include "cpu.h"
#include "exec/helper-proto.h"
#include "exec/cpu-common.h"
#include "exec/tb-flush.h"
#include "hw/core/cpu.h"
#include "dtrace-a64.h"
#include "dtrace_format.h"
#include "ranges.h"

#define NGPR 31
#define NREGS (NGPR + 3 + 8) /* x0..x30, sp, pc, cpsr, v0..v7 */
#define NDEREF 8             /* x0..x7 */

static const char *reg_names[NREGS] = {
    "x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13",
    "x14", "x15", "x16", "x17", "x18", "x19", "x20", "x21", "x22", "x23", "x24", "x25",
    "x26", "x27", "x28", "x29", "x30", "sp", "pc", "cpsr",
    "v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7"};

static struct {
    bool enabled, strict;
    unsigned deref_len, reload_ms;
    uint64_t max_bytes, written;
    char *ranges_path;
    FILE *out, *libs;
    QemuMutex lock;
    uint8_t *buf;
    size_t buf_used, buf_cap;
    uint64_t seq;
    dt_range_table *ranges; /* atomically swapped */
    GPtrArray *retired;
    uint32_t next_id;
    uint64_t target_asid;
    bool capped;
} T;

static pthread_once_t init_once = PTHREAD_ONCE_INIT;

/* ---------- output ---------- */
static void flush_locked(void)
{
    if (T.buf_used) {
        fwrite(T.buf, 1, T.buf_used, T.out);
        T.buf_used = 0;
    }
    fflush(T.out);
}

void dtrace_a64_flush(void);
void dtrace_a64_flush(void)
{
    if (!T.enabled) return;
    qemu_mutex_lock(&T.lock);
    flush_locked();
    fclose(T.out);
    T.enabled = false;
    qemu_mutex_unlock(&T.lock);
    fprintf(stderr, "droidtrace(builtin): wrote %" PRIu64 " records\n", T.seq);
}

static void write_header(void)
{
    dt_file_header h = {0};
    memcpy(h.magic, DT_MAGIC, 4);
    h.version = DT_FORMAT_VERSION;
    h.arch = DT_ARCH_AARCH64;
    h.nregs = NREGS;
    h.deref_n = T.deref_len ? NDEREF : 0;
    h.deref_len = (uint16_t)T.deref_len;
    h.header_size = sizeof h + NREGS * DT_REG_NAME_LEN + h.deref_n * 2;
    h.start_unix_ns = g_get_real_time() * 1000ull;
    fwrite(&h, sizeof h, 1, T.out);
    for (int i = 0; i < NREGS; i++) {
        char n[DT_REG_NAME_LEN] = {0};
        g_strlcpy(n, reg_names[i], sizeof n);
        fwrite(n, sizeof n, 1, T.out);
    }
    for (uint16_t i = 0; i < h.deref_n; i++) fwrite(&i, 2, 1, T.out);
    fflush(T.out);
}

/* ---------- range reload ---------- */
static void flush_work(CPUState *cpu, run_on_cpu_data d)
{
    tb_flush(cpu); /* re-translate so newly traced code gets the helper call */
}

static void reload(void)
{
    dt_range_table *t = dt_ranges_load(T.ranges_path, T.libs, &T.next_id);
    if (!t) return;
    dt_range_table *old = qatomic_xchg(&T.ranges, t);
    if (old) g_ptr_array_add(T.retired, old); /* readers may still hold it */
    qatomic_set(&T.target_asid, 0);
    CPUState *cpu = first_cpu;
    if (cpu) async_run_on_cpu(cpu, flush_work, RUN_ON_CPU_NULL);
}

static void *reload_thread(void *arg)
{
    gint64 last = -1;
    for (;;) {
        struct stat st;
        if (stat(T.ranges_path, &st) == 0) {
            gint64 m = (gint64)st.st_mtime * 1000000000 +
#ifdef __APPLE__
                       st.st_mtimespec.tv_nsec;
#else
                       st.st_mtim.tv_nsec;
#endif
            if (m != last) { last = m; reload(); }
        }
        qemu_mutex_lock(&T.lock);
        if (T.enabled) flush_locked(); /* keep the file fresh for the live viewer */
        qemu_mutex_unlock(&T.lock);
        g_usleep(T.reload_ms * 1000);
    }
    return NULL;
}

static unsigned env_uint(const char *k, unsigned def)
{
    const char *v = getenv(k);
    return v && *v ? (unsigned)strtoul(v, NULL, 0) : def;
}

static void init(void)
{
    const char *out = getenv("DROIDTRACE_OUT");
    if (!out || !*out) return;
    T.out = fopen(out, "wb");
    if (!T.out) { perror(out); return; }
    g_autofree char *libs = g_strdup_printf("%s.libs", out);
    T.libs = fopen(libs, "w");
    T.deref_len = MIN(env_uint("DROIDTRACE_DEREF", 32), 255);
    T.strict = env_uint("DROIDTRACE_STRICT", 1);
    T.reload_ms = MAX(env_uint("DROIDTRACE_RELOAD_MS", 250), 10);
    const char *mb = getenv("DROIDTRACE_MAX_BYTES");
    T.max_bytes = mb && *mb ? strtoull(mb, NULL, 0) : (2ull << 30);
    T.buf_cap = 16u << 20;
    T.buf = g_malloc(T.buf_cap);
    T.retired = g_ptr_array_new();
    T.next_id = 1;
    qemu_mutex_init(&T.lock);
    write_header();
    T.enabled = true;
    atexit(dtrace_a64_flush); /* system mode; user mode calls it from preexit_cleanup */
    const char *r = getenv("DROIDTRACE_RANGES");
    if (r && *r) {
        T.ranges_path = g_strdup(r);
        reload();
        QemuThread th;
        qemu_thread_create(&th, "droidtrace-reload", reload_thread, NULL,
                           QEMU_THREAD_DETACHED);
    }
    fprintf(stderr, "droidtrace(builtin): tracing to %s (cap %.1f MB)\n", out, T.max_bytes / 1e6);
}

/* ---------- translation-time filter ---------- */
bool dtrace_a64_want(uint64_t pc, uint32_t *meta)
{
    pthread_once(&init_once, init);
    if (!qatomic_read(&T.enabled) || qatomic_read(&T.capped)) return false;
    if (pc >= 0x0001000000000000ull) return false; /* kernel / TTBR1 code */
    const dt_range *r = dt_ranges_find(qatomic_read(&T.ranges), pc);
    if (!r) return false;
    *meta = (r->id << 1) | (r->anchor ? 1 : 0);
    return true;
}

/* ---------- runtime helper: one call per traced instruction ---------- */
void HELPER(dtrace_insn)(CPUARMState *env, uint64_t pc, uint32_t insn, uint32_t meta)
{
    uint8_t flags = 0;
    uint64_t asid = env->cp15.ttbr0_el[1] & ~0xffff000000000000ull;
    uint64_t want = qatomic_read(&T.target_asid);
    if ((meta & 1) && !want && asid) {
        qatomic_cmpxchg(&T.target_asid, 0, asid);
        want = asid;
    }
    if (want && asid) {
        if (asid != want) { if (T.strict) return; }
        else flags |= DT_F_PROC_VERIFIED;
    }

    const size_t dslot = 1 + T.deref_len;
    const size_t rec = sizeof(dt_record_hdr) + NREGS * 8 + (T.deref_len ? NDEREF * dslot : 0);
    uint8_t tmp[sizeof(dt_record_hdr) + NREGS * 8 + NDEREF * 256];

    dt_record_hdr *h = (dt_record_hdr *)tmp;
    memset(h, 0, sizeof *h);
    h->vaddr = pc;
    h->range_id = meta >> 1;
    h->vcpu = (uint16_t)env_cpu(env)->cpu_index;
    h->insn_len = 4;
    h->flags = flags;
    h->asid = asid;
    memcpy(h->insn, &insn, 4);

    uint64_t *regs = (uint64_t *)(tmp + sizeof *h);
    memcpy(regs, env->xregs, NGPR * 8); /* x0..x30 in one copy */
    regs[31] = env->xregs[31];          /* current SP */
    regs[32] = pc;
    regs[33] = pstate_read(env);
    for (int i = 0; i < 8; i++) regs[34 + i] = env->vfp.zregs[i].d[0];

    if (T.deref_len) {
        uint8_t *d = (uint8_t *)(regs + NREGS);
        CPUState *cs = env_cpu(env);
        for (int k = 0; k < NDEREF; k++, d += dslot) {
            uint64_t v = regs[k];
            d[0] = 0;
            memset(d + 1, 0, T.deref_len);
            if (v < 0x10000 || v >= 0x0001000000000000ull) continue;
            unsigned len = MIN(T.deref_len, 0x1000 - (v & 0xfff));
            if (cpu_memory_rw_debug(cs, v, d + 1, len, false) == 0) {
                if (len < T.deref_len &&
                    cpu_memory_rw_debug(cs, v + len, d + 1 + len, T.deref_len - len, false) == 0)
                    len = T.deref_len;
                d[0] = (uint8_t)len;
            }
        }
    }

    qemu_mutex_lock(&T.lock);
    if (!T.enabled || T.capped) { qemu_mutex_unlock(&T.lock); return; }
    if (T.written + rec > T.max_bytes) {
        T.capped = true;
        flush_locked();
        fprintf(stderr, "droidtrace(builtin): size cap reached, tracing stopped\n");
        qemu_mutex_unlock(&T.lock);
        return;
    }
    h->seq = T.seq++;
    if (T.buf_used + rec > T.buf_cap) flush_locked();
    memcpy(T.buf + T.buf_used, tmp, rec);
    T.buf_used += rec;
    T.written += rec;
    qemu_mutex_unlock(&T.lock);
}
