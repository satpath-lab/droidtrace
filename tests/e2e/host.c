/* 1. calls the library BEFORE tracing is enabled (code gets translated uninstrumented),
 * 2. writes a ranges file from /proc/self/maps and waits for the plugin's reload + TB flush,
 * 3. calls again: must now be traced, including a string argument,
 * 4. runs an untraced hot loop to measure overhead on code outside the ranges. */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    void *h = dlopen(argv[1], RTLD_NOW);
    if (!h) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    long (*fn)(long, long) = (long (*)(long, long))dlsym(h, "secret_fn");
    double (*sfn)(const char *, double) = (double (*)(const char *, double))dlsym(h, "str_fn");
    printf("pre-trace=%ld\n", fn(1, 2)); /* translated before ranges exist */
    if (argc > 3) {
        FILE *m = fopen("/proc/self/maps", "r"), *o = fopen(argv[3], "w");
        char line[1024];
        while (fgets(line, sizeof line, m)) {
            unsigned long s, e, off; char perms[8], path[512] = "";
            if (sscanf(line, "%lx-%lx %7s %lx %*s %*s %511[^\n]", &s, &e, perms, &off, path) >= 4
                && strchr(perms, 'x') && strstr(path, "libtarget.so"))
                fprintf(o, "%lx %lx %lx A %s\n", s, e, off, path);
        }
        fclose(o); fclose(m);
        rename(argv[3], argv[2]);
        usleep(500000); /* > reload_ms; syscalls let a vCPU thread run the reset */
        usleep(1000);
    }
    printf("result=%ld\n", fn(0x1111, 0x2222));
    printf("str=%f\n", sfn("http://c2.example.invalid/gate", 2.5));
    volatile unsigned long acc = 0;
    long iters = argc > 4 ? atol(argv[4]) : 0;
    for (long i = 0; i < iters; i++) acc += i ^ (acc >> 3);
    printf("loop=%lu\n", (unsigned long)acc);
    return 0;
}
