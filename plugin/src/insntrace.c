/* SPDX-License-Identifier: Apache-2.0
 *
 * DroidTrace QEMU TCG plugin: logs, in execution order, every guest instruction that
 * falls inside the configured library ranges, with the register file captured before
 * the instruction executes. Requires QEMU >= 9.0 (register read API).
 *
 * Performance design:
 *   - Only instructions inside the configured ranges are instrumented (decided at translation
 *     time); all other guest code runs at plain TCG speed with zero callbacks.
 *   - When the range file changes, the plugin requests qemu_plugin_reset() from a vCPU thread,
 *     which flushes the translation cache so already-translated code is re-instrumented.
 *   - The address-space id (TTBR0/CR3) is read once per translated block, not per instruction.
 *
 * Plugin args (-plugin libinsntrace.so,arg=val,...):
 *   out=<path>        trace output (.dtr); a <path>.libs sidecar is written too
 *   ranges=<path>     range file, hot-reloaded when its mtime changes
 *   regs=<a:b:c>      register names to capture, or "gpr" (default) / "all"
 *   deref=<n>         bytes of memory captured behind pointer-valued argument registers
 *                     (default 32, 0 = off) so strings/structs are visible
 *   deref_regs=<a:b>  registers to dereference (default x0..x7 / rdi,rsi,rdx,rcx,r8,r9,rax)
 *   asid_reg=<name>   address-space register (default TTBR0_EL1 / cr3)
 *   strict=on|off     drop records whose ASID != learned target ASID (default on)
 *   reload_ms=<n>     range-file poll interval (default 250)
 *   max_bytes=<n>     hard cap on trace size; tracing stops at the cap (default 2 GiB)
 *   bufsize=<bytes>   stdio buffer for the output (default 64 MiB)
 */
#include <glib.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <qemu-plugin.h>

#include "dtrace_format.h"
#include "ranges.h"

#ifdef __APPLE__
#define DT_MTIME_NS(st) ((st).st_mtimespec.tv_nsec)
#else
#define DT_MTIME_NS(st) ((st).st_mtim.tv_nsec)
#endif

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;

/* ---------- configuration / global state ---------- */
static char *out_path, *ranges_path, *regs_spec, *asid_reg_name, *deref_spec;
static unsigned deref_len = 32;
static GArray *deref_idx; /* uint16 indices into sel_names */
static bool strict = true;
static unsigned reload_ms = 250;
static size_t bufsize = 64u << 20;
static uint64_t max_bytes = 2ull << 30, written;
static bool capped;

static FILE *out, *libs_log;
static GMutex out_lock;
static uint64_t seq;
static enum dt_arch arch;

static _Atomic(dt_range_table *) ranges;
static GPtrArray *retired_tables; /* freed at exit: no reader can hold them then */
static uint32_t next_range_id = 1;
static _Atomic uint64_t target_asid; /* learned from first hit in an anchor range */
static atomic_bool running = true;
static pthread_t reload_thread;
static qemu_plugin_id_t plugin_id;
static atomic_bool reset_pending, reset_running;
static void register_callbacks(qemu_plugin_id_t id);

static GPtrArray *sel_names; /* char* register names chosen at first vcpu init */
static bool header_written;

typedef struct {
    bool in_target;  /* set per TB from the ASID check */
    uint8_t tb_flags;
    uint64_t tb_asid;
    int pc_slot;     /* index of pc/rip in sel_names, or -1 */
    GArray *handles; /* struct qemu_plugin_register* in sel_names order (NULL = missing) */
    struct qemu_plugin_register *asid;
    GByteArray *scratch;
    GByteArray *mem;
    uint8_t *deref_buf; /* deref_n * (1 + deref_len) */
} vcpu_ctx;
static struct qemu_plugin_scoreboard *vcpus;

typedef struct {
    uint64_t vaddr;
    uint32_t range_id;
    uint8_t len;
    uint8_t bytes[DT_MAX_INSN_BYTES];
} insn_info;
static GHashTable *insn_cache; /* vaddr -> insn_info*, dedups per-TB allocations */
static GMutex insn_cache_lock;

