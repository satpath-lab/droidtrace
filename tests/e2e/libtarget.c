/* Benign test library: known register values on entry. */
#include <string.h>
long secret_fn(long a, long b) { long r = a * 3 + b; return r ^ 0x5a; }
double str_fn(const char *s, double d) { return (double)strlen(s) * d; }
