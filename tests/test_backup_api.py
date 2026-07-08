

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


class TestDirBrowser:
    def test_lists_dirs_only(self, test_client, auth_headers, tmp_path, monkeypatch):
        (tmp_path / "photos").mkdir(); (tmp_path / "docs").mkdir()
        (tmp_path / "file.txt").write_text("x")
        (tmp_path / ".hidden").mkdir()
        r = test_client.get("/api/fs/dirs?path=" + str(tmp_path), headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["dirs"] == ["docs", "photos"]

    def test_excludes_pseudo_filesystems(self, test_client, auth_headers):
        for p in ("/proc", "/sys", "/proc/1", "/srv/../proc"):
            r = test_client.get("/api/fs/dirs?path=" + p, headers=auth_headers)
            assert r.status_code == 400, p

    def test_requires_admin(self, test_client, user_headers):
        assert test_client.get("/api/fs/dirs?path=/srv", headers=user_headers).status_code == 403

    def test_missing_dir_404(self, test_client, auth_headers):
        assert test_client.get("/api/fs/dirs?path=/definitely/not/here",
                               headers=auth_headers).status_code == 404


class TestBackupDefaults:
    def test_derives_from_first_pool(self, test_client, auth_headers):
        import forgeos_config as fcfg
        cfg = fcfg.load()
        cfg.storage.pools.append(fcfg.StoragePool(name="tank", uuid="u", mountpoint="/srv/nas/tank"))
        fcfg.save(cfg)
        d = test_client.get("/api/backup/defaults", headers=auth_headers).json()
        assert d["destination_base"] == "/srv/nas/tank/backups"

    def test_empty_mountpoint_uses_derived_default(self, test_client, auth_headers):
        import forgeos_config as fcfg
        cfg = fcfg.load()
        cfg.storage.pools.append(fcfg.StoragePool(name="tank", uuid="u"))
        fcfg.save(cfg)
        d = test_client.get("/api/backup/defaults", headers=auth_headers).json()
        assert d["destination_base"] == "/srv/nas/tank/backups"

    def test_no_pools_empty(self, test_client, auth_headers):
        d = test_client.get("/api/backup/defaults", headers=auth_headers).json()
        assert d["destination_base"] == "" and d["pool"] is None


class TestTaskFailureCapturesStdout:
    """certbot writes its real reason to stdout, not stderr — the runner must
    keep stdout on failure or the user gets a useless 'Exit code 1'.
    Exercises the real _run_background from forgeos-api.py."""

    def _load_mod(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("forgeos_api_mod", "src/forgeos-api.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_failure_keeps_stdout_detail(self, monkeypatch):
        try:
            mod = self._load_mod()
        except Exception:
            import pytest; pytest.skip("forgeos-api.py not importable standalone in this env")
        from unittest.mock import MagicMock
        monkeypatch.setattr(mod, "_persist_tasks", lambda: None)
        monkeypatch.setattr(mod, "_update_job_from_task", lambda *a, **k: None)
        monkeypatch.setattr(mod.subprocess, "run",
                            lambda *a, **k: MagicMock(returncode=1,
                                                      stdout="ACME challenge failed: DNS problem",
                                                      stderr=""))
        tid = "t1"
        mod._background_tasks[tid] = {"id": tid, "status": "pending", "error": None}
        mod._run_background(["certbot"], tid, timeout=10)
        assert "ACME challenge failed" in mod._background_tasks[tid]["error"]