/* ---------- helpers ---------- */
static bool is_user_address(uint64_t va)
{
    /* Both AArch64 (TTBR0) and x86_64 canonical lower half. Kernel code is never traced. */
    return va < 0x0001000000000000ull;
}

static const char *aarch64_gpr[] = {
    "x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
    "x12", "x13", "x14", "x15", "x16", "x17", "x18", "x19", "x20", "x21", "x22",
    "x23", "x24", "x25", "x26", "x27", "x28", "x29", "x30", "sp", "pc", "cpsr",
    /* FP/SIMD argument registers: low 64 bits hold double / float arguments */
    "v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", NULL};
static const char *x86_64_gpr[] = {
    "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "r8", "r9", "r10",
    "r11", "r12", "r13", "r14", "r15", "rip", "eflags", "fs_base",
    "xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7", NULL};
static const char *aarch64_deref[] = {"x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", NULL};
static const char *x86_64_deref[] = {"rdi", "rsi", "rdx", "rcx", "r8", "r9", "rax", NULL};

static void detect_arch(GArray *descs)
{
    for (guint i = 0; i < descs->len; i++) {
        const char *n = g_array_index(descs, qemu_plugin_reg_descriptor, i).name;
        if (!g_strcmp0(n, "x30")) { arch = DT_ARCH_AARCH64; return; }
        if (!g_strcmp0(n, "rax")) { arch = DT_ARCH_X86_64; return; }
    }
}

static void choose_registers(GArray *descs)
{
    sel_names = g_ptr_array_new_with_free_func(g_free);
    if (regs_spec && !g_strcmp0(regs_spec, "all")) {
        for (guint i = 0; i < descs->len; i++)
            g_ptr_array_add(sel_names,
                g_strdup(g_array_index(descs, qemu_plugin_reg_descriptor, i).name));
    } else if (regs_spec && g_strcmp0(regs_spec, "gpr")) {
        gchar **parts = g_strsplit(regs_spec, ":", -1);
        for (gchar **p = parts; *p; p++) if (**p) g_ptr_array_add(sel_names, g_strdup(*p));
        g_strfreev(parts);
    } else {
        const char **list = arch == DT_ARCH_X86_64 ? x86_64_gpr : aarch64_gpr;
        for (; *list; list++) g_ptr_array_add(sel_names, g_strdup(*list));
    }
    deref_idx = g_array_new(FALSE, FALSE, sizeof(uint16_t));
    if (deref_len) {
        gchar **want = deref_spec ? g_strsplit(deref_spec, ":", -1) : NULL;
        const char **def = arch == DT_ARCH_X86_64 ? x86_64_deref : aarch64_deref;
        for (guint i = 0; i < sel_names->len; i++) {
            const char *n = g_ptr_array_index(sel_names, i);
            bool hit = false;
            if (want) { for (gchar **w = want; *w; w++) hit |= !g_ascii_strcasecmp(*w, n); }
            else { for (const char **d = def; *d; d++) hit |= !g_ascii_strcasecmp(*d, n); }
            if (hit) { uint16_t k = (uint16_t)i; g_array_append_val(deref_idx, k); }
        }
        g_strfreev(want);
    }
    if (!asid_reg_name)
        asid_reg_name = g_strdup(arch == DT_ARCH_X86_64 ? "cr3" : "TTBR0_EL1");
}

static void write_header(void)
{
    dt_file_header h = {0};
    memcpy(h.magic, DT_MAGIC, 4);
    h.version = DT_FORMAT_VERSION;
    h.arch = arch;
    h.nregs = sel_names->len;
    h.deref_n = (uint16_t)deref_idx->len;
    h.deref_len = (uint16_t)deref_len;
    h.header_size = sizeof h + sel_names->len * DT_REG_NAME_LEN + deref_idx->len * 2;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    h.start_unix_ns = (uint64_t)ts.tv_sec * 1000000000ull + ts.tv_nsec;
    fwrite(&h, sizeof h, 1, out);
    for (guint i = 0; i < sel_names->len; i++) {
        char name[DT_REG_NAME_LEN] = {0};
        g_strlcpy(name, g_ptr_array_index(sel_names, i), sizeof name);
        fwrite(name, sizeof name, 1, out);
    }
    fwrite(deref_idx->data, sizeof(uint16_t), deref_idx->len, out);
    fflush(out);
}

