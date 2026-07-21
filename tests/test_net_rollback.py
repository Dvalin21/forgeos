"""Rollback engine — the safety-critical apply→confirm→auto-revert core.
Tested entirely with in-memory fakes: NO real network commands. Uses a short
window so the auto-revert path runs fast."""
import time
import threading
import pytest
from net_rollback import RollbackEngine, RollbackError


class Fake:
    """In-memory stand-in for the real config: snapshot/apply/revert record
    what the engine does so tests can assert the exact sequence."""
    def __init__(self):
        self.state = "ORIGINAL"
        self.events = []
        self.apply_should_fail = False

    def snapshot(self):
        self.events.append(("snapshot", self.state))
        return self.state                     # opaque handle = the prior state

    def apply(self, new):
        if self.apply_should_fail:
            self.events.append(("apply-FAIL", new))
            raise RuntimeError("simulated apply failure")
        self.events.append(("apply", new))
        self.state = new

    def revert(self, snap):
        self.events.append(("revert", snap))
        self.state = snap


def test_confirm_commits_change():
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=5)
    r = eng.apply("NEW", "ens18 -> static")
    assert f.state == "NEW"                    # applied
    assert eng.status()["pending"] is True
    eng.confirm(r["token"])
    assert f.state == "NEW"                     # committed, stays NEW
    assert eng.status()["pending"] is False
    assert eng.status()["last_result"] == "committed"
    # no revert ever happened
    assert not any(e[0] == "revert" for e in f.events)


def test_timeout_auto_reverts():
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=1)
    eng.apply("BAD", "ens18 -> broken")
    assert f.state == "BAD"
    # DON'T confirm — wait for the timer to fire
    time.sleep(1.4)
    assert f.state == "ORIGINAL"               # auto-reverted to snapshot
    assert eng.status()["pending"] is False
    assert eng.status()["last_result"] == "reverted"


def test_confirm_before_timeout_prevents_revert():
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=1)
    r = eng.apply("NEW", "x")
    eng.confirm(r["token"])
    time.sleep(1.4)                            # wait past when the timer WOULD fire
    assert f.state == "NEW"                     # still committed, timer was cancelled
    assert eng.status()["last_result"] == "committed"


def test_only_one_pending_at_a_time():
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=5)
    eng.apply("A", "first")
    with pytest.raises(RollbackError):
        eng.apply("B", "second")               # rejected while one is armed


def test_invalid_token_rejected_and_change_stays_pending():
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=5)
    eng.apply("NEW", "x")
    with pytest.raises(RollbackError):
        eng.confirm("wrong-token")
    assert eng.status()["pending"] is True     # still armed, not committed
    eng.cancel()                               # clean up


def test_confirm_with_no_pending_raises():
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert)
    with pytest.raises(RollbackError):
        eng.confirm("anything")


def test_manual_cancel_reverts_now():
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=30)
    eng.apply("NEW", "x")
    assert f.state == "NEW"
    eng.cancel()
    assert f.state == "ORIGINAL"               # immediate revert
    assert eng.status()["last_result"] == "reverted"


def test_apply_failure_restores_and_stays_idle():
    f = Fake()
    f.apply_should_fail = True
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=5)
    with pytest.raises(RollbackError):
        eng.apply("NEW", "x")
    assert eng.status()["pending"] is False    # no dangling armed timer
    assert f.state == "ORIGINAL"               # restored
    # a subsequent good apply still works (engine not wedged)
    f.apply_should_fail = False
    r = eng.apply("GOOD", "y")
    assert f.state == "GOOD"
    eng.confirm(r["token"])


def test_seconds_remaining_counts_down():
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=10)
    eng.apply("NEW", "x")
    rem = eng.status()["seconds_remaining"]
    assert 8 <= rem <= 10
    eng.cancel()


def test_stale_timeout_after_confirm_is_noop():
    """Race: confirm happens, then the (cancelled) timer's callback still fires
    with the old token — must be ignored, not revert a committed change."""
    f = Fake()
    eng = RollbackEngine(f.snapshot, f.apply, f.revert, window_seconds=5)
    r = eng.apply("NEW", "x")
    tok = r["token"]
    eng.confirm(tok)
    # simulate the stale timer firing after confirm
    eng._on_timeout(tok)
    assert f.state == "NEW"                     # NOT reverted
    assert eng.status()["last_result"] == "committed"
