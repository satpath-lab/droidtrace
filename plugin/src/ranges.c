/* SPDX-License-Identifier: Apache-2.0
 * Address-range table: sorted, binary-searched, hot-reloadable.
 */
#include "ranges.h"
#include <glib.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

/* path+start -> id, so an id is stable across reloads */
static GHashTable *id_map;

static int cmp_range(const void *a, const void *b)
{
    const dt_range *x = a, *y = b;
    return (x->start > y->start) - (x->start < y->start);
}

dt_range_table *dt_ranges_load(const char *path, FILE *libs_log, uint32_t *next_id)
{
    FILE *f = fopen(path, "r");
    if (!f) return NULL;
    if (!id_map) id_map = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);

    GArray *arr = g_array_new(FALSE, FALSE, sizeof(dt_range));
    char line[4096];
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#' || line[0] == '\n') continue;
        dt_range r = {0};
        char flags[16] = {0}, lib[3000] = {0};
        if (sscanf(line, "%" SCNx64 " %" SCNx64 " %" SCNx64 " %15s %2999[^\n]",
                   &r.start, &r.end, &r.file_off, flags, lib) != 5)
            continue;
        if (r.end <= r.start) continue;
        r.anchor = strchr(flags, 'A') != NULL;

        char *key = g_strdup_printf("%" PRIx64 ":%s", r.start, lib);
        gpointer idp;
        if (g_hash_table_lookup_extended(id_map, key, NULL, &idp)) {
            r.id = GPOINTER_TO_UINT(idp);
            g_free(key);
        } else {
            r.id = (*next_id)++;
            g_hash_table_insert(id_map, key, GUINT_TO_POINTER(r.id));
            if (libs_log) {
                fprintf(libs_log, "%u %" PRIx64 " %" PRIx64 " %" PRIx64 " %s %s\n",
                        r.id, r.start, r.end, r.file_off, r.anchor ? "A" : "-", lib);
                fflush(libs_log);
            }
        }
        g_array_append_val(arr, r);
    }
    fclose(f);

    dt_range_table *t = g_new0(dt_range_table, 1);
    t->n = arr->len;
    t->v = (dt_range *)g_array_free(arr, FALSE);
    qsort(t->v, t->n, sizeof(dt_range), cmp_range);
    return t;
}

const dt_range *dt_ranges_find(const dt_range_table *t, uint64_t addr)
{
    if (!t) return NULL;
    size_t lo = 0, hi = t->n;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        const dt_range *r = &t->v[mid];
        if (addr < r->start) hi = mid;
        else if (addr >= r->end) lo = mid + 1;
        else return r;
    }
    return NULL;
}

void dt_ranges_free(dt_range_table *t)
{
    if (!t) return;
    g_free(t->v);
    g_free(t);
}