static uint64_t read_u64(struct qemu_plugin_register *r, GByteArray *buf, bool *trunc)
{
    if (!r) return 0;
    g_byte_array_set_size(buf, 0);
    int sz = qemu_plugin_read_register(r, buf);
    if (sz <= 0) return 0;
    (void)trunc; /* SIMD/SVE regs: only the low 64 bits (the scalar FP value) are kept */
    uint64_t v = 0;
    memcpy(&v, buf->data, sz < 8 ? sz : 8); /* guest and host LE for supported arches */
    return v;
}

/* ---------- range hot reload ---------- */
static void reload_ranges(void)
{
    dt_range_table *t = dt_ranges_load(ranges_path, libs_log, &next_range_id);
    if (!t) return;
    dt_range_table *old = atomic_exchange(&ranges, t);
    if (old) {
        g_mutex_lock(&out_lock);
        g_ptr_array_add(retired_tables, old);
        g_mutex_unlock(&out_lock);
    }
    /* New process maps may mean a new target process; re-learn its ASID. */
    atomic_store(&target_asid, 0);
    /* Already-translated code must be re-instrumented: ask a vCPU thread to reset. */
    atomic_store(&reset_pending, true);
}

static void *reload_loop(void *arg)
{
    (void)arg;
    struct timespec last = {0};
    while (atomic_load(&running)) {
        struct stat st;
        if (ranges_path && stat(ranges_path, &st) == 0 &&
            (st.st_mtime != last.tv_sec || DT_MTIME_NS(st) != last.tv_nsec)) {
            last.tv_sec = st.st_mtime;
            last.tv_nsec = DT_MTIME_NS(st);
            reload_ranges();
        }
        g_usleep(reload_ms * 1000);
    }
    return NULL;
}

/* ---------- callbacks ---------- */
static void vcpu_init(qemu_plugin_id_t id, unsigned int vcpu_index)
{
    (void)id;
    g_autoptr(GArray) descs = qemu_plugin_get_registers();
    g_mutex_lock(&out_lock);
    if (!header_written) {
        detect_arch(descs);
        choose_registers(descs);
        write_header();
        header_written = true;
    }
    g_mutex_unlock(&out_lock);

    vcpu_ctx *c = qemu_plugin_scoreboard_find(vcpus, vcpu_index);
    c->handles = g_array_new(FALSE, TRUE, sizeof(struct qemu_plugin_register *));
    c->scratch = g_byte_array_new();
    c->mem = g_byte_array_new();
    c->deref_buf = g_malloc0(deref_idx->len * (1 + deref_len) + 1);
    for (guint i = 0; i < sel_names->len; i++) {
        struct qemu_plugin_register *h = NULL;
        for (guint j = 0; j < descs->len; j++) {
            qemu_plugin_reg_descriptor *d = &g_array_index(descs, qemu_plugin_reg_descriptor, j);
            if (!g_ascii_strcasecmp(d->name, g_ptr_array_index(sel_names, i))) { h = d->handle; break; }
        }
        /* With SVE, AArch64 FP/SIMD regs are exposed as z0..z31 (low 64 bits == vN/dN). */
        const char *want = g_ptr_array_index(sel_names, i);
        if (!h && (want[0] == 'v' || want[0] == 'V') && g_ascii_isdigit(want[1])) {
            g_autofree char *alt = g_strdup_printf("z%s", want + 1);
            for (guint j = 0; j < descs->len; j++) {
                qemu_plugin_reg_descriptor *d = &g_array_index(descs, qemu_plugin_reg_descriptor, j);
                if (!g_ascii_strcasecmp(d->name, alt)) { h = d->handle; break; }
            }
        }
        if (!h && vcpu_index == 0)
            fprintf(stderr, "droidtrace: register '%s' not available, will log 0\n",
                    (char *)g_ptr_array_index(sel_names, i));
        g_array_append_val(c->handles, h);
    }
    c->pc_slot = -1;
    for (guint i = 0; i < sel_names->len; i++) {
        const char *n = g_ptr_array_index(sel_names, i);
        if (!g_ascii_strcasecmp(n, "pc") || !g_ascii_strcasecmp(n, "rip")) c->pc_slot = (int)i;
    }
    for (guint j = 0; j < descs->len; j++) {
        qemu_plugin_reg_descriptor *d = &g_array_index(descs, qemu_plugin_reg_descriptor, j);
        if (!g_ascii_strcasecmp(d->name, asid_reg_name)) c->asid = d->handle;
    }
}

