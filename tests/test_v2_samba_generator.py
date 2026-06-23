"""Tests for the v2 config-DB + Samba generator PoC."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
from generators.samba import SMB_CONF, SHARES_FILE, SambaGenerator  # noqa: E402


def test_config_defaults():
    cfg = fc.ForgeOSConfig()
    assert cfg.samba.enabled is True
    assert cfg.samba.workgroup == "FORGEOS"
    assert cfg.samba.shares == []


def test_config_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg = fc.ForgeOSConfig()
    cfg.samba.shares.append(
        fc.SambaShare(name="data", path="/srv/nas/data", comment="Data")
    )
    fc.save(cfg, p)
    assert oct(p.stat().st_mode)[-3:] == "600"
    loaded = fc.load(p)
    assert len(loaded.samba.shares) == 1
    assert loaded.samba.shares[0].path == "/srv/nas/data"


def test_config_rejects_relative_path():
    with pytest.raises(ValueError):
        fc.SambaShare(name="bad", path="relative/path")


def test_config_rejects_bad_share_name():
    with pytest.raises(ValueError):
        fc.SambaShare(name="bad[name]", path="/srv/nas/x")


def test_config_rejects_duplicate_shares():
    with pytest.raises(ValueError):
        fc.SambaConfig(
            shares=[
                fc.SambaShare(name="data", path="/srv/nas/a"),
                fc.SambaShare(name="DATA", path="/srv/nas/b"),
            ]
        )


def test_load_missing_returns_defaults(tmp_path):
    cfg = fc.load(tmp_path / "does-not-exist.json")
    assert isinstance(cfg, fc.ForgeOSConfig)


def _cfg_with_shares(*shares):
    cfg = fc.ForgeOSConfig()
    cfg.samba.shares = list(shares)
    return cfg


def test_render_disabled_returns_nothing():
    cfg = fc.ForgeOSConfig()
    cfg.samba.enabled = False
    assert SambaGenerator().render(cfg) == []


def test_render_produces_two_files():
    cfg = _cfg_with_shares(fc.SambaShare(name="data", path="/srv/nas/data"))
    files = SambaGenerator().render(cfg)
    paths = {f.path for f in files}
    assert paths == {SMB_CONF, SHARES_FILE}


def test_global_includes_shares_file():
    cfg = fc.ForgeOSConfig()
    g = {f.path: f.content for f in SambaGenerator().render(cfg)}
    assert f"include = {SHARES_FILE}" in g[SMB_CONF]
    assert "workgroup = FORGEOS" in g[SMB_CONF]


def test_standard_share_has_valid_users_and_writable():
    cfg = _cfg_with_shares(
        fc.SambaShare(name="data", path="/srv/nas/data", writable=True,
                      valid_users=["@users", "keith"])
    )
    shares = {f.path: f.content for f in SambaGenerator().render(cfg)}[SHARES_FILE]
    assert "[data]" in shares
    assert "path = /srv/nas/data" in shares
    assert "valid users = @users keith" in shares
    assert "read only = no" in shares


def test_readonly_share():
    cfg = _cfg_with_shares(
        fc.SambaShare(name="ro", path="/srv/nas/ro", writable=False)
    )
    shares = {f.path: f.content for f in SambaGenerator().render(cfg)}[SHARES_FILE]
    assert "read only = yes" in shares


def test_public_ro_share_is_guest_ok():
    cfg = _cfg_with_shares(
        fc.SambaShare(name="pub", path="/srv/nas/pub", type="public-ro")
    )
    shares = {f.path: f.content for f in SambaGenerator().render(cfg)}[SHARES_FILE]
    assert "guest ok = yes" in shares
    assert "read only = yes" in shares
    block = shares.split("[pub]", 1)[1]
    assert "valid users" not in block


def test_database_share_disables_oplocks():
    cfg = _cfg_with_shares(
        fc.SambaShare(name="db", path="/srv/nas/db", type="database")
    )
    shares = {f.path: f.content for f in SambaGenerator().render(cfg)}[SHARES_FILE]
    assert "oplocks = no" in shares
    assert "level2 oplocks = no" in shares


def test_timemachine_share_has_fruit():
    cfg = _cfg_with_shares(
        fc.SambaShare(name="tm", path="/srv/nas/tm", type="timemachine")
    )
    shares = {f.path: f.content for f in SambaGenerator().render(cfg)}[SHARES_FILE]
    assert "fruit:time machine = yes" in shares
    assert "vfs objects = catia fruit streams_xattr" in shares


def test_multiple_shares_all_present():
    cfg = _cfg_with_shares(
        fc.SambaShare(name="data", path="/srv/nas/data"),
        fc.SambaShare(name="media", path="/srv/nas/media", type="public-ro"),
        fc.SambaShare(name="db", path="/srv/nas/db", type="database"),
    )
    shares = {f.path: f.content for f in SambaGenerator().render(cfg)}[SHARES_FILE]
    for name in ("[data]", "[media]", "[db]"):
        assert name in shares


def test_apply_creates_parent_dirs(tmp_path, monkeypatch):
    import generators.samba as sg

    smb = tmp_path / "etc" / "samba" / "smb.conf"
    shares = tmp_path / "etc" / "forgeos" / "samba" / "shares.conf"
    monkeypatch.setattr(sg, "SMB_CONF", str(smb))
    monkeypatch.setattr(sg, "SHARES_FILE", str(shares))

    cfg = _cfg_with_shares(fc.SambaShare(name="data", path="/srv/nas/data"))
    gen = sg.SambaGenerator()
    assert not smb.parent.exists()
    written = gen.apply(cfg, do_reload=False)

    assert smb.exists() and shares.exists()
    assert str(smb) in written


def test_apply_is_idempotent(tmp_path, monkeypatch):
    import generators.samba as sg

    smb = tmp_path / "smb.conf"
    shares = tmp_path / "shares.conf"
    monkeypatch.setattr(sg, "SMB_CONF", str(smb))
    monkeypatch.setattr(sg, "SHARES_FILE", str(shares))

    cfg = _cfg_with_shares(fc.SambaShare(name="data", path="/srv/nas/data"))
    gen = sg.SambaGenerator()
    gen.apply(cfg, do_reload=False)
    first = smb.read_text(), shares.read_text()
    gen.apply(cfg, do_reload=False)
    second = smb.read_text(), shares.read_text()
    assert first == second


# ── S1: advanced per-share options ───────────────────────────────────────────

def _render_share(**kw):
    """Render one share and return its forgeos-shares.conf text."""
    cfg = fc.ForgeOSConfig()
    cfg.samba.shares.append(fc.SambaShare(**kw))
    files = {f.path: f.content for f in SambaGenerator().render(cfg)}
    return files[SHARES_FILE]


def test_share_advanced_defaults():
    s = fc.SambaShare(name="x", path="/srv/nas/x")
    assert s.browseable is False          # NEVER default visible
    assert s.guest_ok is False
    assert s.hide_dot_files is True
    assert s.recycle_bin is False
    assert s.permissions == "group"
    assert s.force_user == "" and s.force_group == ""
    assert s.write_list == []


def test_default_share_is_not_browseable():
    conf = _render_share(name="media", path="/srv/nas/media")
    assert "browseable = no" in conf
    assert "browseable = yes" not in conf


def test_browseable_opt_in_emits_yes():
    conf = _render_share(name="media", path="/srv/nas/media", browseable=True)
    assert "browseable = yes" in conf


def test_guest_and_permissions_directives():
    conf = _render_share(name="pub", path="/srv/nas/pub", guest_ok=True,
                         permissions="public")
    assert "guest ok = yes" in conf
    assert "create mask = 0664" in conf
    assert "directory mask = 0775" in conf


def test_private_permissions_preset():
    conf = _render_share(name="priv", path="/srv/nas/priv", permissions="private")
    assert "create mask = 0600" in conf
    assert "directory mask = 0700" in conf


def test_recycle_force_and_writelist():
    conf = _render_share(name="data", path="/srv/nas/data", recycle_bin=True,
                         force_user="keith", force_group="staff",
                         writable=False, write_list=["keith"])
    assert "vfs objects = recycle" in conf
    assert "recycle:repository = .recycle/%U" in conf
    assert "force user = keith" in conf
    assert "force group = staff" in conf
    assert "read only = yes" in conf
    assert "write list = keith" in conf


def test_recycle_plus_timemachine_single_vfs_line():
    # both features must share ONE `vfs objects` line or testparm rejects it
    conf = _render_share(name="tm", path="/srv/nas/tm", type="timemachine",
                         recycle_bin=True)
    assert "vfs objects = recycle catia fruit streams_xattr" in conf
    assert conf.count("vfs objects =") == 1
    assert "fruit:time machine = yes" in conf


def test_force_principal_rejects_bad_chars():
    with pytest.raises(ValueError):
        fc.SambaShare(name="x", path="/srv/nas/x", force_user="bad user")


# ── S1b: raw custom-include editing ──────────────────────────────────────────

def test_global_includes_custom_file():
    cfg = fc.ForgeOSConfig()
    g = {f.path: f.content for f in SambaGenerator().render(cfg)}[SMB_CONF]
    assert "include = /etc/forgeos/samba/forgeos-shares-custom.conf" in g
    # both includes present, custom AFTER managed
    assert g.index("forgeos-shares.conf") < g.index("forgeos-shares-custom.conf")


def test_validate_custom_noop_without_testparm():
    # testparm isn't installed here -> validate_custom must pass for any text
    SambaGenerator().validate_custom(fc.ForgeOSConfig(), "[scratch]\n   path = /x\n")


def test_managed_validate_still_ok_with_custom_include():
    # the new second include must not break normal managed validation
    cfg = fc.ForgeOSConfig()
    cfg.samba.shares.append(fc.SambaShare(name="m", path="/srv/nas/m"))
    SambaGenerator().validate(SambaGenerator().render(cfg))
