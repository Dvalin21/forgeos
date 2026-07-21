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
import ipaddress
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CONFIG_PATH = Path(os.environ.get("FORGEOS_CONFIG_JSON", "/etc/forgeos/config.json"))

# ---------------- Samba ----------------

ShareType = Literal["standard", "timemachine", "public-ro", "database"]
SharePerms = Literal["private", "group", "public"]


class SambaShare(BaseModel):
    name: str
    path: str
    type: ShareType = "standard"
    writable: bool = True
    valid_users: list[str] = Field(default_factory=lambda: ["@users"])
    comment: str = ""
    # --- advanced options (each surfaced as a plain checkbox/dropdown in the
    #     UI; complexity hidden, nothing behind an "advanced" toggle) ---------
    browseable: bool = False          # NEVER auto-visible — user must opt in
    guest_ok: bool = False            # allow access with no login
    hide_dot_files: bool = True       # hide dotfiles (Samba's own default)
    recycle_bin: bool = False         # deletes recoverable from a .recycle dir
    force_user: str = ""              # all files owned by this user ("" = off)
    force_group: str = ""             # all files owned by this group ("" = off)
    permissions: SharePerms = "group"  # create/dir mask preset
    write_list: list[str] = Field(default_factory=list)  # rw users on a ro share

    @field_validator("force_user", "force_group")
    @classmethod
    def _valid_principal(cls, v: str) -> str:
        v = v.strip()
        if v and any(c in v for c in ' \t\n\r"\\[]/'):
            raise ValueError(f"invalid user/group name: {v!r}")
        return v

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
    # --- advanced proxy options (N1) ---
    # Every default reproduces the prior hardcoded behaviour, so a config
    # written before these existed renders byte-for-byte the same vhost.
    upstream_host: str = "127.0.0.1"
    upstream_scheme: Literal["http", "https"] = "http"
    websocket: bool = False
    http2: bool = True                       # was hardcoded `http2 on`
    force_ssl: bool = True                    # :80 redirects to :443 (else also serves :80)
    hsts: bool = True                         # was hardcoded HSTS header
    block_common_exploits: bool = False
    gzip: bool = False
    client_max_body_size: str = "1m"          # nginx default
    proxy_read_timeout: int = 60              # seconds (nginx default)
    allow_ips: list[str] = Field(default_factory=list)   # allowlist (else deny all)
    deny_ips: list[str] = Field(default_factory=list)    # blocklist (ignored if allow_ips set)
    custom_snippet: str = ""                  # raw nginx, inside server{} (admin escape hatch)
    auth: bool = False
    # "" = use a cert named after `domain` (per-host, back-compat). Set to a
    # cert directory name under /etc/letsencrypt/live/ to SHARE one cert
    # across vhosts — e.g. a "*.example.com" wildcard issued once, stored at
    # live/example.com/, selected here as "example.com" by every subdomain.
    cert_name: str = ""

    @field_validator("cert_name")
    @classmethod
    def _valid_cert_name(cls, v: str) -> str:
        # Becomes a filesystem path segment — reject traversal/separators.
        v = v.strip()
        if v and (v in (".", "..") or any(c in v for c in "/\\\0")):
            raise ValueError(f"invalid cert_name: {v!r}")
        return v

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = v.strip()
        if not v or any(c in v for c in ' /"\\'):
            raise ValueError(f"invalid vhost name: {v!r}")
        return v

    @field_validator("domain")
    @classmethod
    def _valid_domain(cls, v: str) -> str:
        # Rendered into `server_name` — reject anything that could break out of
        # the directive or inject nginx config. Wildcards (*) are allowed.
        v = v.strip()
        if not v or any(c in v for c in ' \t\n\r;{}#"\\'):
            raise ValueError(f"invalid domain: {v!r}")
        return v

    @field_validator("upstream_port")
    @classmethod
    def _valid_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port out of range: {v}")
        return v

    @field_validator("upstream_host")
    @classmethod
    def _valid_host(cls, v: str) -> str:
        v = v.strip()
        # Hostname or IP. Reject anything that could break out of the upstream
        # directive (whitespace, nginx block/terminator chars).
        if not v or any(c in v for c in ' \t\n;{}#"\\'):
            raise ValueError(f"invalid upstream host: {v!r}")
        return v

    @field_validator("client_max_body_size")
    @classmethod
    def _valid_body_size(cls, v: str) -> str:
        v = v.strip()
        # nginx size: digits with optional k/m/g suffix (0 = unlimited)
        if not re.fullmatch(r"\d+[kKmMgG]?", v):
            raise ValueError(f"invalid client_max_body_size: {v!r} (e.g. '1m', '100m', '0')")
        return v

    @field_validator("proxy_read_timeout")
    @classmethod
    def _valid_timeout(cls, v: int) -> int:
        if not (1 <= v <= 3600):
            raise ValueError(f"proxy_read_timeout out of range (1-3600s): {v}")
        return v

    @field_validator("allow_ips", "deny_ips")
    @classmethod
    def _valid_ips(cls, v: list[str]) -> list[str]:
        out = []
        for item in v:
            item = item.strip()
            if not item:
                continue
            try:
                # accept both single IPs and CIDR ranges
                ipaddress.ip_network(item, strict=False)
            except ValueError:
                raise ValueError(f"invalid IP/CIDR: {item!r}")
            out.append(item)
        return out


