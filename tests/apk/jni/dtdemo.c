/* Benign native test library. No libc: only JNI function-table calls, so it builds
 * without the NDK. Mimics common malware patterns (string deobfuscation, hashing). */
#include <jni.h>

static const unsigned char enc[] = { /* "http://c2.example.invalid/gate" ^ 0x5a */
    0x32,0x2e,0x2e,0x2a,0x60,0x75,0x75,0x39,0x68,0x74,0x3f,0x22,0x3b,0x37,0x2a,0x36,0x3f,
    0x74,0x33,0x34,0x2c,0x3b,0x36,0x33,0x3e,0x75,0x3d,0x3b,0x2e,0x3f};

__attribute__((noinline)) static unsigned long hash(const char *s, int key)
{
    unsigned long h = 1469598103934665603ul ^ (unsigned long)key;
    while (*s) { h ^= (unsigned char)*s++; h *= 1099511628211ul; }
    return h;
}

__attribute__((noinline)) static void deobfuscate(char *out, const unsigned char *in,
                                                  int n, unsigned char k)
{
    for (int i = 0; i < n; i++) out[i] = (char)(in[i] ^ k);
    out[n] = 0;
}

__attribute__((noinline)) static int connect_c2(const char *url) /* does nothing */
{
    int n = 0;
    while (url[n]) n++;
    return n;
}

JNIEXPORT jdouble JNICALL
Java_org_droidtrace_demo_MainActivity_check(JNIEnv *env, jclass c, jstring s, jint key,
                                            jdouble w)
{
    const char *str = (*env)->GetStringUTFChars(env, s, 0);
    unsigned long h = hash(str, key);
    (*env)->ReleaseStringUTFChars(env, s, str);
    return (double)(h & 0xffff) * w;
}

JNIEXPORT jstring JNICALL
Java_org_droidtrace_demo_MainActivity_revealUrl(JNIEnv *env, jclass c)
{
    char buf[64];
    deobfuscate(buf, enc, (int)sizeof enc, 0x5a);
    connect_c2(buf);
    return (*env)->NewStringUTF(env, buf);
}