static void tb_exec(unsigned int vcpu_index, void *udata)
{
    bool has_anchor = udata != NULL;
    vcpu_ctx *c = qemu_plugin_scoreboard_find(vcpus, vcpu_index);
    bool trunc = false;
    uint64_t asid = read_u64(c->asid, c->scratch, &trunc);
    if (arch == DT_ARCH_AARCH64) asid &= ~0xffffull; /* table base only; drop ASID bits */

    uint64_t want = atomic_load(&target_asid);
    if (has_anchor && !want && asid) {
        uint64_t zero = 0;
        if (atomic_compare_exchange_strong(&target_asid, &zero, asid)) want = asid;
    }
    c->tb_asid = asid;
    c->tb_flags = 0;
    c->in_target = true;
    if (want && asid) {
        if (asid == want) c->tb_flags |= DT_F_PROC_VERIFIED;
        else c->in_target = !strict;
    }
}

static void insn_exec(unsigned int vcpu_index, void *udata)
{
    const insn_info *ii = udata;
    vcpu_ctx *c = qemu_plugin_scoreboard_find(vcpus, vcpu_index);
    if (!c->in_target) return;

    bool trunc = false;
    guint n = c->handles->len;
    uint64_t regs[n ? n : 1];
    struct qemu_plugin_register **hs = (struct qemu_plugin_register **)c->handles->data;
    for (guint i = 0; i < n; i++) regs[i] = read_u64(hs[i], c->scratch, &trunc);
    /* QEMU only syncs the PC register at TB boundaries; the instruction address is exact. */
    if (c->pc_slot >= 0) regs[c->pc_slot] = ii->vaddr;

    /* Capture memory behind pointer-looking argument registers (strings, structs). */
    size_t dsz = deref_idx->len * (1 + deref_len);
    for (guint k = 0; k < deref_idx->len; k++) {
        uint8_t *slot = c->deref_buf + k * (1 + deref_len);
        uint64_t v = regs[g_array_index(deref_idx, uint16_t, k)];
        slot[0] = 0;
        if (v < 0x10000 || !is_user_address(v)) continue;
        g_byte_array_set_size(c->mem, 0);
        /* Read up to the page end first so a string near a page boundary still works. */
        uint64_t to_page = 0x1000 - (v & 0xfff);
        unsigned len = (unsigned)MIN(deref_len, to_page);
        if (qemu_plugin_read_memory_vaddr(v, c->mem, len)) {
            if (len < deref_len) {
                g_autoptr(GByteArray) more = g_byte_array_new();
                if (qemu_plugin_read_memory_vaddr(v + len, more, deref_len - len)) {
                    g_byte_array_append(c->mem, more->data, more->len);
                    len = deref_len;
                }
            }
            slot[0] = (uint8_t)len;
            memcpy(slot + 1, c->mem->data, len);
        }
    }

    dt_record_hdr h = {
        .vaddr = ii->vaddr, .range_id = ii->range_id, .vcpu = (uint16_t)vcpu_index,
        .insn_len = ii->len, .flags = (uint8_t)(c->tb_flags | (trunc ? DT_F_REG_TRUNC : 0)),
        .asid = c->tb_asid,
    };
    memcpy(h.insn, ii->bytes, sizeof h.insn);

    g_mutex_lock(&out_lock);
    if (capped) { g_mutex_unlock(&out_lock); return; }
    written += sizeof h + n * 8 + dsz;
    if (written > max_bytes) {
        capped = true;
        fprintf(stderr, "droidtrace: size cap reached, tracing stopped\n");
        g_mutex_unlock(&out_lock);
        return;
    }
    h.seq = seq++;
    fwrite(&h, sizeof h, 1, out);
    fwrite(regs, sizeof(uint64_t), n, out);
    fwrite(c->deref_buf, 1, dsz, out);
    g_mutex_unlock(&out_lock);
}

