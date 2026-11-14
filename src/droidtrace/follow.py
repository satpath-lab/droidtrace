"""Follow a .dtr trace while QEMU is still writing it (like `tail -f`)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path

from .format import FILE_HEADER
from .reader import (
    Record,
    RecordDecoder,
    Trace,
    TraceFormatError,
    _read_header,
    header_bytes_needed,
    parse_libs,
)


class TraceFollower:
    def __init__(self, path: Path, poll: float = 0.2) -> None:
        self.path, self.poll = path, poll
        self.trace: Trace | None = None
        self._libs_size = -1

    def wait_header(self, stop: Callable[[], bool] | None = None) -> Trace:
        while True:
            try:
                if self.path.exists() and self.path.stat().st_size >= FILE_HEADER.size:
                    with self.path.open("rb") as f:
                        head = f.read(FILE_HEADER.size)
                        need = header_bytes_needed(head)
                        head += f.read(need - len(head))
                    if len(head) == need:
                        self.trace = Trace(self.path, _read_header(head))
                        self.refresh_libs()
                        return self.trace
            except TraceFormatError:
                raise
            if stop and stop():
                raise TimeoutError
            time.sleep(self.poll)

    def refresh_libs(self) -> None:
        assert self.trace is not None  # (a Trace with 0 records is falsy)
        p = self.path.with_name(self.path.name + ".libs")
        size = p.stat().st_size if p.exists() else 0
        if size != self._libs_size:
            self._libs_size = size
            self.trace.libs = parse_libs(p)

    def batches(
        self, start: int = 0, max_batch: int = 2000, stop: Callable[[], bool] | None = None
    ) -> Iterator[list[Record]]:
        """Yield lists of new records starting at record index `start`; [] when idle."""
        t = self.trace if self.trace is not None else self.wait_header(stop)
        dec = RecordDecoder(t.header)
        rsize = dec.size
        off = t.header.header_size + start * rsize
        with self.path.open("rb") as f:
            while not (stop and stop()):
                f.seek(off)
                data = f.read(rsize * max_batch)
                n = len(data) // rsize
                out = [dec.decode(data, i * rsize) for i in range(n)]
                off += n * rsize
                if out:
                    self.refresh_libs()
                yield out
                if n < max_batch:
                    time.sleep(self.poll)
