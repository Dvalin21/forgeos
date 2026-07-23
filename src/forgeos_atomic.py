"""The one atomic-write helper for the whole codebase.

Four near-identical copies of this used to live in net_networkd, generators,
forgeos_osbackup and nginx_api. Only one of them had the read-only-parent
fallback, which is precisely how a revert died on hardware: the copies drift,
and the next caller to target a file-level path reintroduces the bug. One
implementation, one place to fix.

Not converted (deliberately): forgeos_auth._save_users and
forgeos_config.save_config write JSON inline into /etc/forgeos — a DIRECTORY
carve-out where mkstemp always works — so they carry no risk and rewriting the
auth user store buys nothing.
"""
from __future__ import annotations

import errno
import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write"]

# errnos that mean "this directory is not writable" rather than a real fault
_READONLY_ERRNOS = (errno.EROFS, errno.EACCES, errno.EPERM)


def _write_in_place(path: Path, content: str, mode: int) -> None:
    """Truncate-and-write the target directly.

    ponytail: not atomic — a crash mid-write leaves a partial file. Only used
    when the parent directory is read-only so no temp file can exist there;
    upgrade if a durability-critical target ever lands in such a directory.
    """
    with open(path, "w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def atomic_write(path: str | Path, content: str, mode: int = 0o644) -> None:
    """Write `content` to `path` atomically: temp file + fsync + chmod + rename.

    Falls back to an in-place write when the parent directory is read-only.
    systemd ProtectSystem=strict carve-outs can be FILE-level (the unit grants
    -/etc/resolv.conf, not /etc), which leaves the parent unwritable even
    though the target itself is writable — mkstemp there fails with EROFS.
    Any other OSError propagates; a genuine fault must not be masked.
    """
    p = Path(path)
    if not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".forgeos-", suffix=".tmp")
    except OSError as e:
        if e.errno not in _READONLY_ERRNOS:
            raise
        _write_in_place(p, content, mode)
        return
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
