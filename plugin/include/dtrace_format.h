/* SPDX-License-Identifier: Apache-2.0
 * DroidTrace binary trace format (.dtr). Keep in sync with src/droidtrace/format.py
 * and docs/trace-format.md. All integers little-endian.
 */
#ifndef DTRACE_FORMAT_H
#define DTRACE_FORMAT_H
#include <stdint.h>

#define DT_MAGIC          "DTRC"
#define DT_FORMAT_VERSION 2
#define DT_REG_NAME_LEN   32
#define DT_MAX_INSN_BYTES 16

enum dt_arch { DT_ARCH_UNKNOWN = 0, DT_ARCH_AARCH64 = 1, DT_ARCH_X86_64 = 2 };

enum dt_record_flags {
    DT_F_PROC_VERIFIED = 1u << 0, /* address-space id matched the target process */
    DT_F_REG_TRUNC     = 1u << 1, /* a register wider than 64 bits was truncated */
};

#pragma pack(push, 1)
typedef struct {
    char     magic[4];     /* "DTRC" */
    uint16_t version;      /* DT_FORMAT_VERSION */
    uint16_t arch;         /* enum dt_arch */
    uint32_t nregs;        /* number of uint64 register slots per record */
    uint32_t header_size;  /* total bytes incl. register name table */
    uint64_t start_unix_ns;
    uint16_t deref_n;      /* registers whose pointed-to memory is captured */
    uint16_t deref_len;    /* bytes captured per dereferenced register */
    uint32_t reserved;
    /* followed by nregs * char[DT_REG_NAME_LEN] (NUL padded),
     * then deref_n * uint16 register indices */
} dt_file_header;

typedef struct {
    uint64_t seq;          /* global execution order */
    uint64_t vaddr;        /* guest virtual address of instruction */
    uint32_t range_id;     /* id into the .libs sidecar */
    uint16_t vcpu;
    uint8_t  insn_len;
    uint8_t  flags;        /* enum dt_record_flags */
    uint64_t asid;         /* TTBR0_EL1 (aarch64) / CR3 (x86_64), 0 if unavailable */
    uint8_t  insn[DT_MAX_INSN_BYTES];
    /* followed by nregs * uint64 register values (pre-execution state),
     * then deref_n * { uint8 valid_len; uint8 bytes[deref_len]; } memory at *reg */
} dt_record_hdr;
#pragma pack(pop)

#endif
