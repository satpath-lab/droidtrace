"""Local live trace viewer: HTTP + Server-Sent Events, stdlib only."""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import webbrowser
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from .disasm import disassemble
from .follow import TraceFollower
from .format import Arch
from .reader import Record, Trace
from .values import interpret

if TYPE_CHECKING:
    from .phone import Phone

log = logging.getLogger(__name__)


@lru_cache(maxsize=65536)
def _dis(arch: Arch, insn: bytes, va: int) -> str:
    return disassemble(arch, insn, va)


def record_json(t: Trace, r: Record) -> dict[str, Any]:
    lib = t.lib(r)
    return {
        "seq": r.seq,
        "va": f"{r.vaddr:x}",
        "lib": lib.name if lib else "?",
        "off": f"{lib.lib_offset(r.vaddr):x}" if lib else "",
        "insn": _dis(t.header.arch, r.insn, r.vaddr),
        "v": bool(r.flags & 1),
        "r": [
            interpret(t, n, v, r.mem.get(i))
            for i, (n, v) in enumerate(zip(t.header.reg_names, r.regs, strict=True))
        ],
    }


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/":
            html = files("droidtrace").joinpath("static/viewer.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif u.path == "/api/screen":
            phone = self.server.phone
            png = phone.screenshot() if phone else None
            if png is None:
                self._send(404, b"no phone screen in this session", "text/plain")
            else:
                self._send(200, png, "image/png")
        elif u.path == "/api/status":
            self._send(200, json.dumps(self.server.status()).encode(), "application/json")
        elif u.path == "/api/stream":
            q = parse_qs(u.query)
            self._stream(int(q.get("from", ["0"])[0]), once=q.get("once", ["0"])[0] == "1")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        phone = self.server.phone
        if phone is None or urlparse(self.path).path != "/api/input":
            self._send(404, b"not found", "text/plain")
            return
        # Only accept same-origin requests from the viewer page (blocks drive-by websites).
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self._send(403, b"forbidden", "text/plain")
            return
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 4096)
            req = json.loads(self.rfile.read(n) or b"{}")
            kind = req.get("type")
            if kind == "tap":
                phone.tap(int(req["x"]), int(req["y"]))
            elif kind == "swipe":
                phone.swipe(int(req["x1"]), int(req["y1"]), int(req["x2"]), int(req["y2"]))
            elif kind == "key":
                phone.key(str(req["key"]))
            elif kind == "text":
                phone.text(str(req["text"])[:500])
            else:
                raise ValueError(kind)
        except (ValueError, KeyError, TypeError):
            self._send(400, b"bad request", "text/plain")
            return
        self._send(200, b"{}", "application/json")

    def _stream(self, start: int, once: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        fol = TraceFollower(self.server.trace_path)
        stop = self.server.stopping.is_set
        try:
            t = fol.wait_header(stop)
            meta = {"regs": t.header.reg_names, "arch": t.header.arch.name}
            self.wfile.write(f"event: meta\ndata: {json.dumps(meta)}\n\n".encode())
            self.wfile.flush()
            for batch in fol.batches(start, 2000, stop):
                if batch:
                    rows = [record_json(t, r) for r in batch]
                    self.wfile.write(f"data: {json.dumps(rows)}\n\n".encode())
                elif once:  # snapshot mode: send what exists, then end the stream
                    self.wfile.write(b"event: end\ndata: {}\n\n")
                    self.wfile.flush()
                    return
                else:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], trace_path: Path) -> None:
        super().__init__(addr, _Handler)
        self.phone: Phone | None = None
        self.trace_path = trace_path
        self.stopping = threading.Event()
        self.state = "waiting for trace"

    def status(self) -> dict[str, Any]:
        p = self.trace_path
        return {
            "state": self.state,
            "trace": str(p),
            "phone": self.phone is not None,
            "bytes": p.stat().st_size if p.exists() else 0,
        }


class LiveViewer:
    """Serve a live view of `trace_path` on http://127.0.0.1:<port>/ (localhost only)."""

    def __init__(self, trace_path: Path, port: int = 8765, host: str = "127.0.0.1") -> None:
        self.server = _Server((host, port), trace_path)
        self.url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/"
        self._t = threading.Thread(target=self.server.serve_forever, daemon=True)

    def attach_phone(self, phone: Phone) -> None:
        """Show the phone's screen in the viewer and let clicks control it."""
        self.server.phone = phone

    def set_state(self, s: str) -> None:
        self.server.state = s

    def start(self, open_browser: bool = True) -> None:
        self._t.start()
        if open_browser:
            with contextlib.suppress(Exception):  # headless / container
                webbrowser.open(self.url)

    def stop(self) -> None:
        self.server.stopping.set()
        self.server.shutdown()
