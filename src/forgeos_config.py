"""ForgeOS v2 configuration database.

Single source of truth for all service configuration. Stored as a single
JSON document (human-inspectable, trivially backed up, no daemon). Validated
by pydantic models so invalid config is rejected at WRITE time rather than
discovered at render time.

Service generators read from this; the web API writes to it and then calls
the generator to render config files + reload services. This replaces the
old pattern of bash modules writing /etc files imperatively via heredocs.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CONFIG_PATH = Path(os.environ.get("FORGEOS_CONFIG_JSON", "/etc/forgeos/config.json"))

# ---------------- Samba ----------------

ShareType = Literal["standard", "timemachine", "public-ro", "database"]


class SambaShare(BaseModel):
    name: str
    path: str
    type: ShareType = "standard"
    writable: bool = True
    valid_users: list[str] = Field(default_factory=lambda: ["@users"])
    comment: str = ""

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("share name cannot be empty")
        if any(c in v for c in '[]/"\\'):
            raise ValueError(f"invalid characters in share name: {v!r}")
        return v

    @field_validator("path")
    @classmethod
    def _abs_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"share path must be absolute: {v!r}")
        return v


class SambaConfig(BaseModel):
    enabled: bool = True
    workgroup: str = "FORGEOS"
    server_string: str = "ForgeOS NAS"
    shares: list[SambaShare] = Field(default_factory=list)

    @field_validator("shares")
    @classmethod
    def _unique_names(cls, v: list[SambaShare]) -> list[SambaShare]:
        names = [s.name.lower() for s in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate share names: {sorted(dupes)}")
        return v


# ---------------- nginx ----------------


class NginxVhost(BaseModel):
    name: str
    domain: str
    upstream_port: int
    websocket: bool = False
    auth: bool = False

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = v.strip()
        if not v or any(c in v for c in ' /"\\'):
            raise ValueError(f"invalid vhost name: {v!r}")
        return v

    @field_validator("upstream_port")
    @classmethod
    def _valid_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port out of range: {v}")
        return v


class NginxConfig(BaseModel):
    enabled: bool = True
    vhosts: list[NginxVhost] = Field(default_factory=list)

    @field_validator("vhosts")
    @classmethod
    def _unique(cls, v: list[NginxVhost]) -> list[NginxVhost]:
        names = [x.name.lower() for x in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate vhost names: {sorted(dupes)}")
        return v


# ---------------- security ----------------

SecurityProfile = Literal["low", "medium", "high"]


class SecurityConfig(BaseModel):
    profile: SecurityProfile = "medium"
    lan_cidr: str = "10.0.0.0/24"

    @field_validator("lan_cidr")
    @classmethod
    def _cidr(cls, v: str) -> str:
        if "/" not in v:
            raise ValueError(f"lan_cidr must be CIDR notation: {v!r}")
        return v


# ---------------- WireGuard ----------------


class WireGuardPeer(BaseModel):
    name: str
    public_key: str
    address: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v or any(c in v for c in ' /"\\[]'):
            raise ValueError(f"invalid peer name: {v!r}")
        return v

    @field_validator("address")
    @classmethod
    def _addr(cls, v: str) -> str:
        if "/" not in v:
            v = v + "/32"
        return v


class WireGuardConfig(BaseModel):
    enabled: bool = False
    interface: str = "wg0"
    server_address: str = "10.10.0.1"
    listen_port: int = 51820
    subnet: str = "10.10.0.0/24"
    egress_nic: str = "eth0"
    peers: list[WireGuardPeer] = Field(default_factory=list)

    @field_validator("listen_port")
    @classmethod
    def _port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port out of range: {v}")
        return v

    @field_validator("peers")
    @classmethod
    def _unique_peers(cls, v: list[WireGuardPeer]) -> list[WireGuardPeer]:
        names = [p.name.lower() for p in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate peer names: {sorted(dupes)}")
        return v


# ---------------- NFS ----------------

NfsExportType = Literal["rw", "ro", "public", "backup"]


class NfsExport(BaseModel):
    path: str
    type: NfsExportType = "rw"

    @field_validator("path")
    @classmethod
    def _abs(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"export path must be absolute: {v!r}")
        return v


class NfsConfig(BaseModel):
    enabled: bool = False
    nas_root: str = "/srv/nas"
    lan_cidr: str = "10.0.0.0/24"
    exports: list[NfsExport] = Field(default_factory=list)

    @field_validator("exports")
    @classmethod
    def _unique_paths(cls, v: list[NfsExport]) -> list[NfsExport]:
        paths = [e.path for e in v]
        dupes = {p for p in paths if paths.count(p) > 1}
        if dupes:
            raise ValueError(f"duplicate export paths: {sorted(dupes)}")
        return v


# ---------------- SMTP ----------------


class SmtpConfig(BaseModel):
    """Outbound SMTP for notifications (errors, service/app down).

    A NOTIFICATION sender, not a mail server. Password is NOT stored here;
    it lives in the keystore (see forgeos_smtp).
    """

    enabled: bool = False
    host: str = ""
    port: int = 587
    use_tls: bool = True
    use_ssl: bool = False
    username: str = ""
    from_addr: str = ""
    to_addrs: list[str] = Field(default_factory=list)

    @field_validator("port")
    @classmethod
    def _port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port out of range: {v}")
        return v

    @field_validator("to_addrs")
    @classmethod
    def _addrs(cls, v: list[str]) -> list[str]:
        for a in v:
            if "@" not in a:
                raise ValueError(f"invalid email address: {a!r}")
        return v


# ---------------- root ----------------


class InstalledApp(BaseModel):
    """An app installed from the catalog. Recorded in the config DB so its
    port stays stable and its nginx vhost can be derived."""

    id: str
    version: str = ""
    webui_port: int
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9][a-z0-9_-]*$", v):
            raise ValueError(f"invalid app id: {v!r}")
        return v

    @field_validator("webui_port")
    @classmethod
    def _port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port out of range: {v}")
        return v


class TogglesConfig(BaseModel):
    """Base features that are install/uninstall toggles (not always-on).

    Coral + GPU are also hardware-gated: enabling them only does anything if
    the hardware is present. ForgeFileDB is a pure software toggle.
    """

    forgefiledb: bool = False
    coral: bool = False
    gpu: bool = False


class OsBackupConfig(BaseModel):
    """Bare-metal disaster recovery for ForgeOS ITSELF, via ReaR.

    Produces a bootable rescue image + a full system archive so the box can
    be rebuilt on the same or new hardware. Distinct from data-pool backups
    (Restic/btrfs) and from client backups (UrBackup).
    """

    enabled: bool = False
    output: Literal["ISO", "USB"] = "ISO"
    # Where the rescue image + archive land. MUST be a separate filesystem
    # from root — ReaR refuses otherwise. With a dedicated backup disk this
    # is satisfied by construction.
    backup_path: str = "/mnt/backup/osbackup"
    schedule: str = "weekly"           # systemd OnCalendar value
    cloud_sync: bool = False           # also push the archive via Rclone
    cloud_remote: str = ""             # rclone remote name (if cloud_sync)

    @field_validator("backup_path")
    @classmethod
    def _abs_not_root(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"backup_path must be absolute: {v!r}")
        # Guard the ReaR "not on root fs" rule at the schema level: refuse
        # obvious root-fs paths. (Real separate-fs check happens at apply.)
        bad = ("/", "/root", "/etc", "/var", "/usr", "/home", "/boot")
        if v.rstrip("/") in bad or v.rstrip("/") == "":
            raise ValueError(
                f"backup_path {v!r} looks like the root filesystem; ReaR "
                "requires a separate filesystem (use the dedicated backup disk)"
            )
        return v

    @field_validator("schedule")
    @classmethod
    def _sched(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("schedule cannot be empty")
        return v

    @field_validator("cloud_remote")
    @classmethod
    def _remote(cls, v: str, info) -> str:
        return v


class StoragePool(BaseModel):
    """A btrfs data pool. Declarative record of an existing pool — pool
    CREATION is a guarded, one-time destructive action (forgeos_diskprep),
    NOT something regenerated idempotently. This just records what exists so
    shares/exports can reference the mountpoint and fstab can mount it.
    btrfs native raid for now; swappable for LHSR later.
    """
    name: str
    raid_level: str = "single"          # single|raid0|raid1|raid10|raid5|raid6
    devices: list[str] = Field(default_factory=list)  # stable /dev/disk/by-id/*
    mountpoint: str = ""                # default /srv/nas/<name> if empty
    uuid: str = ""                      # btrfs FS UUID — mount by THIS, not /dev

    @field_validator("name")
    @classmethod
    def _valid_pool_name(cls, v: str) -> str:
        import re as _re
        if not _re.fullmatch(r"[A-Za-z0-9_-]{2,}", v or ""):
            raise ValueError(f"invalid pool name: {v!r}")
        return v

    def resolved_mountpoint(self) -> str:
        return self.mountpoint or f"/srv/nas/{self.name}"


class StorageConfig(BaseModel):
    pools: list[StoragePool] = Field(default_factory=list)

    @field_validator("pools")
    @classmethod
    def _unique_pool_names(cls, v: list["StoragePool"]) -> list["StoragePool"]:
        names = [p.name.lower() for p in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate pool names: {sorted(dupes)}")
        return v


class NamingConfig(BaseModel):
    """The three distinct names a ForgeOS box has. Conflating them is a trap:
    they coincide on a simple LAN box but DIVERGE the moment you add a mail
    server or public reverse-proxy host.

    - system_hostname: what the OS calls itself (hostnamectl). Local identity;
      Samba NetBIOS, logs, SSH key it. ForgeOS NEVER silently changes this.
    - lan_name: how you REACH the box on the LAN — the mDNS/.local discovery
      name. Defaults to '<system_hostname>.local' so avahi advertises it with
      zero config. This is what the local web UI uses.
    - public_fqdn: a globally-resolvable, DNS-backed name. EMPTY until you own
      a real domain. Required for real TLS (reverse-proxy manager) and for a
      future mail server's MX/PTR/HELO. NEVER a .local name — mail and public
      certs cannot use mDNS. Set this without touching hostname or lan_name.
    """
    system_hostname: str = ""      # "" = use the OS's current hostname as-is
    lan_name: str = ""             # "" = derive '<hostname>.local'
    public_fqdn: str = ""          # "" = none yet (reverse-proxy / mail set it)


class ForgeOSConfig(BaseModel):
    """Root config document. Grows one section per service as v2 expands."""

    version: int = 2
    # `domain` is the legacy single-name field, kept for compatibility with
    # existing call sites (installer, nginx generator, CLI). The authoritative
    # model is `naming` (three-names). `domain` mirrors naming.lan_name for the
    # LAN-facing case. Migration runner (V-012, Phase 3) will fold call sites
    # onto `naming` and retire this.
    domain: str = "nas.local"
    naming: NamingConfig = Field(default_factory=NamingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    samba: SambaConfig = Field(default_factory=SambaConfig)
    nginx: NginxConfig = Field(default_factory=NginxConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    wireguard: WireGuardConfig = Field(default_factory=WireGuardConfig)
    nfs: NfsConfig = Field(default_factory=NfsConfig)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)
    apps: list[InstalledApp] = Field(default_factory=list)
    toggles: TogglesConfig = Field(default_factory=TogglesConfig)
    osbackup: OsBackupConfig = Field(default_factory=OsBackupConfig)

    @field_validator("apps")
    @classmethod
    def _unique_apps(cls, v: list[InstalledApp]) -> list[InstalledApp]:
        ids = [a.id for a in v]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate app ids: {sorted(dupes)}")
        return v


SCHEMA_VERSION = 2


def _migrate_v1_to_v2(data: dict) -> dict:
    """v1 had a single `domain` and no `naming` block. Populate the three-names
    model from it: lan_name = the old domain, system_hostname derived from the
    domain's first label (best effort — real hostname reconciled at next
    install/apply), public_fqdn empty. Idempotent.
    """
    domain = data.get("domain", "") or "nas.local"
    naming = data.get("naming") or {}
    if not naming.get("lan_name"):
        naming["lan_name"] = domain
    if not naming.get("system_hostname"):
        # the label before the first dot is the best guess at the hostname
        naming["system_hostname"] = domain.split(".")[0]
    naming.setdefault("public_fqdn", "")
    data["naming"] = naming
    data["version"] = 2
    return data


# version N -> N+1 migrators, applied in order until data reaches SCHEMA_VERSION
_MIGRATIONS = {
    1: _migrate_v1_to_v2,
}


def migrate(data: dict) -> dict:
    """Bring a raw config dict up to the current schema version by applying
    each version migrator in sequence. A dict with no version is treated as
    v1 (the first schema that shipped without an explicit bump)."""
    v = int(data.get("version", 1))
    if v > SCHEMA_VERSION:
        raise ValueError(
            f"config schema v{v} is newer than this ForgeOS (v{SCHEMA_VERSION}); "
            "downgrade is not supported — upgrade ForgeOS instead"
        )
    while v < SCHEMA_VERSION:
        migrator = _MIGRATIONS.get(v)
        if migrator is None:
            raise ValueError(f"no migration from schema version {v}")
        data = migrator(data)
        new_v = int(data.get("version", v))
        if new_v <= v:
            raise ValueError(f"migration from v{v} did not advance version")
        v = new_v
    return data


def load(path: Path | None = None) -> ForgeOSConfig:
    """Load + validate the config DB. Returns defaults if it doesn't exist.
    Older-schema configs are migrated up before validation (V-012)."""
    p = path or CONFIG_PATH
    if not p.exists():
        return ForgeOSConfig()
    data = json.loads(p.read_text())
    data = migrate(data)   # no-op if already current; raises if newer-than-code
    return ForgeOSConfig.model_validate(data)


def load_and_upgrade(path: Path | None = None) -> ForgeOSConfig:
    """Like load(), but if the on-disk config was an older schema, PERSIST the
    migrated version back to disk (once). Use this on the installer/apply path
    so an upgraded box's config.json is physically at the current schema.
    Returns defaults (and writes nothing) if no config exists yet.
    """
    p = path or CONFIG_PATH
    if not p.exists():
        return ForgeOSConfig()
    raw = json.loads(p.read_text())
    needed = int(raw.get("version", 1)) < SCHEMA_VERSION
    cfg = load(p)
    if needed:
        save(cfg, p)   # write the upgraded config back, atomically, 0600
    return cfg


def save(cfg: ForgeOSConfig, path: Path | None = None) -> None:
    """Validate + atomically write the config DB (0600)."""
    p = path or CONFIG_PATH
    cfg = ForgeOSConfig.model_validate(cfg.model_dump())
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cfg.model_dump(), indent=2, sort_keys=False)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
