"""Database + user provisioning inside Postgres / MariaDB engines.

Security model, stated up front because this file executes privileged SQL:

* SUPERUSER ACCESS IS BY UNIX SOCKET, NEVER A STORED PASSWORD. forgeos-api
  runs as root; Debian's postgres trusts local `postgres` via peer auth and
  MariaDB trusts local `root` via unix_socket. So ForgeOS runs CREATE/DROP as
  the engine admin without ever holding the admin credential. There is no
  superuser secret to leak.

* THE ONLY SECRETS ForgeOS HOLDS are the per-app passwords it generates, and
  it holds them SHOW-ONCE: the plaintext is returned to the caller exactly
  once at creation, and only a bcrypt hash is persisted (db-secrets.json,
  0600, root). ForgeOS can therefore VERIFY a password but never REVEAL one —
  a lost password is reset (new password, new hash), not recovered.

* IDENTIFIERS ARE THE INJECTION SURFACE. Database and user names land in
  `CREATE DATABASE <name>` / `CREATE USER <name>` where SQL has no parameter
  binding. They are validated to a strict charset AND quoted per engine.
  Passwords DO go through parameter binding / proper escaping.
"""
from __future__ import annotations

import json
import re
import secrets
import string
import subprocess
from pathlib import Path

from forgeos_auth import pwd_ctx

SECRETS_FILE = Path("/etc/forgeos/db-secrets.json")

# Strict identifier charset: letters, digits, underscore; must start with a
# letter or underscore. Rejects everything that could break out of an
# identifier context — no quotes, no semicolons, no spaces, no hyphens.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")


class ProvisionError(Exception):
    """Raised for validation failures and engine command failures."""


def valid_identifier(name: str) -> bool:
    return bool(_IDENT.fullmatch(name or ""))


def _require_identifier(name: str, what: str) -> str:
    if not valid_identifier(name):
        raise ProvisionError(
            f"invalid {what} {name!r}: use letters, digits and underscore, "
            f"starting with a letter (max 63 chars)")
    return name


def generate_password(length: int = 24) -> str:
    # url-safe-ish printable set minus shell/SQL-hostile chars; length >= 24
    alphabet = string.ascii_letters + string.digits + "._~-"
    return "".join(secrets.choice(alphabet) for _ in range(max(length, 24)))


