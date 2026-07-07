

class TestDrEndpoints:
    def test_dr_status_shape(self, test_client, auth_headers):
        from unittest.mock import patch, MagicMock
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="inactive\n")):
            r = test_client.get("/api/backup/dr", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        for k in ("enabled", "backup_path", "schedule", "rear_installed",
                  "config_rendered", "timer_active", "artifacts"):
            assert k in d
        assert d["timer_active"] is False

    def test_dr_put_rejects_root_path(self, test_client, auth_headers):
        r = test_client.put("/api/backup/dr", headers=auth_headers,
                            json={"enabled": True, "backup_path": "/etc"})
        assert r.status_code == 400

    def test_dr_put_requires_admin(self, test_client, user_headers):
        r = test_client.put("/api/backup/dr", headers=user_headers,
                            json={"enabled": False})
        assert r.status_code == 403

    def test_dr_put_disabled_saves_without_render(self, test_client, auth_headers, tmp_path, monkeypatch):
        import forgeos_config as fcfg
        r = test_client.put("/api/backup/dr", headers=auth_headers,
                            json={"enabled": False, "backup_path": "/mnt/backup/osbackup"})
        assert r.status_code == 200
        assert r.json()["next_command"] is None
        assert fcfg.load().osbackup.backup_path == "/mnt/backup/osbackup"
