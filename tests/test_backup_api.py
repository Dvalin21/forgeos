

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


class TestBackupActivityScope:
    """/api/backup/tasks must show ONLY backup-tool tasks, not the whole
    shared registry (which also holds e.g. certbot tasks)."""

    def _seed(self, mod):
        mod._background_tasks.clear()
        mod._background_tasks.update({
            "b1": {"id": "b1", "tool": "borg",    "action": "create",   "status": "done",    "started_at": 100},
            "r1": {"id": "r1", "tool": "restic",  "action": "snapshot", "status": "running", "started_at": 200},
            "s1": {"id": "s1", "tool": "rclone",  "action": "sync",     "status": "done",    "started_at": 150},
            "c1": {"id": "c1", "tool": "certbot", "action": "dns-01",   "status": "done",    "started_at": 300},
            "x1": {"id": "x1", "tool": "certbot", "action": "domain-add","status": "failed", "started_at": 250},
        })

    def test_list_excludes_non_backup_tools(self, test_client, auth_headers):
        import backup_api as mod
        self._seed(mod)
        try:
            r = test_client.get("/api/backup/tasks", headers=auth_headers)
            assert r.status_code == 200
            tools = {t["tool"] for t in r.json()["tasks"]}
            assert tools == {"borg", "restic", "rclone"}   # NO certbot
            assert all(t["tool"] != "certbot" for t in r.json()["tasks"])
        finally:
            mod._background_tasks.clear()

    def test_list_still_newest_first(self, test_client, auth_headers):
        import backup_api as mod
        self._seed(mod)
        try:
            r = test_client.get("/api/backup/tasks", headers=auth_headers)
            ids = [t["id"] for t in r.json()["tasks"]]
            assert ids == ["r1", "s1", "b1"]   # 200,150,100 desc; certbot excluded
        finally:
            mod._background_tasks.clear()

    def test_single_task_hides_non_backup(self, test_client, auth_headers):
        import backup_api as mod
        self._seed(mod)
        try:
            # a backup task is visible
            assert test_client.get("/api/backup/task/b1", headers=auth_headers).status_code == 200
            # a certbot task is NOT reachable through the backup namespace
            assert test_client.get("/api/backup/task/c1", headers=auth_headers).status_code == 404
        finally:
            mod._background_tasks.clear()


class TestToolVersionDetection:
    """borg's version probe was `borg version`, which borg parses as a
    positional REPOSITORY arg and exits non-zero — so an installed borg was
    reported missing. The probe must use `borg --version`."""

    def _capture_cmd(self, monkeypatch):
        import backup_api as mod
        seen = {}
        from unittest.mock import MagicMock
        def fake_run(cmd, *a, **k):
            seen["cmd"] = cmd
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        return mod, seen

    def test_borg_probed_with_dash_dash_version(self, monkeypatch):
        mod, seen = self._capture_cmd(monkeypatch)
        assert mod._check_tool("borg") is True
        # the exact bug: must be --version, NOT the `version` subcommand
        assert seen["cmd"] == ["borg", "--version"]
        assert "version" not in seen["cmd"][1:] or seen["cmd"][1] == "--version"

    def test_all_backup_tools_use_dash_dash_version(self, monkeypatch):
        mod, seen = self._capture_cmd(monkeypatch)
        for tool in mod.BACKUP_TOOLS:
            mod._check_tool(tool)
            assert seen["cmd"] == [tool, "--version"], f"{tool}: {seen['cmd']}"

    def test_borg_status_reports_installed_when_borg_runs(self, test_client,
                                                          auth_headers, monkeypatch):
        """End to end: a borg that exits 0 on --version shows installed=True."""
        import backup_api as mod
        from unittest.mock import MagicMock
        def fake_run(cmd, *a, **k):
            # simulate real borg: --version → 0, `version` subcommand → 2
            if cmd[:2] == ["borg", "--version"]:
                return MagicMock(returncode=0, stdout=b"borg 1.2.4\n", stderr=b"")
            if cmd[:2] == ["borg", "version"]:
                return MagicMock(returncode=2, stdout=b"", stderr=b"error")
            return MagicMock(returncode=0, stdout=b"[]", stderr=b"")
        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        r = test_client.get("/api/backup/borg/status", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["installed"] is True

    def test_missing_tool_still_reports_false(self, monkeypatch):
        import backup_api as mod
        def boom(cmd, *a, **k):
            raise FileNotFoundError(cmd[0])
        monkeypatch.setattr(mod.subprocess, "run", boom)
        assert mod._check_tool("borg") is False
