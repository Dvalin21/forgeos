"""NFS API surface.

NFS had a config model and a generator and NO endpoint - it could not be
configured or enabled through ForgeOS at all. These tests cover the routes
that now exist, with the save+generate step injected so nothing here writes
/etc or shells out to `exportfs`.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def dirs(tmp_path):
    """Factory for REAL directories.

    The API rejects an export whose folder is missing, because exportfs
    silently drops those and the save would appear to succeed. Tests must
    therefore use paths that really exist.
    """

    def make(name):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    return make


@pytest.fixture
def cfgfile(tmp_path, monkeypatch):
    import forgeos_config as fc
    path = tmp_path / "config.json"
    fc.save(fc.ForgeOSConfig(), path)
    monkeypatch.setattr(fc, "CONFIG_PATH", path)
    return path


@pytest.fixture
def applied(tmp_path, monkeypatch):
    """Intercept the save+generate step so nothing here writes /etc or shells
    out to `exportfs`.

    It still SAVES, because that is what the real _apply_nfs does — a fake
    that skipped the save would make every second call see stale config and
    quietly pass tests the product would fail (duplicate detection, delete
    by index)."""
    import forgeos_config as fc
    import nfs_api
    seen = []

    def fake(cfg):
        seen.append([(e.path, e.type) for e in cfg.nfs.exports])
        fc.save(cfg)

    monkeypatch.setattr(nfs_api, "_apply", fake)
    yield seen
    nfs_api.set_apply(None)


class TestRead:
    def test_defaults_when_nothing_configured(self, test_client, auth_headers,
                                              cfgfile, applied):
        r = test_client.get("/api/nfs", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["enabled"] is False
        assert d["exports"] == []
        assert d["nas_root"] == "/srv"

    def test_requires_auth(self, test_client, cfgfile, applied):
        assert test_client.get("/api/nfs").status_code in (401, 403)


class TestAdd:
    def test_adds_an_export(self, test_client, auth_headers, cfgfile, applied,
                            dirs):
        p = dirs("tank/media")
        r = test_client.post("/api/nfs", headers=auth_headers,
                             json={"path": p, "type": "ro"})
        assert r.status_code == 200
        d = r.json()
        assert len(d["exports"]) == 1
        assert d["exports"][0]["path"] == p
        assert d["exports"][0]["type"] == "ro"
        assert applied == [[(p, "ro")]]

    def test_relative_path_rejected(self, test_client, auth_headers, cfgfile,
                                    applied):
        r = test_client.post("/api/nfs", headers=auth_headers,
                             json={"path": "srv/nas/tank", "type": "rw"})
        assert r.status_code == 400
        assert applied == []

    def test_unknown_type_rejected(self, test_client, auth_headers, cfgfile,
                                   applied, dirs):
        # a freeform option string must never be able to reach /etc/exports
        r = test_client.post("/api/nfs", headers=auth_headers,
                             json={"path": dirs("tank"), "type": "rw,no_root_squash"})
        assert r.status_code == 400
        assert applied == []

    def test_missing_folder_rejected(self, test_client, auth_headers, cfgfile,
                                     applied, tmp_path):
        """exportfs drops an entry whose path does not exist and says nothing,
        so saving one produced a green checkmark and no share. It must be a
        400 with a message the user can act on."""
        ghost = str(tmp_path / "not-created-yet")
        r = test_client.post("/api/nfs", headers=auth_headers,
                             json={"path": ghost, "type": "rw"})
        assert r.status_code == 400
        assert "doesn't exist" in r.json()["detail"]
        assert applied == []

    def test_duplicate_path_rejected(self, test_client, auth_headers, cfgfile,
                                    applied, dirs):
        body = {"path": dirs("tank"), "type": "rw"}
        assert test_client.post("/api/nfs", headers=auth_headers, json=body).status_code == 200
        assert test_client.post("/api/nfs", headers=auth_headers, json=body).status_code == 400

    def test_non_admin_rejected(self, test_client, user_headers, cfgfile,
                                applied, dirs):
        r = test_client.post("/api/nfs", headers=user_headers,
                             json={"path": dirs("tank"), "type": "rw"})
        assert r.status_code == 403
        assert applied == []


class TestReplace:
    def test_replaces_the_whole_set_in_one_go(self, test_client, auth_headers,
                                              cfgfile, applied, dirs):
        a, b = dirs("a"), dirs("b")
        r = test_client.put("/api/nfs", headers=auth_headers, json={"exports": [
            {"path": a, "type": "rw"},
            {"path": b, "type": "ro"},
        ]})
        assert r.status_code == 200
        assert len(r.json()["exports"]) == 2
        # ONE apply, not one per export: no half-applied state
        assert len(applied) == 1

    def test_can_change_the_lan_cidr(self, test_client, auth_headers, cfgfile,
                                     applied):
        r = test_client.put("/api/nfs", headers=auth_headers,
                            json={"exports": [], "lan_cidr": "192.168.1.0/24"})
        assert r.status_code == 200
        assert r.json()["lan_cidr"] == "192.168.1.0/24"

    def test_bad_set_is_rejected_whole(self, test_client, auth_headers,
                                       cfgfile, applied, dirs):
        r = test_client.put("/api/nfs", headers=auth_headers, json={"exports": [
            {"path": dirs("ok"), "type": "rw"},
            {"path": "not-absolute", "type": "ro"},
        ]})
        assert r.status_code == 400
        assert applied == [], "a bad entry must not half-apply the good ones"

    def test_missing_folder_rejects_the_whole_set(self, test_client,
                                                  auth_headers, cfgfile, applied,
                                                  dirs, tmp_path):
        r = test_client.put("/api/nfs", headers=auth_headers, json={"exports": [
            {"path": dirs("ok"), "type": "rw"},
            {"path": str(tmp_path / "ghost"), "type": "ro"},
        ]})
        assert r.status_code == 400
        assert applied == []


class TestToggle:
    def test_enables_then_disables(self, test_client, auth_headers, cfgfile,
                                   applied):
        r = test_client.post("/api/nfs/toggle", headers=auth_headers,
                             json={"enabled": True})
        assert r.status_code == 200 and r.json()["enabled"] is True
        r = test_client.post("/api/nfs/toggle", headers=auth_headers,
                             json={"enabled": False})
        assert r.status_code == 200 and r.json()["enabled"] is False

    def test_non_admin_rejected(self, test_client, user_headers, cfgfile,
                                applied):
        assert test_client.post("/api/nfs/toggle", headers=user_headers,
                                json={"enabled": True}).status_code == 403


class TestDelete:
    def test_removes_by_index(self, test_client, auth_headers, cfgfile, applied,
                              dirs):
        a, b = dirs("a"), dirs("b")
        test_client.put("/api/nfs", headers=auth_headers, json={"exports": [
            {"path": a, "type": "rw"},
            {"path": b, "type": "ro"},
        ]})
        r = test_client.delete("/api/nfs/0", headers=auth_headers)
        assert r.status_code == 200
        paths = [e["path"] for e in r.json()["exports"]]
        assert paths == [b]

    def test_out_of_range_is_404(self, test_client, auth_headers, cfgfile,
                                 applied):
        assert test_client.delete("/api/nfs/7", headers=auth_headers).status_code == 404

    def test_non_admin_rejected(self, test_client, user_headers, cfgfile,
                                applied):
        assert test_client.delete("/api/nfs/0", headers=user_headers).status_code == 403


class TestApplyFailureIsNotSilent:
    """Regression: registry.apply_one() never raises — it RETURNS
    ApplyResult(ok=False, error=...). Checking only for GeneratorError and
    dropping the result made the API answer 200 while the generator had
    written nothing at all."""

    def test_write_failure_surfaces_as_500(self, test_client, auth_headers,
                                           cfgfile, dirs, monkeypatch):
        import nfs_api
        from generators.registry import ApplyResult

        monkeypatch.setattr(nfs_api, "_apply", None)
        monkeypatch.setattr(
            nfs_api.registry, "apply_one",
            lambda name, cfg=None: ApplyResult(service="nfs", ok=False,
                                               error="Read-only file system"))
        r = test_client.post("/api/nfs", headers=auth_headers,
                             json={"path": dirs("tank"), "type": "rw"})
        assert r.status_code == 500
        assert "Read-only file system" in r.json()["detail"]


class TestGeneratorShape:
    """The API is only useful if the generator it drives renders what NFS
    actually needs. These assert the join between the two."""

    def _render(self, enabled, exports, cidr="10.0.0.0/24"):
        import forgeos_config as fc
        from generators.nfs import NfsGenerator
        cfg = fc.ForgeOSConfig.model_validate({
            "nfs": {"enabled": enabled, "lan_cidr": cidr,
                    "exports": [{"path": p, "type": ty} for p, ty in exports]}})
        return NfsGenerator().render(cfg)

    def test_disabled_renders_nothing(self):
        assert self._render(False, [("/srv/nas/tank", "rw")]) == []

    def test_enabled_renders_the_pseudo_root_and_exports(self):
        files = self._render(True, [("/srv/nas/tank/media", "ro")])
        assert len(files) == 1
        body = files[0].content
        assert "fsid=0" in body, "NFSv4 needs the pseudo-root export"
        assert "/srv/nas/tank/media 10.0.0.0/24(ro," in body

    def test_export_type_selects_the_option_set(self):
        body = self._render(True, [("/a", "public"), ("/b", "backup")])[0].content
        assert "all_squash" in body, "public exports squash everyone"
        assert "sync" in body and "root_squash" in body, "backup exports are sync"

    def test_lan_cidr_reaches_the_rendered_line(self):
        body = self._render(True, [("/a", "rw")], cidr="192.168.5.0/24")[0].content
        assert "192.168.5.0/24" in body
