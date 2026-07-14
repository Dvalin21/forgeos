"""Server-database (Postgres / MariaDB) durability generator.

Data Connect patch 3. For tracked server DBs this generator pins the
durability settings whose absence is the #1 corruption cause, and manages
the weekly integrity-check timer:

  Postgres  -> /etc/postgresql/<ver>/main/conf.d/forgeos.conf
               fsync=on, synchronous_commit=on, full_page_writes=on.
               Debian enables the conf.d include_dir in its packages; all
               three settings are SIGHUP-reloadable, so apply() reloads.
  MariaDB   -> /etc/mysql/mariadb.conf.d/99-forgeos.cnf
               innodb_flush_log_at_trx_commit=1. MariaDB has no config
               reload; the value is already the engine default, so the
               drop-in is drift-prevention that binds on next restart.

These pin engine DEFAULTS on purpose: the failure mode is someone "tuning
for speed" (fsync=off) on a box whose whole job is holding the data.

The forgeos-dbcheck.{service,timer} units are STATIC files shipped by the
installer (pg_amcheck --install-missing / mysqlcheck, engine-guarded); this
generator only enables/disables the timer, so the API sandbox never needs
write access to /etc/systemd/system.
"""
from __future__ import annotations

import glob as _glob
from pathlib import Path

from generators import RenderedFile, ServiceGenerator

MYSQL_DROPIN = "/etc/mysql/mariadb.conf.d/99-forgeos.cnf"
DBCHECK_TIMER = "forgeos-dbcheck.timer"

PG_DROPIN_CONTENT = """# ForgeOS Data Connect — GENERATED, do not edit.
# Pins the durability floor; removing these invites corruption on power loss.
fsync = on
synchronous_commit = on
full_page_writes = on
"""

MYSQL_DROPIN_CONTENT = """# ForgeOS Data Connect — GENERATED, do not edit.
# Durability floor: committed transactions must be on disk (engine default,
# pinned here against speed-tuning drift). Binds on next MariaDB restart.
[mysqld]
innodb_flush_log_at_trx_commit = 1
"""


def _pg_confdirs() -> list[str]:
    """Debian per-cluster conf.d dirs. Seam: tests monkeypatch this."""
    return sorted(_glob.glob("/etc/postgresql/*/main/conf.d"))


def _tracked_kinds(cfg) -> set[str]:
    dc = getattr(cfg, "data_connect", None)
    if dc is None or not dc.enabled:
        return set()
    return {d.kind for d in dc.databases if d.kind in ("postgres", "mysql")}


class DbServerGenerator(ServiceGenerator):
    name = "dbserver"

    def render(self, cfg) -> list[RenderedFile]:
        kinds = _tracked_kinds(cfg)
        out: list[RenderedFile] = []
        if "postgres" in kinds:
            for d in _pg_confdirs():
                out.append(RenderedFile(path=f"{d}/forgeos.conf",
                                        content=PG_DROPIN_CONTENT))
        if "mysql" in kinds:
            out.append(RenderedFile(path=MYSQL_DROPIN,
                                    content=MYSQL_DROPIN_CONTENT))
        return out

    # Known emit locations for stale-file cleanup when a DB is untracked.
    def _known_paths(self) -> list[str]:
        return [f"{d}/forgeos.conf" for d in _pg_confdirs()] + [MYSQL_DROPIN]

    def apply(self, cfg, *, do_reload: bool = True) -> list[str]:
        files = self.render(cfg)
        want = {f.path for f in files}
        written: list[str] = []
        for rf in files:
            self._atomic_write(rf)
            written.append(rf.path)
        removed_pg = False
        for known in self._known_paths():
            if known not in want and Path(known).exists():
                Path(known).unlink()
                removed_pg = removed_pg or "postgresql" in known
        if do_reload:
            kinds = _tracked_kinds(cfg)
            if "postgres" in kinds or removed_pg:
                # All pinned PG settings are SIGHUP-context — reload suffices,
                # never a client-dropping restart.
                self._run(["systemctl", "reload", "postgresql"], check=False)
            if kinds:
                self._run(["systemctl", "enable", "--now", DBCHECK_TIMER],
                          check=False)
            else:
                self._run(["systemctl", "disable", "--now", DBCHECK_TIMER],
                          check=False)
        return written
