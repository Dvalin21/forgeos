"""Tests for the service health watcher — transition-based alerting."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_health as fh  # noqa: E402


SVCS = {"smbd": "Samba", "nginx": "nginx"}


def test_first_run_establishes_baseline_no_alerts():
    t = fh.diff_states(SVCS, {}, {"smbd": True, "nginx": False})
    assert t == []


def test_detects_down_transition():
    prev = {"smbd": True, "nginx": True}
    cur = {"smbd": True, "nginx": False}
    t = fh.diff_states(SVCS, prev, cur)
    assert len(t) == 1
    assert t[0].unit == "nginx" and t[0].kind == "down"


def test_detects_up_transition():
    prev = {"smbd": False, "nginx": True}
    cur = {"smbd": True, "nginx": True}
    t = fh.diff_states(SVCS, prev, cur)
    assert len(t) == 1
    assert t[0].unit == "smbd" and t[0].kind == "up"


def test_no_transition_when_unchanged():
    state = {"smbd": True, "nginx": False}
    assert fh.diff_states(SVCS, state, state) == []


def test_persistent_down_does_not_repeat():
    prev = {"smbd": True, "nginx": True}
    down = {"smbd": True, "nginx": False}
    first = fh.diff_states(SVCS, prev, down)
    assert len(first) == 1
    second = fh.diff_states(SVCS, down, down)
    assert second == []


def test_watcher_tick_calls_notify_on_down():
    seq = iter([
        {"smbd": True, "nginx": True},
        {"smbd": True, "nginx": False},
    ])
    state = {}

    def probe(unit):
        return state[unit]

    w = fh.HealthWatcher(services=SVCS, probe=probe)
    calls = []

    state.update(next(seq))
    assert w.tick(lambda s, b: calls.append(s)) == []
    assert calls == []

    state.update(next(seq))
    transitions = w.tick(lambda s, b: calls.append(s))
    assert len(transitions) == 1
    assert any("nginx" in c and "DOWN" in c for c in calls)


def test_watcher_recovery_notice():
    state = {"smbd": True}
    w = fh.HealthWatcher(services={"smbd": "Samba"}, probe=lambda u: state[u])
    msgs = []
    w.tick(lambda s, b: msgs.append(s))
    state["smbd"] = False
    w.tick(lambda s, b: msgs.append(s))
    state["smbd"] = True
    w.tick(lambda s, b: msgs.append(s))
    assert any("DOWN" in m for m in msgs)
    assert any("recovered" in m for m in msgs)


def test_default_services_excludes_mail():
    assert not any("postfix" in u or "dovecot" in u for u in fh.DEFAULT_SERVICES)
