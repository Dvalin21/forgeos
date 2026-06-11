"""Tests for the v2 security profile generator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators.security import (  # noqa: E402
    ALL_TOOLS,
    TIER_TOOLS,
    SecurityGenerator,
)


def _cfg(profile):
    cfg = fc.ForgeOSConfig()
    cfg.security.profile = profile
    return cfg


def test_default_profile_is_medium():
    assert fc.ForgeOSConfig().security.profile == "medium"


def test_rejects_bad_profile():
    with pytest.raises(ValueError):
        fc.SecurityConfig(profile="paranoid")


def test_tiers_are_supersets():
    assert TIER_TOOLS["low"] < TIER_TOOLS["medium"] < TIER_TOOLS["high"]


def test_low_plan_only_ufw_fail2ban():
    plan = {p.tool: p.active for p in SecurityGenerator().plan(_cfg("low"))}
    assert plan["ufw"] and plan["fail2ban"]
    assert not plan["apparmor"]
    assert not plan["aide"]
    assert not plan["crowdsec"]


def test_medium_adds_apparmor_crowdsec():
    plan = {p.tool: p.active for p in SecurityGenerator().plan(_cfg("medium"))}
    assert plan["apparmor"] and plan["crowdsec"]
    assert not plan["aide"]
    assert not plan["rkhunter"]
    assert not plan["auditd"]


def test_high_enables_everything():
    plan = {p.tool: p.active for p in SecurityGenerator().plan(_cfg("high"))}
    assert all(plan[t] for t in ALL_TOOLS)


def test_plan_covers_all_tools_at_every_tier():
    for prof in ("low", "medium", "high"):
        tools = {p.tool for p in SecurityGenerator().plan(_cfg(prof))}
        assert tools == ALL_TOOLS


def test_low_renders_sshd_jail_only():
    c = SecurityGenerator().render(_cfg("low"))[0].content
    assert "[sshd]" in c
    assert "[samba]" not in c
    assert "[forgeos-api]" not in c


def test_medium_renders_full_jail_set():
    c = SecurityGenerator().render(_cfg("medium"))[0].content
    for jail in ("[sshd]", "[nginx-http-auth]", "[forgeos-api]", "[samba]"):
        assert jail in c


def test_apply_enables_and_disables_per_tier(tmp_path, monkeypatch):
    import generators.security as sg

    calls = []

    def fake_run(self, cmd, check=True):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr(sg.SecurityGenerator, "_run", fake_run, raising=False)
    monkeypatch.setattr(sg, "_have", lambda c: True)
    gen = sg.SecurityGenerator()
    monkeypatch.setattr(
        gen, "render",
        lambda cfg: [sg.RenderedFile(path=str(tmp_path / "forgeos.conf"),
                                     content="x", mode=0o644)],
    )

    gen.apply(_cfg("low"), do_reload=False)
    joined = [" ".join(c) for c in calls]
    assert any("enable --now ufw" in j for j in joined)
    assert any("enable --now fail2ban" in j for j in joined)
    assert any("disable --now aide.timer" in j for j in joined)
    assert any("disable --now rkhunter.timer" in j for j in joined)
    assert any("disable --now auditd" in j for j in joined)
    assert any("disable --now apparmor" in j for j in joined)


def test_apply_high_enables_aide_rkhunter_timers(tmp_path, monkeypatch):
    import generators.security as sg

    calls = []

    def fake_run(self, cmd, check=True):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr(sg.SecurityGenerator, "_run", fake_run, raising=False)
    monkeypatch.setattr(sg, "_have", lambda c: True)
    gen = sg.SecurityGenerator()
    monkeypatch.setattr(
        gen, "render",
        lambda cfg: [sg.RenderedFile(path=str(tmp_path / "f.conf"), content="x")],
    )

    gen.apply(_cfg("high"), do_reload=False)
    joined = [" ".join(c) for c in calls]
    assert any("enable --now aide.timer" in j for j in joined)
    assert any("enable --now rkhunter.timer" in j for j in joined)
    assert any("enable --now auditd" in j for j in joined)
