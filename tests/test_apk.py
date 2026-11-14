import io
import zipfile

import pytest

from droidtrace.apk import inspect_apk


def _apk(libs: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("classes.dex", b"")
        for name, data in (libs or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def test_single_apk_abis(tmp_path):
    p = tmp_path / "a.apk"
    p.write_bytes(_apk({"lib/arm64-v8a/libx.so": b"", "lib/x86_64/libx.so": b""}))
    info = inspect_apk(p, aapt="does-not-exist")
    assert info.abis == ["arm64-v8a", "x86_64"] and info.native_libs == ["libx.so"]
    assert info.install_files(["x86_64"]) == [p]


@pytest.mark.parametrize("suffix,prefix", [(".apks", "splits/"), (".xapk", ""), (".apkm", "")])
def test_bundles_pick_matching_abi_split(tmp_path, suffix, prefix):
    bundle = tmp_path / f"app{suffix}"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr(f"{prefix}base.apk", _apk())
        z.writestr(f"{prefix}split_config.arm64_v8a.apk", _apk({"lib/arm64-v8a/libp.so": b""}))
        z.writestr(f"{prefix}split_config.x86_64.apk", _apk({"lib/x86_64/libp.so": b""}))
        z.writestr(f"{prefix}split_config.en.apk", _apk())
        z.writestr("manifest.json", b"{}")
    info = inspect_apk(bundle, aapt="does-not-exist")
    assert info.abis == ["arm64-v8a", "x86_64"] and info.native_libs == ["libp.so"]
    names = [f.name for f in info.install_files(["x86_64", "x86"])]
    assert names[0].endswith("base.apk")
    assert any(n.endswith("x86_64.apk") for n in names)
    assert not any("arm64" in n for n in names)  # wrong-CPU split left out
    assert any(n.endswith("en.apk") for n in names)  # language split kept


def test_folder_of_splits(tmp_path):
    d = tmp_path / "splits"
    d.mkdir()
    (d / "base.apk").write_bytes(_apk())
    (d / "split_config.arm64_v8a.apk").write_bytes(_apk({"lib/arm64-v8a/libq.so": b""}))
    info = inspect_apk(d, aapt="does-not-exist")
    assert info.abis == ["arm64-v8a"]
    assert [f.name for f in info.install_files(["arm64-v8a"])] == [
        "base.apk",
        "split_config.arm64_v8a.apk",
    ]