static insn_info *intern_insn(struct qemu_plugin_insn *insn, uint32_t range_id)
{
    uint64_t va = qemu_plugin_insn_vaddr(insn);
    g_mutex_lock(&insn_cache_lock);
    insn_info *ii = g_hash_table_lookup(insn_cache, &va);
    if (!ii) {
        ii = g_new0(insn_info, 1);
        ii->vaddr = va;
        size_t len = qemu_plugin_insn_size(insn);
        ii->len = (uint8_t)MIN(len, DT_MAX_INSN_BYTES);
        qemu_plugin_insn_data(insn, ii->bytes, ii->len);
        g_hash_table_insert(insn_cache, &ii->vaddr, ii);
    }
    ii->range_id = range_id; /* same vaddr may belong to a new mapping after reload */
    g_mutex_unlock(&insn_cache_lock);
    return ii;
}


static void tb_trans(qemu_plugin_id_t id, struct qemu_plugin_tb *tb)
{
    (void)id;
    const dt_range_table *t = atomic_load(&ranges);
    if (!t || !t->n) return;
    size_t n = qemu_plugin_tb_n_insns(tb);
    bool any = false, anchor = false;
    for (size_t i = 0; i < n; i++) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i);
        uint64_t va = qemu_plugin_insn_vaddr(insn);
        if (!is_user_address(va)) continue;
        const dt_range *r = dt_ranges_find(t, va);
        if (!r) continue; /* untraced code: no callback at all */
        qemu_plugin_register_vcpu_insn_exec_cb(insn, insn_exec, QEMU_PLUGIN_CB_R_REGS,
                                               intern_insn(insn, r->id));
        any = true;
        anchor |= r->anchor;
    }
    /* TB callbacks run before the TB's instruction callbacks. */
    if (any)
        qemu_plugin_register_vcpu_tb_exec_cb(tb, tb_exec, QEMU_PLUGIN_CB_R_REGS,
                                             anchor ? (void *)1 : NULL);
}

static void after_reset(qemu_plugin_id_t id)
{
    register_callbacks(id);
    atomic_store(&reset_running, false);
}

/* Runs on a vCPU thread, where qemu_plugin_reset() can safely flush the TB cache. */
static void maybe_reset(void)
{
    if (!atomic_load(&reset_pending)) return;
    bool f = false;
    if (!atomic_compare_exchange_strong(&reset_running, &f, true)) return;
    atomic_store(&reset_pending, false);
    qemu_plugin_reset(plugin_id, after_reset);
}

static void vcpu_idle(qemu_plugin_id_t id, unsigned int vcpu_index)
{
    (void)id; (void)vcpu_index;
    maybe_reset();
}

static void vcpu_syscall(qemu_plugin_id_t id, unsigned int vcpu_index, int64_t num,
                         uint64_t a1, uint64_t a2, uint64_t a3, uint64_t a4, uint64_t a5,
                         uint64_t a6, uint64_t a7, uint64_t a8)
{
    (void)id; (void)vcpu_index; (void)num; (void)a1; (void)a2; (void)a3; (void)a4;
    (void)a5; (void)a6; (void)a7; (void)a8;
    maybe_reset();
}

