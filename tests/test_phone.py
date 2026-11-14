import zlib

from droidtrace.phone import ppm_to_png


def test_ppm_to_png_roundtrip():
    w, h = 3, 2
    px = bytes(range(w * h * 3))
    png, pw, ph = ppm_to_png(b"P6\n# comment\n3 2\n255\n" + px)
    assert (pw, ph) == (3, 2) and png.startswith(b"\x89PNG")
    idat = png[png.index(b"IDAT") + 4 : png.index(b"IEND") - 8]
    raw = zlib.decompress(idat)
    assert raw == b"\0" + px[:9] + b"\0" + px[9:]
