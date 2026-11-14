from droidtrace.adb import AdbClient


class FakeAdb(AdbClient):
    """Simulates a device that is briefly offline after each connect, then boots."""

    def __init__(self, states):
        super().__init__("127.0.0.1:15555")
        self.states, self.kills, self.connects = list(states), 0, 0

    def _run(self, *args, check=True, timeout=None):
        if args == ("devices",):
            st = self.states.pop(0) if self.states else "device"
            return f"List of devices attached\n{self.serial}\t{st}\n" if st else ""
        if args[:1] == ("shell",):
            return "1\n"
        return ""

    def connect(self):
        self.connects += 1


def test_brief_offline_does_not_kill_server(monkeypatch):
    import droidtrace.adb as m

    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: calls.append(a))
    a = FakeAdb(["", "offline", "offline", "device"])
    a.wait_for_boot(timeout=60)
    assert calls == []  # no kill-server for a short handshake
    assert a.connects == 1


def test_stuck_offline_restarts_server(monkeypatch):
    import droidtrace.adb as m

    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    FakeAdb(["offline"] * 7 + ["device"]).wait_for_boot(timeout=60)
    assert any("kill-server" in c for c in calls)
