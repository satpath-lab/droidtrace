from droidtrace.maps import parse_maps, render_ranges, select_ranges

MAPS = """\
7a00000000-7a00010000 r--p 00000000 fd:05 123  /data/app/~~x/com.evil-1/lib/arm64/libpayload.so
7a00010000-7a00020000 r-xp 00010000 fd:05 123  /data/app/~~x/com.evil-1/lib/arm64/libpayload.so
7b00000000-7b00100000 r-xp 00050000 07:10 9    /apex/com.android.runtime/lib64/bionic/libc.so
7c00000000-7c00001000 r-xp 00000000 00:00 0    [vdso]
7d00000000-7d00001000 rw-p 00000000 00:00 0
"""


def test_parse_and_select():
    entries = parse_maps(MAPS)
    assert len(entries) == 5
    sel = select_ranges(entries, ["lib*.so"], anchor_globs=["/data/app/*"])
    names = [(e.name, a) for e, a in sel]
    assert names == [("libpayload.so", True), ("libc.so", False)]
    text = render_ranges(sel)
    assert "7a00010000 7a00020000 10000 A /data/app" in text


def test_exclude():
    sel = select_ranges(parse_maps(MAPS), ["*.so"], exclude=["libc.so"])
    assert [e.name for e, _ in sel] == ["libpayload.so"]
