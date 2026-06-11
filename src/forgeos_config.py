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


class ForgeOSConfig(BaseModel):
    """Root config document. Grows one section per service as v2 expands."""

    version: int = 1
    domain: str = "nas.local"
    samba: SambaConfig = Field(default_factory=SambaConfig)
    nginx: NginxConfig = Field(default_factory=NginxConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    wireguard: WireGuardConfig = Field(default_factory=WireGuardConfig)
    nfs: NfsConfig = Field(default_factory=NfsConfig)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)
    apps: list[InstalledApp] = Field(default_factory=list)

    @field_validator("apps")
    @classmethod
    def _unique_apps(cls, v: list[InstalledApp]) -> list[InstalledApp]:
        ids = [a.id for a in v]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate app ids: {sorted(dupes)}")
        return v


def load(path: Path | None = None) -> ForgeOSConfig:
    """Load + validate the config DB. Returns defaults if it doesn't exist."""
    p = path or CONFIG_PATH
    if not p.exists():
        return ForgeOSConfig()
    data = json.loads(p.read_text())
    return ForgeOSConfig.model_validate(data)


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
