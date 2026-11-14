/* SPDX-License-Identifier: Apache-2.0 */
#ifndef DT_RANGES_H
#define DT_RANGES_H
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

typedef struct {
    uint64_t start, end, file_off;
    uint32_t id;
    bool     anchor;  /* range only mapped in the target process (e.g. APK's own .so) */
} dt_range;

typedef struct {
    dt_range *v;
    size_t    n;
} dt_range_table;

/* Parse "start end offset flags path" lines (hex). Assigns stable ids via libs log. */
dt_range_table *dt_ranges_load(const char *path, FILE *libs_log, uint32_t *next_id);
const dt_range *dt_ranges_find(const dt_range_table *t, uint64_t addr);
void dt_ranges_free(dt_range_table *t);
#endif
