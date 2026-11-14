from pathlib import Path

from droidtrace.config import RunConfig
from droidtrace.emulator import build_command


def test_command_is_isolated_and_tcg():
    cfg = RunConfig()
    cmd = build_command(cfg.emulator, cfg.trace, Path("t.dtr"), Path("r.txt"))
    joined = " ".join(cmd)
    assert "tcg" in joined
    assert "restrict=on" in joined and "127.0.0.1" in joined
    assert not any(c == "-plugin" for c in cmd)  # builtin engine is the default


def test_engines():
    from droidtrace.emulator import trace_env

    cfg = RunConfig()
    env = trace_env(cfg.emulator, cfg.trace, Path("t.dtr"), Path("r.txt"))
    assert env["DROIDTRACE_OUT"].endswith("t.dtr") and env["DROIDTRACE_MAX_BYTES"]
    cfg.emulator.engine = "plugin"
    cmd = build_command(cfg.emulator, cfg.trace, Path("t.dtr"), Path("r.txt"))
    assert any("libinsntrace.so" in c and "max_bytes=" in c for c in cmd)
    assert trace_env(cfg.emulator, cfg.trace, Path("t.dtr"), Path("r.txt")) == {}
    cfg.emulator.engine, cfg.emulator.arch = "builtin", "x86_64"  # builtin is aarch64-only
    assert "-plugin" in build_command(cfg.emulator, cfg.trace, Path("t"), Path("r"))
