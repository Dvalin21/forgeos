"""LHSR execution: the destructive path.

`forgeos_lhsr_exec.execute_layout` runs `sgdisk --zap-all`, `mkfs.btrfs` and
mergerfs. It had NO tests at all, which is how it shipped two defects that only
show up on real hardware:

  * it UNMOUNTED every tier before handing the tier mountpoints to mergerfs,
    so the span was built over empty directories and the tier data became
    unreachable — on a box that had just been partitioned and formatted;
  * it accepted a `force` flag it never read, so nothing stood between a
    mistyped device (or the system disk) and `sgdisk --zap-all`.

These tests drive the real function with an injected command runner, so they
prove the ORDER and the GUARDS without touching a disk.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# captured before any monkeypatch replaces builtins.open
_REAL_OPEN = open

import forgeos_lhsr as lhsr            # noqa: E402
import forgeos_lhsr_exec as exec_mod   # noqa: E402


class FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


@pytest.fixture
def layout():
    """A real computed layout for three same-size disks (LHSR1, one raid1 tier)."""
    return lhsr.plan_layout(
        [("/dev/sdb", 1_000_000_000_000), ("/dev/sdc", 1_000_000_000_000),
         ("/dev/sdd", 1_000_000_000_000)],
        parity=1,
    )


@pytest.fixture
def no_guards(monkeypatch):
    """Sandbox for the happy path.

    Two jobs. (1) Report each layout disk as a blank, unmounted, unused disk so
    the safety guards PASS and the test exercises ordering/assembly rather than
    lsblk parsing. (2) Stub the three partitioning primitives, which call
    `_run` directly (not the injected runner) and would otherwise shell out to
    sgdisk/partprobe on the test host.
    """
    import forgeos_diskprep as dp

    def disks():
        return [dp.DiskInfo(name=p.rsplit("/", 1)[-1], path=p, size_bytes=1_000_000_000_000)
                for p in ("/dev/sdb", "/dev/sdc", "/dev/sdd")]

    monkeypatch.setattr(dp, "inspect_disks", disks)
    monkeypatch.setattr(exec_mod, "_partition_disk",
                        lambda path, layout, idx: [1])
    monkeypatch.setattr(exec_mod, "_reread_partitions", lambda path: None)
    monkeypatch.setattr(exec_mod, "_wait_for_part", lambda path, n: None)


def _runner(blkid_uuid="UUID-TEST"):
    calls = []

    def run(cmd, timeout=None):
        calls.append(list(cmd))
        if cmd[0] == "blkid":
            return FakeCompleted(stdout=blkid_uuid + "\n")
        return FakeCompleted()

    return calls, run


class TestMountOrder:
    def test_tier_mountpoints_stay_mounted_for_mergerfs(self, layout, no_guards,
                                                        tmp_path, monkeypatch):
        """The core defect. mergerfs merges the tier BRANCH mountpoints, so
        every tier must still be mounted when it runs."""
        calls, run = _runner()
        # keep the fstab write inside the test
        monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: None)
        monkeypatch.setattr("builtins.open", _FakeOpen(tmp_path))

        exec_mod.execute_layout(layout, runner=run)

        umounts = [c for c in calls if c[0] == "umount"]
        assert umounts == [], f"tiers must NOT be unmounted before mergerfs, got {umounts}"

        merges = [c for c in calls if c[0] == "mergerfs"]
        assert len(merges) == 1, "mergerfs must be mounted exactly once"
        branches = merges[0][1].split(":")
        assert branches, "mergerfs needs at least one branch mountpoint"

        # order: every tier mount happens before mergerfs runs
        first_merge = calls.index(merges[0])
        tier_mounts = [i for i, c in enumerate(calls)
                       if c[0] == "mount" and c[2].startswith("/srv/lhsr_tier")]
        assert tier_mounts, "no tier was mounted at all"
        assert max(tier_mounts) < first_merge, \
            "every tier must be mounted BEFORE mergerfs runs"
        # and mergerfs is handed exactly the tier mountpoints we mounted
        assert branches == [c[2] for c in calls
                            if c[0] == "mount" and c[2].startswith("/srv/lhsr_tier")]

    def test_each_tier_is_mounted_once(self, layout, no_guards, tmp_path,
                                       monkeypatch):
        calls, run = _runner()
        monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: None)
        monkeypatch.setattr("builtins.open", _FakeOpen(tmp_path))
        exec_mod.execute_layout(layout, runner=run)
        tier_mounts = [c for c in calls
                       if c[0] == "mount" and c[2].startswith("/srv/lhsr_tier")]
        assert len(tier_mounts) == layout.tier_count


class TestDiskGuards:
    """`sgdisk --zap-all` is unconditional — nothing may reach it on a disk
    that is not safe to destroy."""

    def test_system_disk_is_refused_even_with_force(self, layout, tmp_path,
                                                   monkeypatch, no_guards):
        import forgeos_diskprep as dp
        info = dp.DiskInfo(name="sdb", path="/dev/sdb", size_bytes=1, is_system=True,
                           mounted=False, in_array=False,
                           has_partition_table=True, has_filesystem=False,
                           mountpoints=())
        monkeypatch.setattr(dp, "inspect_disks", lambda: [info])
        calls, run = _runner()
        monkeypatch.setattr("builtins.open", _FakeOpen(tmp_path))

        with pytest.raises(exec_mod.LhsrExecError) as exc:
            exec_mod.execute_layout(layout, force=True, runner=run)

        assert "REFUSED" in str(exc.value)
        assert "system" in str(exc.value).lower()
        # nothing destructive ran at all
        assert [c for c in calls if c[0] == "sgdisk"] == []

    def test_mounted_disk_is_refused(self, layout, tmp_path, monkeypatch, no_guards):
        import forgeos_diskprep as dp
        info = dp.DiskInfo(name="sdb", path="/dev/sdb", size_bytes=1, is_system=False,
                           mounted=True, in_array=False,
                           has_partition_table=True, has_filesystem=True,
                           mountpoints=("/data",))
        monkeypatch.setattr(dp, "inspect_disks", lambda: [info])
        calls, run = _runner()
        monkeypatch.setattr("builtins.open", _FakeOpen(tmp_path))

        with pytest.raises(exec_mod.LhsrExecError):
            exec_mod.execute_layout(layout, force=True, runner=run)
        assert [c for c in calls if c[0] == "sgdisk"] == []

    def test_unknown_device_is_refused(self, layout, tmp_path, monkeypatch):
        import forgeos_diskprep as dp
        monkeypatch.setattr(dp, "inspect_disks", lambda: [])
        calls, run = _runner()
        monkeypatch.setattr("builtins.open", _FakeOpen(tmp_path))
        with pytest.raises(exec_mod.LhsrExecError):
            exec_mod.execute_layout(layout, force=True, runner=run)
        assert [c for c in calls if c[0] == "sgdisk"] == []


class TestFstab:
    def test_block_is_replaced_not_stacked(self, tmp_path, monkeypatch, no_guards):
        """A second create must not append a duplicate stanza (dead UUIDs keep
        the old tiers mounted forever)."""
        fstab = tmp_path / "fstab"
        fstab.write_text("UUID=ROOT / ext4 defaults 0 1\n"
                         "# ForgeOS LHSR\nUUID=OLD /srv/lhsr_tier_0 btrfs defaults,noatime 0 0\n")
        monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: None)
        monkeypatch.setattr("builtins.open", _FakeOpen(tmp_path))
        calls, run = _runner()
        exec_mod.execute_layout(_LAYOUT, runner=run)
        text = fstab.read_text()
        assert text.count("# ForgeOS LHSR") == 1
        assert "UUID=OLD" not in text, "the previous tier stanza must be gone"
        assert text.startswith("UUID=ROOT"), "entries above the block must survive"
        assert "UUID-TEST" in text

    def test_empty_uuid_never_writes_a_poison_line(self, tmp_path, monkeypatch, no_guards):
        fstab = tmp_path / "fstab"
        fstab.write_text("UUID=ROOT / ext4 defaults 0 1\n")
        monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: None)
        monkeypatch.setattr("builtins.open", _FakeOpen(tmp_path))
        calls, run = _runner(blkid_uuid="")
        exec_mod.execute_layout(_LAYOUT, runner=run)
        text = fstab.read_text()
        assert "UUID=  " not in text, "an empty UUID would break boot"
        assert "UUID-TEST" not in text


_LAYOUT = lhsr.plan_layout(
    [("/dev/sdb", 1_000_000_000_000), ("/dev/sdc", 1_000_000_000_000),
     ("/dev/sdd", 1_000_000_000_000)], parity=1)


class _FakeOpen:
    """Redirect every open() inside execute_layout to the test's fstab file,
    so the real /etc/fstab is never touched."""

    def __init__(self, tmp_path):
        self.path = Path(tmp_path) / "fstab"
        if not self.path.exists():
            self.path.write_text("")

    def __call__(self, file, mode="r", *a, **k):
        return _REAL_OPEN(self.path, mode, *a, **k)