# ── secret store (bcrypt hashes only, never plaintext) ──────────────────────
def _load_secrets() -> dict:
    if SECRETS_FILE.exists():
        try:
            return json.loads(SECRETS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_secrets(data: dict) -> None:
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # write 0600 BEFORE content so the plaintext-hash never exists world-readable
    tmp = SECRETS_FILE.with_suffix(".json.new")
    tmp.touch(mode=0o600, exist_ok=True)
    tmp.write_text(json.dumps(data, indent=1))
    tmp.chmod(0o600)
    tmp.replace(SECRETS_FILE)
    SECRETS_FILE.chmod(0o600)


def store_password_hash(key: str, password: str) -> None:
    d = _load_secrets()
    d[key] = pwd_ctx.hash(password)
    _save_secrets(d)


def verify_password(key: str, password: str) -> bool:
    d = _load_secrets()
    h = d.get(key)
    return bool(h) and pwd_ctx.verify(password, h)


def forget_secret(key: str) -> None:
    d = _load_secrets()
    if key in d:
        del d[key]
        _save_secrets(d)


# ── engine command execution (socket auth, root) ────────────────────────────
# Overridable for tests so no real engine / no real SQL runs.
_run = None


def set_run(fn) -> None:
    global _run
    _run = fn


def _exec(cmd: list[str], sql: str, timeout: int = 30) -> subprocess.CompletedProcess:
    if _run is not None:
        return _run(cmd, sql, timeout)
    return subprocess.run(cmd, input=sql, capture_output=True, text=True,
                          timeout=timeout)


def _psql(sql: str) -> None:
    # peer auth: become the postgres superuser via the local socket
    r = _exec(["runuser", "-u", "postgres", "--", "psql", "-v", "ON_ERROR_STOP=1",
               "-tAc", sql], sql)
    if r.returncode != 0:
        raise ProvisionError((r.stderr or r.stdout or "psql failed").strip()[:300])


def _mysql(sql: str) -> None:
    # unix_socket auth: root@localhost trusts the local root OS user
    r = _exec(["mariadb", "--protocol=socket", "-u", "root", "-e", sql], sql)
    if r.returncode != 0:
        raise ProvisionError((r.stderr or r.stdout or "mariadb failed").strip()[:300])


def _pg_quote_literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _my_quote_literal(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


# ── public API ──────────────────────────────────────────────────────────────
def provision(engine: str, db_name: str, db_user: str, secret_key: str) -> str:
    """Create <db_name> and <db_user> with a generated password, grant the
    user full rights on that database, store the password hash under
    secret_key, and RETURN THE PLAINTEXT ONCE. The plaintext is never
    persisted and cannot be retrieved again."""
    _require_identifier(db_name, "database name")
    _require_identifier(db_user, "user name")
    pw = generate_password()

    if engine == "postgres":
        # identifiers double-quoted (validated charset makes this safe);
        # password as a quoted literal.
        _psql(f'CREATE DATABASE "{db_name}";')
        try:
            _psql(f'CREATE USER "{db_user}" WITH PASSWORD {_pg_quote_literal(pw)};')
            _psql(f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{db_user}";')
            # PG15+: schema public is not writable by default — grant it
            _psql(f'ALTER DATABASE "{db_name}" OWNER TO "{db_user}";')
        except ProvisionError:
            _psql(f'DROP DATABASE IF EXISTS "{db_name}";')   # rollback partial
            raise
    elif engine == "mysql":
        _mysql(f"CREATE DATABASE `{db_name}`;")
        try:
            _mysql(f"CREATE USER `{db_user}`@'localhost' "
                   f"IDENTIFIED BY {_my_quote_literal(pw)};")
            _mysql(f"GRANT ALL PRIVILEGES ON `{db_name}`.* "
                   f"TO `{db_user}`@'localhost';")
            _mysql("FLUSH PRIVILEGES;")
        except ProvisionError:
            _mysql(f"DROP DATABASE IF EXISTS `{db_name}`;")
            raise
    else:
        raise ProvisionError(f"unknown engine {engine!r}")

    store_password_hash(secret_key, pw)
    return pw


def reset_password(engine: str, db_user: str, secret_key: str) -> str:
    """Generate a new password for an existing managed user, apply it in the
    engine, re-hash it, and RETURN THE PLAINTEXT ONCE."""
    _require_identifier(db_user, "user name")
    pw = generate_password()
    if engine == "postgres":
        _psql(f'ALTER USER "{db_user}" WITH PASSWORD {_pg_quote_literal(pw)};')
    elif engine == "mysql":
        _mysql(f"ALTER USER `{db_user}`@'localhost' "
               f"IDENTIFIED BY {_my_quote_literal(pw)};")
        _mysql("FLUSH PRIVILEGES;")
    else:
        raise ProvisionError(f"unknown engine {engine!r}")
    store_password_hash(secret_key, pw)
    return pw


def deprovision(engine: str, db_name: str, db_user: str, secret_key: str) -> None:
    """Drop the database and user, and forget the stored secret. Idempotent:
    IF EXISTS everywhere so a partially-created DB still cleans up."""
    _require_identifier(db_name, "database name")
    _require_identifier(db_user, "user name")
    if engine == "postgres":
        _psql(f'DROP DATABASE IF EXISTS "{db_name}";')
        _psql(f'DROP USER IF EXISTS "{db_user}";')
    elif engine == "mysql":
        _mysql(f"DROP DATABASE IF EXISTS `{db_name}`;")
        _mysql(f"DROP USER IF EXISTS `{db_user}`@'localhost';")
        _mysql("FLUSH PRIVILEGES;")
    else:
        raise ProvisionError(f"unknown engine {engine!r}")
    forget_secret(secret_key)
