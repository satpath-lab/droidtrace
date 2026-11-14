from conftest import synth

from droidtrace.follow import TraceFollower


def test_follow_picks_up_appended_records(tmp_path):
    p = tmp_path / "t.dtr"
    synth.write(p, 3)
    fol = TraceFollower(p, poll=0.01)
    it = fol.batches(0, max_batch=100)
    assert [r.seq for r in next(it)] == [0, 1, 2]
    data = p.read_bytes()
    rsize = fol.trace.record_size
    with p.open("ab") as f:  # append a copy of the last record, split in two writes
        last = data[-rsize:]
        f.write(last[:10])
        f.flush()
        assert next(it) == []  # torn record not emitted yet
        f.write(last[10:])
    assert [r.seq for r in next(it)] == [2]
    assert fol.trace.lib(fol.trace and next(iter(fol.trace.records()))).name == "libnative-lib.so"


def test_follow_empty_trace_does_not_crash(tmp_path):
    """A valid header with zero records is falsy (len == 0); the follower must still work."""
    p = tmp_path / "t.dtr"
    synth.write(p, 0)
    fol = TraceFollower(p, poll=0.01)
    t = fol.wait_header()
    assert t is not None and len(t) == 0
    assert next(fol.batches(0)) == []