static void plugin_exit(qemu_plugin_id_t id, void *p)
{
    (void)id; (void)p;
    atomic_store(&running, false);
    if (ranges_path) pthread_join(reload_thread, NULL);
    g_mutex_lock(&out_lock);
    fflush(out);
    fclose(out);
    if (libs_log) fclose(libs_log);
    g_mutex_unlock(&out_lock);
    dt_ranges_free(atomic_load(&ranges));
    for (guint i = 0; i < retired_tables->len; i++)
        dt_ranges_free(g_ptr_array_index(retired_tables, i));
    fprintf(stderr, "droidtrace: wrote %" PRIu64 " records to %s\n", seq, out_path);
}

QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id, const qemu_info_t *info,
                                           int argc, char **argv)
{
    if (info->system_emulation == false)
        fprintf(stderr, "droidtrace: user-mode emulation: ASID filtering disabled\n");

    for (int i = 0; i < argc; i++) {
        g_auto(GStrv) kv = g_strsplit(argv[i], "=", 2);
        if (!kv[0] || !kv[1]) { fprintf(stderr, "droidtrace: bad arg %s\n", argv[i]); return -1; }
        if (!g_strcmp0(kv[0], "out")) out_path = g_strdup(kv[1]);
        else if (!g_strcmp0(kv[0], "ranges")) ranges_path = g_strdup(kv[1]);
        else if (!g_strcmp0(kv[0], "regs")) regs_spec = g_strdup(kv[1]);
        else if (!g_strcmp0(kv[0], "deref")) deref_len = (unsigned)MIN(atoi(kv[1]), 255);
        else if (!g_strcmp0(kv[0], "deref_regs")) deref_spec = g_strdup(kv[1]);
        else if (!g_strcmp0(kv[0], "asid_reg")) asid_reg_name = g_strdup(kv[1]);
        else if (!g_strcmp0(kv[0], "reload_ms")) reload_ms = (unsigned)atoi(kv[1]);
        else if (!g_strcmp0(kv[0], "max_bytes")) max_bytes = g_ascii_strtoull(kv[1], NULL, 10);
        else if (!g_strcmp0(kv[0], "bufsize")) bufsize = (size_t)g_ascii_strtoull(kv[1], NULL, 10);
        else if (!g_strcmp0(kv[0], "strict")) {
            if (!qemu_plugin_bool_parse(kv[0], kv[1], &strict)) return -1;
        } else { fprintf(stderr, "droidtrace: unknown option %s\n", kv[0]); return -1; }
    }
    if (!out_path) out_path = g_strdup("trace.dtr");

    out = fopen(out_path, "wb");
    if (!out) { perror(out_path); return -1; }
    setvbuf(out, NULL, _IOFBF, bufsize);
    g_autofree char *libs_path = g_strdup_printf("%s.libs", out_path);
    libs_log = fopen(libs_path, "w");

    insn_cache = g_hash_table_new(g_int64_hash, g_int64_equal);
    retired_tables = g_ptr_array_new();
    vcpus = qemu_plugin_scoreboard_new(sizeof(vcpu_ctx));

    if (ranges_path) {
        reload_ranges();
        pthread_create(&reload_thread, NULL, reload_loop, NULL);
    } else {
        fprintf(stderr, "droidtrace: no ranges= given; tracing nothing until provided\n");
    }

    plugin_id = id;
    qemu_plugin_register_vcpu_init_cb(id, vcpu_init);
    register_callbacks(id);
    return 0;
}

static void register_callbacks(qemu_plugin_id_t id)
{
    qemu_plugin_register_vcpu_tb_trans_cb(id, tb_trans);
    qemu_plugin_register_vcpu_idle_cb(id, vcpu_idle);   /* system mode: guest goes idle */
    qemu_plugin_register_vcpu_resume_cb(id, vcpu_idle);
    qemu_plugin_register_vcpu_syscall_cb(id, vcpu_syscall); /* user mode */
    qemu_plugin_register_atexit_cb(id, plugin_exit, NULL);
}
