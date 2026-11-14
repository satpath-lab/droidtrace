"""Command-line interface."""

from __future__ import annotations

import collections
import logging
import time
from pathlib import Path

import click

from . import __version__
from .config import RunConfig
from .exporters import export as do_export
from .reader import open_trace


@click.group()
@click.version_option(__version__)
@click.option("-v", "--verbose", count=True)
def main(verbose: int) -> None:
    """DroidTrace: instruction-level APK tracing under QEMU.

    \b
    Quick start:
      droidtrace doctor            check everything is installed
      droidtrace run app.apk       run an APK and watch the trace live
    """
    logging.basicConfig(
        level=logging.WARNING - 10 * min(verbose, 2),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@main.command()
@click.argument("apk", type=click.Path(exists=True, path_type=Path))
@click.option("--config", type=click.Path(exists=True, path_type=Path), help="YAML run config")
@click.option("--out", type=click.Path(path_type=Path), help="Output dir")
@click.option("--duration", type=float, help="Seconds to run the app (default 120)")
@click.option("--libs", help="Comma-separated library globs to trace, e.g. 'libnative*.so,libc.so'")
@click.option("--package", help="Package name (if aapt is not installed)")
@click.option(
    "--engine",
    type=click.Choice(["builtin", "plugin"]),
    help="Tracer: built into patched QEMU (fast, default) or TCG plugin",
)
@click.option(
    "--attach",
    metavar="SERIAL",
    help="Trace on an Android device already running on the patched QEMU (see docs/arm64.md)",
)
@click.option("--max-size", "max_size", type=int, help="Max trace size in MB (default 2048)")
@click.option(
    "--internet",
    is_flag=True,
    help="Let the phone reach the internet (off by default: malware could do real harm)",
)
@click.option(
    "--screen/--no-screen",
    default=True,
    show_default=True,
    help="Show the phone screen in the viewer and let you click on it",
)
@click.option("--live/--no-live", default=True, show_default=True, help="Live web viewer")
@click.option("--port", default=8765, show_default=True)
@click.option("--host", default="127.0.0.1", hidden=True)
@click.option("--no-browser", is_flag=True, help="Don't open the browser automatically")
def run(
    apk: Path,
    config: Path | None,
    out: Path | None,
    duration: float | None,
    libs: str | None,
    package: str | None,
    engine: str | None,
    attach: str | None,
    max_size: int | None,
    internet: bool,
    screen: bool,
    live: bool,
    port: int,
    host: str,
    no_browser: bool,
) -> None:
    """Run an app and record (and show live) its instruction trace.

    APP can be an .apk, a split app (.apks, .xapk, .apkm) or a folder of split APKs.
    """
    from .doctor import checks
    from .runner import run as do_run

    cfg = RunConfig.load(config)
    if duration:
        cfg.duration = duration
    if libs:
        cfg.trace.libraries = [x.strip() for x in libs.split(",") if x.strip()]
    if package:
        cfg.package = package
    if engine:
        cfg.emulator.engine = engine  # type: ignore[assignment]
    if attach:
        cfg.attach = attach
    if internet:
        cfg.emulator.network = "internet"
        click.secho(
            "⚠ Internet is ON: the app can contact real servers. "
            "Only do this on an isolated analysis machine.",
            fg="yellow",
            err=True,
        )
    if max_size:
        cfg.trace.max_bytes = max_size * 1_000_000
    needed = {"adb"} if cfg.attach else None  # attached device: only adb is required here
    bad = [
        c
        for c in checks(cfg)
        if not c[1] and not c[0].startswith("aapt") and (needed is None or c[0] in needed)
    ]
    if bad:
        for name, _, msg in bad:
            click.secho(f"✗ {name}: {msg}", fg="red", err=True)
        raise click.ClickException("environment not ready — run `droidtrace doctor`")

    out = out or Path("runs") / f"{apk.stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    viewer = None
    if live:
        from .live import LiveViewer

        viewer = LiveViewer(out / "trace.dtr", port, host)
        viewer.start(open_browser=not no_browser)
        click.secho(f"Live trace: {viewer.url}", fg="green", bold=True)

    def status(s: str) -> None:
        click.echo(f"[droidtrace] {s}")
        if viewer:
            viewer.set_state(s)

    try:
        on_phone = viewer.attach_phone if (viewer and screen) else None
        trace = do_run(cfg, apk, out, status, on_phone)
    except KeyboardInterrupt:
        click.echo("interrupted")
        trace = out / "trace.dtr"
    click.secho(f"Trace saved: {trace}", fg="green")
    click.echo(f"Export:  droidtrace export {trace} -o {out / 'trace.jsonl'}")
    if viewer:
        click.echo("Viewer still running — press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            viewer.stop()


@main.command()
@click.option("--config", type=click.Path(exists=True, path_type=Path), help="YAML run config")
def prepare(config: Path | None) -> None:
    """Boot Android once and save it, so every `run` starts in seconds."""
    from .runner import prepare as do_prepare

    do_prepare(
        RunConfig.load(config), Path("runs") / "prepare", lambda s: click.echo(f"[droidtrace] {s}")
    )


@main.command("attach-env")
@click.option("--out", required=True, type=click.Path(path_type=Path), help="Run folder")
def attach_env(out: Path) -> None:
    """Print the environment to start your own patched QEMU with, for `run --attach`."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "ranges.txt").touch()
    click.echo(f"export DROIDTRACE_OUT={(out / 'trace.dtr').resolve()}")
    click.echo(f"export DROIDTRACE_RANGES={(out / 'ranges.txt').resolve()}")


@main.command()
@click.argument("trace", type=click.Path(path_type=Path))
@click.option("--port", default=8765, show_default=True)
@click.option("--no-browser", is_flag=True)
@click.option("--host", default="127.0.0.1", hidden=True)
def view(trace: Path, port: int, no_browser: bool, host: str) -> None:
    """Open the live viewer on an existing (or still-growing) trace file."""
    from .live import LiveViewer

    v = LiveViewer(trace, port, host)
    v.set_state("viewing file")
    v.start(open_browser=not no_browser)
    click.secho(f"Viewer: {v.url}  (Ctrl+C to stop)", fg="green")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        v.stop()


@main.command()
@click.option("--config", type=click.Path(exists=True, path_type=Path))
def doctor(config: Path | None) -> None:
    """Check that QEMU, the plugin, adb and the Android image are ready."""
    from .doctor import checks

    ok = True
    for name, good, msg in checks(RunConfig.load(config)):
        click.secho(f"{'✓' if good else '✗'} {name:<22} {msg}", fg="green" if good else "red")
        ok &= good or name.startswith("aapt")
    if not ok:
        click.echo("\nSee docs/operations.md, or `droidtrace setup --image DIR`.")
        raise SystemExit(1)


@main.command()
@click.option(
    "--image",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Directory with kernel, system.qcow2, userdata.qcow2",
)
def setup(image: Path) -> None:
    """Import an Android guest image into ~/.droidtrace."""
    from .doctor import import_image

    copied = import_image(image)
    click.echo(f"imported: {', '.join(copied) or 'nothing'}")


@main.command()
@click.argument("trace", type=click.Path(exists=True, path_type=Path))
def info(trace: Path) -> None:
    """Summarise a trace file."""
    t = open_trace(trace)
    click.echo(f"arch: {t.header.arch.name}  version: {t.header.version}")
    click.echo(f"registers ({len(t.header.reg_names)}): {', '.join(t.header.reg_names)}")
    click.echo(f"records: {len(t)}  libraries: {len(t.libs)}")
    counts: collections.Counter[str] = collections.Counter()
    for r in t.records():
        lib = t.lib(r)
        counts[lib.name if lib else "?"] += 1
    for name, c in counts.most_common(20):
        click.echo(f"  {c:>12}  {name}")


@main.command()
@click.argument("trace", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["jsonl", "csv", "parquet"]), default="jsonl")
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path))
@click.option("--lib", "lib_glob", help="Only export instructions from libraries matching glob")
@click.option("--no-disasm", is_flag=True)
def export(trace: Path, fmt: str, output: Path, lib_glob: str | None, no_disasm: bool) -> None:
    """Export a trace to jsonl / csv / parquet."""
    n = do_export(open_trace(trace), fmt, output, lib_glob, not no_disasm)
    click.echo(f"exported {n} records to {output}")


if __name__ == "__main__":
    main()
