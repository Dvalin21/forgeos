"""Tests for the app-store CONVERGE layer — reconcile Docker -> config DB.

Injected fake `run` (no Docker), real temp filesystem for the compose-exists
branch. Proves: correct per-app action, idempotency (act only on a delta),
fail-loud on unknown state, and that converge only ever drives compose projects
it can name from cfg.apps (an unmanaged container is structurally untouchable).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
import forgeos_appinstall as ai  # noqa: E402
import forgeos_appstore_exec as ex  # noqa: E402


# ── fakes ─────────────────────────────────────────────────────────────────


class _R:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRun:
    """Records commands. `ps` results and up/stop results are canned per app
    (keyed by the value after `-p`)."""

    def __init__(self, ps=None, actions=None):
        self.ps = ps or {}          # app_id -> (returncode, stdout)
        self.actions = actions or {}  # app_id -> returncode for up/stop
        self.calls = []

    def __call__(self, cmd, cwd=None):
        self.calls.append(cmd)
        app_id = cmd[cmd.index("-p") + 1] if "-p" in cmd else None
        if "ps" in cmd:
            rc, out = self.ps.get(app_id, (0, ""))  # default: empty -> down
            return _R(rc, out)
        rc = self.actions.get(app_id, 0)
        return _R(rc, "", "boom" if rc else "")

    def issued(self, verb):
        """Commands that issued a given compose verb (up/stop/ps)."""
        return [c for c in self.calls if verb in c]


RUNNING = '[{"Service":"app","State":"running","Status":"Up 3 minutes"}]'
EXITED = '[{"Service":"app","State":"exited","Status":"Exited (0)"}]'


def _mk_compose(root: Path, *app_ids):
    """Create a stub compose file on disk for each app id."""
    for aid in app_ids:
        d = root / aid
        d.mkdir(parents=True, exist_ok=True)
        (d / "docker-compose.yml").write_text("name: %s\nservices: {}\n" % aid)


def _store(run):
    store = ex.AppStore()
    store.run = run
    return store


def _cfg(*apps):
    return fc.ForgeOSConfig(apps=list(apps))


def _app(aid, *, port, enabled=True):
    return fc.InstalledApp(id=aid, webui_port=port, enabled=enabled)


# ── pure decision table ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "enabled,running,exists,expected",
    [
        (True, True, True, "noop"),    # enabled + up        -> nothing
        (True, False, True, "up"),     # enabled + down      -> start
        (True, False, False, "error"), # enabled + no compose-> can't start
        (False, True, True, "stop"),   # disabled + up       -> stop
        (False, False, True, "noop"),  # disabled + down     -> nothing
        (False, False, False, "noop"), # disabled + no compose-> already gone
        (True, True, False, "error"),  # exists=False dominates for enabled
    ],
)
def test_decide_app_action_truth_table(enabled, running, exists, expected):
    assert ai.decide_app_action(
        enabled=enabled, running=running, compose_exists=exists
    ) == expected


# ── _any_running parser ─────────────────────────────────────────────────────


def test_any_running_empty_is_down():
    assert ex._any_running("") is False
    assert ex._any_running("   \n  ") is False


def test_any_running_json_array():
    assert ex._any_running(RUNNING) is True
    assert ex._any_running(EXITED) is False


def test_any_running_ndjson_lines():
    nd = '{"Service":"a","State":"exited"}\n{"Service":"b","State":"running"}'
    assert ex._any_running(nd) is True


def test_any_running_unparseable_is_unknown():
    assert ex._any_running("not json at all") is None
    assert ex._any_running('{"broken": ') is None


# ── converge: per-app actions ───────────────────────────────────────────────


def test_enabled_already_running_is_noop(tmp_path):
    _mk_compose(tmp_path, "grafana")
    run = FakeRun(ps={"grafana": (0, RUNNING)})
    res = _store(run).converge(_cfg(_app("grafana", port=3001)), apps_root=str(tmp_path))

    assert res.ok
    assert res.changed == []
    assert res.states[0].action == "noop"
    assert run.issued("up") == [] and run.issued("stop") == []


def test_enabled_but_down_gets_started(tmp_path):
    _mk_compose(tmp_path, "grafana")
    run = FakeRun(ps={"grafana": (0, EXITED)})
    res = _store(run).converge(_cfg(_app("grafana", port=3001)), apps_root=str(tmp_path))

    assert res.ok
    assert res.changed == ["grafana"]
    assert res.states[0].action == "up"
    up = run.issued("up")
    assert len(up) == 1
    assert up[0] == ["docker", "compose", "-p", "grafana",
                     "-f", f"{tmp_path}/grafana/docker-compose.yml", "up", "-d"]


def test_disabled_but_running_gets_stopped(tmp_path):
    _mk_compose(tmp_path, "grafana")
    run = FakeRun(ps={"grafana": (0, RUNNING)})
    res = _store(run).converge(
        _cfg(_app("grafana", port=3001, enabled=False)), apps_root=str(tmp_path)
    )

    assert res.ok
    assert res.changed == ["grafana"]
    assert res.states[0].action == "stop"
    assert len(run.issued("stop")) == 1
    assert run.issued("up") == []


def test_disabled_and_down_is_noop(tmp_path):
    _mk_compose(tmp_path, "grafana")
    run = FakeRun(ps={"grafana": (0, EXITED)})
    res = _store(run).converge(
        _cfg(_app("grafana", port=3001, enabled=False)), apps_root=str(tmp_path)
    )
    assert res.ok and res.changed == []
    assert res.states[0].action == "noop"


def test_enabled_missing_compose_is_error_no_command(tmp_path):
    # no compose file written for this app
    run = FakeRun()
    res = _store(run).converge(_cfg(_app("ghost", port=3001)), apps_root=str(tmp_path))

    assert not res.ok
    assert res.errors == ["ghost"]
    assert res.states[0].action == "error"
    assert res.states[0].actual == "absent"
    # never tried to talk to docker about a project it can't materialize
    assert run.calls == []


def test_disabled_missing_compose_is_silent_noop(tmp_path):
    run = FakeRun()
    res = _store(run).converge(
        _cfg(_app("ghost", port=3001, enabled=False)), apps_root=str(tmp_path)
    )
    assert res.ok and res.changed == []
    assert res.states[0].action == "noop"
    assert run.calls == []


# ── converge: fail loud, never guess ────────────────────────────────────────


def test_probe_failure_is_error_no_action(tmp_path):
    # docker unreachable: `compose ps` returns non-zero -> state unknown.
    _mk_compose(tmp_path, "grafana")
    run = FakeRun(ps={"grafana": (1, "")})
    res = _store(run).converge(_cfg(_app("grafana", port=3001)), apps_root=str(tmp_path))

    assert not res.ok
    assert res.errors == ["grafana"]
    assert res.states[0].action == "error"
    assert res.states[0].actual == "unknown"
    # must NOT have attempted up/stop on unknown state
    assert run.issued("up") == [] and run.issued("stop") == []


def test_unparseable_ps_is_error(tmp_path):
    _mk_compose(tmp_path, "grafana")
    run = FakeRun(ps={"grafana": (0, "garbage not json")})
    res = _store(run).converge(_cfg(_app("grafana", port=3001)), apps_root=str(tmp_path))
    assert not res.ok
    assert res.states[0].action == "error"


def test_compose_up_failure_recorded(tmp_path):
    _mk_compose(tmp_path, "grafana")
    run = FakeRun(ps={"grafana": (0, EXITED)}, actions={"grafana": 1})
    res = _store(run).converge(_cfg(_app("grafana", port=3001)), apps_root=str(tmp_path))

    assert not res.ok
    assert res.errors == ["grafana"]
    assert res.states[0].action == "error"
    assert "compose up failed" in res.states[0].detail


# ── converge: whole-set behavior ────────────────────────────────────────────


def test_mixed_set_one_up_one_stop_one_noop(tmp_path):
    _mk_compose(tmp_path, "grafana", "prom", "gotify")
    run = FakeRun(ps={
        "grafana": (0, EXITED),    # enabled, down  -> up
        "prom": (0, RUNNING),      # disabled, up   -> stop
        "gotify": (0, RUNNING),    # enabled, up    -> noop
    })
    cfg = _cfg(
        _app("grafana", port=3001),
        _app("prom", port=3002, enabled=False),
        _app("gotify", port=3003),
    )
    res = _store(run).converge(cfg, apps_root=str(tmp_path))

    assert res.ok
    assert set(res.changed) == {"grafana", "prom"}
    actions = {s.app_id: s.action for s in res.states}
    assert actions == {"grafana": "up", "prom": "stop", "gotify": "noop"}


def test_one_error_does_not_block_the_rest(tmp_path):
    _mk_compose(tmp_path, "good")  # 'bad' has no compose
    run = FakeRun(ps={"good": (0, EXITED)})
    cfg = _cfg(_app("bad", port=3001), _app("good", port=3002))
    res = _store(run).converge(cfg, apps_root=str(tmp_path))

    assert not res.ok
    assert res.errors == ["bad"]
    assert "good" in res.changed                 # good still got started
    assert len(run.issued("up")) == 1


def test_idempotent_second_pass_is_noop(tmp_path):
    """First pass starts a down app; if it's now running, a second pass with
    the same config issues nothing."""
    _mk_compose(tmp_path, "grafana")
    store = _store(FakeRun(ps={"grafana": (0, EXITED)}))
    cfg = _cfg(_app("grafana", port=3001))
    r1 = store.converge(cfg, apps_root=str(tmp_path))
    assert r1.changed == ["grafana"]

    # second pass: app now reports running -> nothing to do
    store2 = _store(FakeRun(ps={"grafana": (0, RUNNING)}))
    r2 = store2.converge(cfg, apps_root=str(tmp_path))
    assert r2.changed == []
    assert r2.states[0].action == "noop"


# ── converge: safety boundary ───────────────────────────────────────────────


def test_only_drives_named_compose_projects(tmp_path):
    """Every command converge issues is a `docker compose -p <id> -f <path>`
    against a project named from cfg.apps. It NEVER issues a bare
    `docker stop/rm`, so a container started outside the app-store (e.g. via
    /api/docker/run, not in cfg.apps) is untouchable here."""
    _mk_compose(tmp_path, "grafana", "prom")
    run = FakeRun(ps={"grafana": (0, EXITED), "prom": (0, RUNNING)})
    cfg = _cfg(_app("grafana", port=3001), _app("prom", port=3002, enabled=False))
    _store(run).converge(cfg, apps_root=str(tmp_path))

    managed_ids = {"grafana", "prom"}
    for cmd in run.calls:
        assert cmd[:3] == ["docker", "compose", "-p"]
        assert cmd[3] in managed_ids
        assert cmd[5].endswith("/docker-compose.yml")
        # no destructive bare-docker verbs ever
        assert "rm" not in cmd
        assert not (cmd[0] == "docker" and cmd[1] in ("stop", "rm", "kill"))
