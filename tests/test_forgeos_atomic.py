"""The single shared atomic writer."""
import errno
import os
import stat

import pytest

import forgeos_atomic as fa


def test_writes_content_and_mode(tmp_path):
    t = tmp_path / "sub" / "f.conf"          # parent created on demand
    fa.atomic_write(t, "hello\n", 0o600)
    assert t.read_text() == "hello\n"
    assert stat.S_IMODE(t.stat().st_mode) == 0o600


def test_replaces_existing_atomically(tmp_path):
    t = tmp_path / "f.conf"
    t.write_text("old\n")
    fa.atomic_write(t, "new\n")
    assert t.read_text() == "new\n"
    # no temp litter left behind
    assert [p.name for p in tmp_path.iterdir()] == ["f.conf"]


def test_accepts_str_path(tmp_path):
    t = tmp_path / "f.conf"
    fa.atomic_write(str(t), "x\n")
    assert t.read_text() == "x\n"


@pytest.mark.parametrize("err", [errno.EROFS, errno.EACCES, errno.EPERM])
def test_falls_back_when_parent_unwritable(tmp_path, monkeypatch, err):
    """File-level ProtectSystem carve-outs leave the parent dir read-only, so
    mkstemp there fails even though the target itself is writable."""
    t = tmp_path / "resolv.conf"
    t.write_text("old\n")
    monkeypatch.setattr(fa.tempfile, "mkstemp",
                        lambda *a, **k: (_ for _ in ()).throw(OSError(err, "ro")))
    fa.atomic_write(t, "nameserver 1.1.1.1\n")
    assert t.read_text() == "nameserver 1.1.1.1\n"


def test_other_oserrors_propagate(tmp_path, monkeypatch):
    """A real fault must not be masked by the fallback."""
    monkeypatch.setattr(fa.tempfile, "mkstemp",
                        lambda *a, **k: (_ for _ in ()).throw(
                            OSError(errno.ENOSPC, "No space left on device")))
    with pytest.raises(OSError):
        fa.atomic_write(tmp_path / "f.conf", "x")


def test_temp_file_cleaned_up_on_write_failure(tmp_path, monkeypatch):
    t = tmp_path / "f.conf"
    real = os.replace
    monkeypatch.setattr(os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        fa.atomic_write(t, "x")
    monkeypatch.setattr(os, "replace", real)
    assert list(tmp_path.iterdir()) == []     # no .forgeos-*.tmp litter
