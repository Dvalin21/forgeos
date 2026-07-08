"""
ForgeOS system endpoint tests.

The dashboard depends on /api/system/info for the CPU model label.
If this endpoint changes shape without a corresponding UI update,
the label silently shows nothing — worse than a crash.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


class TestSystemInfo:
    """GET /api/system/info — used by dashboard for CPU model label."""

    ENDPOINT = "/api/system/info"
    EXPECTED_FIELDS = {
        "hostname", "os", "kernel", "cpu",
        "cpu_cores", "forgeos_ver", "uptime", "boot_time",
    }

    def test_requires_auth(self, test_client: TestClient) -> None:
        r = test_client.get(self.ENDPOINT)
        assert r.status_code == 401

    def test_returns_all_fields(self, test_client: TestClient, auth_headers: dict[str, str]) -> None:
        r = test_client.get(self.ENDPOINT, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == self.EXPECTED_FIELDS, (
            f"Field mismatch. Got: {set(data.keys())}, Expected: {self.EXPECTED_FIELDS}"
        )
        for field in data:
            assert isinstance(data[field], str), f"{field} should be str, got {type(data[field])}"
        assert len(data["hostname"]) > 0
        assert len(data["os"]) > 0
        assert len(data["kernel"]) > 0
        assert len(data["cpu"]) > 0


class TestSettingsV2:
    """Rewritten /api/settings — config-DB truth, v1 shell-conf vocabulary
    (HIPAA/MariaDB/Redis/PROXY) deleted."""

    def test_get_shape_and_no_legacy_keys(self, test_client, auth_headers):
        from unittest.mock import patch, MagicMock
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="America/Chicago\n")):
            r = test_client.get("/api/settings", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        for k in ("effective_hostname", "lan_name", "public_fqdn", "timezone", "version"):
            assert k in d
        assert "HIPAA_ENABLED" not in d and "MARIADB_ENABLED" not in d

    def test_get_requires_admin(self, test_client, user_headers):
        assert test_client.get("/api/settings", headers=user_headers).status_code == 403

    def test_put_persists_identity(self, test_client, auth_headers):
        import forgeos_config as fcfg
        r = test_client.put("/api/settings", headers=auth_headers,
                            json={"lan_name": "nas.local", "public_fqdn": "nas.example.com"})
        assert r.status_code == 200
        c = fcfg.load().naming
        assert c.lan_name == "nas.local" and c.public_fqdn == "nas.example.com"

    def test_put_rejects_garbage_timezone(self, test_client, auth_headers):
        r = test_client.put("/api/settings", headers=auth_headers,
                            json={"timezone": "bad; rm -rf /"})
        assert r.status_code == 400

    def test_put_timezone_calls_timedatectl(self, test_client, auth_headers):
        from unittest.mock import patch, MagicMock
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as m:
            r = test_client.put("/api/settings", headers=auth_headers,
                                json={"timezone": "America/Chicago"})
        assert r.status_code == 200
        assert any(c.args[0][:2] == ["timedatectl", "set-timezone"] for c in m.call_args_list)


class TestSmtpSettings:
    def test_roundtrip_password_never_in_get(self, test_client, auth_headers, tmp_path, monkeypatch):
        import forgeos_smtp as fsmtp
        monkeypatch.setattr(fsmtp, "SMTP_KEY_DIR", str(tmp_path))
        r = test_client.put("/api/settings/smtp", headers=auth_headers, json={
            "enabled": True, "host": "smtp.example.com", "port": 587,
            "username": "u", "from_addr": "a@b.c", "to_addrs": ["k@b.c"],
            "password": "hunter2"})
        assert r.status_code == 200
        pw = tmp_path / "password"
        assert pw.read_text() == "hunter2"
        assert (pw.stat().st_mode & 0o777) == 0o600
        d = test_client.get("/api/settings/smtp", headers=auth_headers).json()
        assert d["password_set"] is True
        assert "hunter2" not in str(d)

    def test_put_rejects_bad_port(self, test_client, auth_headers):
        r = test_client.put("/api/settings/smtp", headers=auth_headers,
                            json={"port": 99999})
        assert r.status_code == 400

    def test_test_send_requires_enabled(self, test_client, auth_headers):
        test_client.put("/api/settings/smtp", headers=auth_headers, json={"enabled": False})
        r = test_client.post("/api/settings/smtp/test", headers=auth_headers)
        assert r.status_code == 400

    def test_smtp_requires_admin(self, test_client, user_headers):
        assert test_client.get("/api/settings/smtp", headers=user_headers).status_code == 403


class TestHostnameEdit:
    def test_put_hostname_calls_hostnamectl_and_persists(self, test_client, auth_headers):
        import forgeos_config as fcfg
        from unittest.mock import patch, MagicMock
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as m:
            r = test_client.put("/api/settings", headers=auth_headers,
                                json={"system_hostname": "forge2"})
        assert r.status_code == 200
        assert any(c.args[0][:2] == ["hostnamectl", "set-hostname"] for c in m.call_args_list)
        assert fcfg.load().naming.system_hostname == "forge2"

    def test_put_hostname_rejects_garbage(self, test_client, auth_headers):
        r = test_client.put("/api/settings", headers=auth_headers,
                            json={"system_hostname": "bad host;{}"})
        assert r.status_code == 400

    def test_blank_hostname_means_keep(self, test_client, auth_headers):
        from unittest.mock import patch, MagicMock
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as m:
            r = test_client.put("/api/settings", headers=auth_headers,
                                json={"lan_name": "x.local"})
        assert r.status_code == 200
        assert not any("hostnamectl" in c.args[0] for c in m.call_args_list)


class TestAppsList:
    def test_apps_list_shape(self, test_client, auth_headers):
        import forgeos_config as fcfg
        cfg = fcfg.load()
        cfg.apps.append(fcfg.InstalledApp(id="urbackup", version="2.5.37", webui_port=55414))
        fcfg.save(cfg)
        r = test_client.get("/api/apps", headers=auth_headers)
        assert r.status_code == 200
        a = r.json()["apps"][0]
        assert a["id"] == "urbackup" and a["url"].startswith("https://urbackup.")

    def test_apps_requires_auth(self, test_client):
        assert test_client.get("/api/apps").status_code in (401, 403)


class TestImagingNative:
    def test_status_not_installed(self, test_client, auth_headers):
        from unittest.mock import patch, MagicMock
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="")):
            r = test_client.get("/api/imaging", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["installed"] is False and d["running"] is False

    def test_status_installed_running(self, test_client, auth_headers):
        from unittest.mock import patch, MagicMock
        def fake(cmd, **kw):
            if cmd[0] == "dpkg-query":
                return MagicMock(returncode=0, stdout="2.5.37")
            return MagicMock(returncode=0, stdout="active\n")
        with patch("subprocess.run", side_effect=fake):
            d = test_client.get("/api/imaging", headers=auth_headers).json()
        assert d["installed"] and d["running"] and d["version"] == "2.5.37"
        assert d["url"].startswith("https://urbackup.")

    def test_install_adds_vhost_and_uninstall_removes(self, tmp_path, monkeypatch):
        import sys
        sys.path.insert(0, "src")
        import forgeos_imaging as fim
        import forgeos_config as fcfg
        from generators import registry
        from unittest.mock import MagicMock
        deb = tmp_path / "fake.deb"; deb.write_bytes(b"x" * 2_000_000)
        calls = []
        def fake(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == "curl":
                import shutil; shutil.copy(deb, cmd[3])
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd[0] == "dpkg-query":
                return MagicMock(returncode=0, stdout="2.5.37")
            return MagicMock(returncode=0, stdout="active\n", stderr="")
        monkeypatch.setattr(registry, "apply_one",
                            lambda name, cfg=None: MagicMock(ok=True))
        st = fim.install(run=fake)
        assert st["installed"]
        assert any(c[0] == "apt-get" and "install" in c for c in calls)
        assert any(v.name == "urbackup" for v in fcfg.load().nginx.vhosts)
        fim.uninstall(run=fake)
        assert not any(v.name == "urbackup" for v in fcfg.load().nginx.vhosts)

    def test_install_rejects_tiny_download(self, tmp_path):
        import sys; sys.path.insert(0, "src")
        import forgeos_imaging as fim
        from unittest.mock import MagicMock
        import pytest as pt
        def fake(cmd, **kw):
            if cmd[0] == "curl":
                open(cmd[3], "w").write("404 page")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="")
        with pt.raises(fim.ImagingError):
            fim.install(run=fake)