class DnsProvider(BaseModel):
    """DNS-01 credentials for ONE provider, shared by every domain on it.
    code = a lego provider code (porkbun, cloudflare, ...). creds_path points
    at a 0600 ini the API owns. Same provider + more domains = reuse this, no
    re-entry; a different provider = a separate entry (separate creds file)."""
    code: str
    creds_path: str

    @field_validator("code")
    @classmethod
    def _valid_code(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or not __import__("re").fullmatch(r"[a-z0-9]+", v):
            raise ValueError(f"invalid provider code: {v!r}")
        return v


class Domain(BaseModel):
    """A domain ForgeOS manages a cert for. Adding it issues the cert; vhosts
    whose hostname is at or under `name` inherit this cert automatically.
      wildcard=True  -> cert covers name + *.name (every subdomain)
      wildcard=False -> cert covers just name (the bare domain)
    provider is a DnsProvider.code (which holds the creds)."""
    name: str
    provider: str                              # DnsProvider.code
    wildcard: bool = True

    @field_validator("name")
    @classmethod
    def _valid_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if not __import__("re").fullmatch(r"[a-z0-9][a-z0-9.\-]{0,251}[a-z0-9]", v):
            raise ValueError(f"invalid domain: {v!r}")
        return v


class ExternalCert(BaseModel):
    """A cert ForgeOS did NOT issue — points at PEM files an external tool
    (e.g. a porkbun-certbot container) drops in. Recorded so it appears in
    the cert list and is selectable by vhosts, exactly like an issued cert."""
    name: str                                  # dir/label, selectable as vhost.cert_name
    fullchain_path: str
    privkey_path: str

    @field_validator("name")
    @classmethod
    def _valid(cls, v: str) -> str:
        v = v.strip()
        if not v or v in (".", "..") or any(c in v for c in "/\\\0 "):
            raise ValueError(f"invalid cert name: {v!r}")
        return v


class NginxConfig(BaseModel):
    enabled: bool = True
    vhosts: list[NginxVhost] = Field(default_factory=list)
    external_certs: list[ExternalCert] = Field(default_factory=list)
    dns_providers: list[DnsProvider] = Field(default_factory=list)
    domains: list[Domain] = Field(default_factory=list)

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



class FirewallRule(BaseModel):
    """One ufw rule. port may be a single port or a range "a:b"; ranges
    require an explicit proto (ufw constraint). from_ip: 'any', an IP, or a
    CIDR. family follows the legacy API semantics (both|ipv4|ipv6)."""
    port: str
    proto: Literal["any", "tcp", "udp"] = "any"
    action: Literal["allow", "deny", "reject", "limit"] = "allow"
    from_ip: str = "any"
    family: Literal["both", "ipv4", "ipv6"] = "both"
    comment: str = ""

    @field_validator("port")
    @classmethod
    def _valid_port(cls, v: str) -> str:
        v = v.strip()
        m = re.match(r"^(\d{1,5})(?::(\d{1,5}))?$", v)
        if not m:
            raise ValueError(f"invalid port: {v!r}")
        lo = int(m.group(1)); hi = int(m.group(2)) if m.group(2) else lo
        if not (1 <= lo <= 65535 and 1 <= hi <= 65535 and lo <= hi):
            raise ValueError(f"port out of range: {v!r}")
        return v

    @field_validator("from_ip")
    @classmethod
    def _valid_from(cls, v: str) -> str:
        v = v.strip()
        if v in ("", "any"):
            return "any"
        import ipaddress
        ipaddress.ip_network(v, strict=False)   # raises on garbage
        return v

    @field_validator("comment")
    @classmethod
    def _valid_comment(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[A-Za-z0-9 ._-]{0,60}$", v):
            raise ValueError("comment: letters, digits, spaces, ._- only (max 60)")
        return v

    @model_validator(mode="after")
    def _range_needs_proto(self):
        if ":" in self.port and self.proto == "any":
            raise ValueError("port ranges require an explicit proto (tcp or udp)")
        if self.from_ip != "any":
            import ipaddress
            fam = "ipv6" if ipaddress.ip_network(self.from_ip, strict=False).version == 6 else "ipv4"
            if self.family == "both":
                self.family = fam
            elif self.family != fam:
                raise ValueError(f"family {self.family} does not match address {self.from_ip}")
        return self


class FirewallConfig(BaseModel):
    """Firewall intent — config-DB is the source of truth; the ufw generator
    converges the live firewall to this."""
    enabled: bool = False
    default_incoming: Literal["deny", "allow", "reject"] = "deny"
    default_outgoing: Literal["deny", "allow", "reject"] = "allow"
    logging: Literal["off", "low", "medium", "high", "full"] = "low"
    rules: list[FirewallRule] = Field(default_factory=list)


class Fail2banConfig(BaseModel):
    """fail2ban tunables + per-jail switches. Rendered into jail.d/forgeos.conf
    by the security generator; the forgeos-api jail reads /var/log/forgeos/auth.log."""
    enabled: bool = True
    bantime: str = "1h"
    findtime: str = "10m"
    maxretry: int = 5
    jail_sshd: bool = True
    jail_nginx: bool = True
    jail_forgeos: bool = True
    jail_recidive: bool = True

    @field_validator("bantime", "findtime")
    @classmethod
    def _duration(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^\d{1,6}[smhdw]?$", v):
            raise ValueError(f"invalid duration: {v!r} (e.g. 600, 10m, 1h, 1d)")
        return v

    @field_validator("maxretry")
    @classmethod
    def _retry(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("maxretry must be 1-100")
        return v



class UpdatesConfig(BaseModel):
    """Unattended security updates (Debian unattended-upgrades). Debian's
    default origin set is security-only; we surface reboot behavior."""
    enabled: bool = True
    auto_reboot: bool = False
    reboot_time: str = "02:00"

    @field_validator("reboot_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v.strip()):
            raise ValueError(f"reboot_time must be HH:MM: {v!r}")
        return v.strip()


class SecurityConfig(BaseModel):
    profile: SecurityProfile = "medium"   # deprecated: informational only since P3
    lan_cidr: str = "10.0.0.0/24"
    fail2ban: Fail2banConfig = Field(default_factory=Fail2banConfig)

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
    # "" = resolve the default-route NIC at render time. A hardcoded "eth0"
    # default silently rendered dead NAT/forward rules on any box with
    # predictable interface names (ens18, enp3s0, ...).
    egress_nic: str = ""
    # Public host/IP clients dial (port comes from listen_port). "" = unset;
    # add-peer refuses until set so client configs never ship a placeholder.
    endpoint: str = ""
    peers: list[WireGuardPeer] = Field(default_factory=list)

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return v
        try:                                   # IP literal (v4/v6) is fine
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
        # RFC 1123 hostname: per-label check, same discipline as certbot fix
        label = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        if len(v) > 253 or not re.fullmatch(rf"{label}(\.{label})*", v):
            raise ValueError(f"invalid endpoint host: {v!r}")
        return v

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


# ── Data Connect ────────────────────────────────────────────────────────────
# Manages databases for multiple clients. Two kinds:
#   file-based (ElevateDB/Access/SQLite/... — files on a Samba share, protected
#     by SMB share modes: oplocks off, strict locking on)
#   server (postgres/mysql — run locally on native ports, own MVCC concurrency;
#     data dir MUST be local, never on a share)
class DockerConfig(BaseModel):
    """Docker-surface settings. apps_root is the default host directory for
    per-app bind mounts ({apps_root}/{app}/...) — the appdata convention."""
    apps_root: str = "/srv/apps"

    @field_validator("apps_root")
    @classmethod
    def _abs_root(cls, v: str) -> str:
        # Validate what's ALLOWED, not what's forbidden — a denylist of "bad"
        # paths can't be exhaustive and is trivially bypassed (/etc/../etc
        # normalises to /etc, and /bin /lib /sys were never on the list).
        # Resolve first (collapses .. and symlinks), then require the result to
        # sit under a sane app-data prefix.
        raw = (v or "").strip()
        if not raw.startswith("/"):
            raise ValueError("apps_root must be an absolute path")
        resolved = os.path.normpath(raw).rstrip("/") or "/"
        allowed_prefixes = ("/srv", "/opt", "/mnt", "/media", "/home", "/data",
                            "/var/lib")
        # allow an allowed prefix itself, or any path strictly beneath it
        if not any(resolved == p or resolved.startswith(p + "/")
                   for p in allowed_prefixes):
            raise ValueError(
                f"{resolved} is not a permitted app-data location — use a path "
                f"under one of: {', '.join(allowed_prefixes)}")
        return resolved


DataConnectKind = Literal["file", "postgres", "mysql"]


# File-DB extensions -> the app/engine family they belong to. Single source of
# truth for (a) auto-tagging an imported directory and (b) building the per-share
# `veto oplock files` pattern in the Samba generator.
DB_FAMILIES: dict[str, str] = {
    ".edb": "ElevateDB", ".edbt": "ElevateDB", ".edbi": "ElevateDB", ".edbl": "ElevateDB",
    ".db": "DBISAM", ".px": "Paradox", ".mb": "Paradox", ".val": "Paradox",
    ".nxd": "NexusDB", ".nxi": "NexusDB", ".nxl": "NexusDB",
    ".dbf": "dBase/FoxPro", ".cdx": "dBase/FoxPro", ".fpt": "dBase/FoxPro", ".idx": "dBase/FoxPro",
    ".mdb": "Access", ".accdb": "Access", ".ldb": "Access", ".laccdb": "Access",
    ".sqlite": "SQLite", ".sqlite3": "SQLite", ".sqlite-wal": "SQLite",
    ".fdb": "Firebird", ".gdb": "Firebird",
    ".dat": "TurboDB", ".tdb": "TurboDB", ".tdx": "TurboDB",
}


def db_family_extensions(family: str) -> list[str]:
    """Extensions for a DB family, sorted. [] for unknown/empty family."""
    return sorted(ext for ext, fam in DB_FAMILIES.items() if fam == family)


class ManagedDatabase(BaseModel):
    name: str                                  # unique id / share or db name
    kind: DataConnectKind
    data_path: str                             # dir (file) or data dir (server)
    app: str = ""                              # which app owns it (free tag)
    db_type: str = ""                          # detected file family, or engine
    port: int = 0                              # server DBs: 5432/3306; 0 = file
    comment: str = ""
    # Managed provisioning (server DBs only). When ForgeOS created the database
    # and its user, it can also drop them. The password is show-once at
    # creation; only a bcrypt hash lives in /etc/forgeos/db-secrets.json —
    # never in this config, never recoverable, resettable.
    managed: bool = False
    db_name: str = ""                          # database created inside engine
    db_user: str = ""                          # user created inside engine

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        v = v.strip()
        if not v or any(c in v for c in ' \t\n\r"\\[]/'):
            raise ValueError(f"invalid database name: {v!r}")
        return v

    @field_validator("data_path")
    @classmethod
    def _abs(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"data path must be absolute: {v!r}")
        return v


class DataConnectConfig(BaseModel):
    enabled: bool = False
    broadcast: bool = True                     # mDNS/Avahi announce
    databases: list[ManagedDatabase] = Field(default_factory=list)

    @field_validator("databases")
    @classmethod
    def _unique(cls, v: list[ManagedDatabase]) -> list[ManagedDatabase]:
        names = [d.name.lower() for d in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate database names: {sorted(dupes)}")
        return v


class TogglesConfig(BaseModel):
    """Base features that are install/uninstall toggles (not always-on).

    Coral + GPU are also hardware-gated: enabling them only does anything if
    the hardware is present. Data Connect is a pure software toggle.
    """

    data_connect: bool = False
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


class AuthConfig(BaseModel):
    """Authentication policy. Currently just the new-account 2FA mandate:
    when on, every user created afterward is flagged totp_required, and login
    signals enrollment_required until they enroll (enforced in the UI)."""

    require_totp_new_users: bool = False


SCHEMA_VERSION = 11


class ForgeOSConfig(BaseModel):
    """Root config document. Grows one section per service as v2 expands."""

    version: int = SCHEMA_VERSION
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
    data_connect: DataConnectConfig = Field(default_factory=DataConnectConfig)
    docker: DockerConfig = Field(default_factory=DockerConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    firewall: FirewallConfig = Field(default_factory=FirewallConfig)
    updates: UpdatesConfig = Field(default_factory=UpdatesConfig)
    wireguard: WireGuardConfig = Field(default_factory=WireGuardConfig)
    nfs: NfsConfig = Field(default_factory=NfsConfig)
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)
    apps: list[InstalledApp] = Field(default_factory=list)
    toggles: TogglesConfig = Field(default_factory=TogglesConfig)
    osbackup: OsBackupConfig = Field(default_factory=OsBackupConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    @field_validator("apps")
    @classmethod
    def _unique_apps(cls, v: list[InstalledApp]) -> list[InstalledApp]:
        ids = [a.id for a in v]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate app ids: {sorted(dupes)}")
        return v




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


def _migrate_v2_to_v3(data: dict) -> dict:
    """v3 adds the `auth` policy block (require_totp_new_users). No existing
    data needs transforming — pydantic fills the default — but bump the
    version so the schema marker stays accurate and load_and_upgrade persists
    it. Idempotent: an already-present auth block is preserved."""
    data.setdefault("auth", {})
    data["version"] = 3
    return data


def _migrate_v3_to_v4(data: dict) -> dict:
    """v4 expands NginxVhost with advanced proxy options (upstream host/scheme,
    http2/force_ssl/hsts/gzip toggles, body size, timeouts, IP allow/deny,
    custom snippet). Additive — existing vhosts get defaults that reproduce the
    prior hardcoded behaviour — so no data transform, just bump the marker."""
    data["version"] = 4
    return data


# version N -> N+1 migrators, applied in order until data reaches SCHEMA_VERSION

def _migrate_v4_to_v5(data: dict) -> dict:
    """v5: firewall block (config-DB-owned ufw). Additive."""
    data.setdefault("firewall", {})
    data["version"] = 5
    return data


def _migrate_v5_to_v6(data: dict) -> dict:
    """v6: fail2ban tunables under security. Additive."""
    data.setdefault("security", {}).setdefault("fail2ban", {})
    data["version"] = 6
    return data


def _migrate_v6_to_v7(data: dict) -> dict:
    """v7: unattended-updates block. Additive."""
    data.setdefault("updates", {})
    data["version"] = 7
    return data

def _migrate_v8_to_v9(data: dict) -> dict:
    """v9: ForgeFileDB became Data Connect. Rename the toggle; the old
    file-locking daemon is gone (its advisory locks never worked
    cross-protocol). Existing tracked dirs, if any, are not auto-migrated —
    the model changed shape — but the toggle carries over."""
    tog = data.setdefault("toggles", {})
    if "forgefiledb" in tog:
        tog["data_connect"] = tog.pop("forgefiledb")
    data["version"] = 9
    return data


def _migrate_v9_to_v10(data: dict) -> dict:
    """v10: docker block (apps_root for per-app bind mounts). Additive."""
    data.setdefault("docker", {})
    data["version"] = 10
    return data


def _migrate_v10_to_v11(data: dict) -> dict:
    """v11: managed/db_name/db_user on tracked databases. Purely additive —
    the model defaults (managed=False) make every existing entry valid as an
    untracked/tracker-only database."""
    data["version"] = 11
    return data


def _migrate_v7_to_v8(data: dict) -> dict:
    """v8: egress_nic "eth0" was a blind default, never a user choice — reset
    to "" (auto-detect default-route NIC at render time)."""
    wg = data.setdefault("wireguard", {})
    if wg.get("egress_nic", "") == "eth0":
        wg["egress_nic"] = ""
    data["version"] = 8
    return data


_MIGRATIONS = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
    5: _migrate_v5_to_v6,
    6: _migrate_v6_to_v7,
    7: _migrate_v7_to_v8,
    8: _migrate_v8_to_v9,
    9: _migrate_v9_to_v10,
    10: _migrate_v10_to_v11,
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
