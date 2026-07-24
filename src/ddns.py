"""Dynamic DNS — provider clients and update orchestration.

Keeps a hostname pointed at this machine when the public IP changes.

Protocols implemented (each verified against the provider's own docs rather
than written from memory):

  • dyndns2 — No-IP and DynDNS share one protocol. GET /nic/update with HTTP
    Basic auth and a real User-Agent (the spec requires one; clients without
    it get blocked). Response is text/plain, first token is the code:
    good/nochg/nohost/badauth/notfqdn/abuse/911/...
  • cloudflare — REST v4 with a Bearer token: resolve zone -> resolve the A
    record -> PATCH its content. PATCH, not PUT: PUT replaces the whole
    record (and historically rejected API tokens), while a DDNS update only
    ever changes `content`.
  • duckdns — GET /update?domains=&token=&ip=, replies OK or KO. `domains`
    must be the BARE subdomain; passing the full x.duckdns.org is a
    documented way to get KO back.
  • custom — caller-supplied URL template with {ip} / {hostname}.

Result codes are classified into ok / nochg / fatal / retry because the
scheduler must treat them differently: dyndns2 providers rate-limit or ban
clients that re-send unchanged updates, and a fatal code (bad credentials,
unknown host) means stop and wait for the user rather than retry forever.

Credentials live in the config store at 0600 and are NEVER returned by the
API — same rule as the nginx ACME credentials.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from forgeos_atomic import atomic_write

logger = logging.getLogger("forgeos-api")

DDNS_FILE = Path("/etc/forgeos/ddns.json")

PROVIDERS = ("cloudflare", "noip", "dyndns", "duckdns", "custom")

# dyndns2 endpoints — same protocol, different hosts
_DYNDNS2_HOSTS = {
    "noip": "https://dynupdate.no-ip.com/nic/update",
    "dyndns": "https://members.dyndns.org/nic/update",
}

# The dyndns2 spec requires a descriptive User-Agent; requests without one
# are liable to be refused.
USER_AGENT = "ForgeOS-DDNS/1.0"

_HTTP_TIMEOUT = 15

# dyndns2 codes that mean "stop, a human must fix this"
_DYNDNS2_FATAL = {"badauth", "nohost", "notfqdn", "abuse", "!yours", "!active",
                  "badsys", "numhost"}
# ...and codes that mean "back off and try later"
_DYNDNS2_RETRY = {"911", "dnserr", "servererror"}


@dataclass
class DdnsResult:
    status: str          # "ok" | "nochg" | "fatal" | "retry"
    code: str            # raw provider code, for the UI/logs
    message: str = ""
    ip: str = ""

    @property
    def success(self) -> bool:
        return self.status in ("ok", "nochg")


# ════════════════════════════════════════════════════════════════════
# CONFIG STORE  (0600 — holds credentials)
# ════════════════════════════════════════════════════════════════════
def load() -> dict:
    try:
        return json.loads(DDNS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> None:
    atomic_write(DDNS_FILE, json.dumps(cfg, indent=2), 0o600)


def public_view(cfg: dict) -> dict:
    """What the API is allowed to return — built field by field on purpose.

    Never spread the stored config into a response: the credentials live in
    the same document, and a `**cfg` would leak them the moment someone adds
    a field.
    """
    return {
        "configured": bool(cfg.get("provider")),
        "enabled": bool(cfg.get("enabled", False)),
        "provider": cfg.get("provider", ""),
        "hostname": cfg.get("hostname", ""),
        "interval_minutes": cfg.get("interval_minutes", 5),
        "last_ip": cfg.get("last_ip", ""),
        "last_update": cfg.get("last_update", ""),
        "last_status": cfg.get("last_status", ""),
        "last_message": cfg.get("last_message", ""),
        "has_credentials": bool(cfg.get("credentials")),
    }


# ════════════════════════════════════════════════════════════════════
# PUBLIC IP
# ════════════════════════════════════════════════════════════════════
# ponytail: vpn_api has its own inline public-IP lookup. Not consolidated —
# it also derives the LAN address and the two would need untangling for a
# six-line fetch. Revisit if a third copy appears.
_IP_SERVICES = ("https://checkip.amazonaws.com", "https://api.ipify.org")


def detect_public_ip() -> str:
    """Current public IPv4, or "" if it can't be determined."""
    for url in _IP_SERVICES:
        try:
            raw = urllib.request.urlopen(url, timeout=8).read()
            cand = raw.decode("ascii", "replace").strip()
            ipaddress.ip_address(cand)      # trust boundary: must parse
            return cand
        except (OSError, ValueError):
            continue
    return ""


def _get(url: str, headers: Optional[dict] = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _json_req(url: str, token: str, method: str = "GET",
              payload: Optional[dict] = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            return e.code, {}


# ════════════════════════════════════════════════════════════════════
# PROVIDER CLIENTS
# ════════════════════════════════════════════════════════════════════
def _update_dyndns2(provider: str, hostname: str, creds: dict, ip: str) -> DdnsResult:
    user = creds.get("username", "")
    pw = creds.get("password", "")
    if not user or not pw:
        return DdnsResult("fatal", "nocreds", "Username and password are required.")
    base = _DYNDNS2_HOSTS.get(provider) or creds.get("server") or ""
    if not base:
        return DdnsResult("fatal", "noserver", "No update server for this provider.")
    url = base + "?" + urllib.parse.urlencode({"hostname": hostname, "myip": ip})
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    try:
        _, body = _get(url, {"Authorization": "Basic " + auth})
    except OSError as e:
        return DdnsResult("retry", "network", str(e))
    parts = body.strip().split()
    code = parts[0].lower() if parts else ""
    got = parts[1] if len(parts) > 1 else ""
    if code == "good":
        return DdnsResult("ok", "good", "Hostname updated.", got or ip)
    if code == "nochg":
        return DdnsResult("nochg", "nochg", "Already up to date.", got or ip)
    if code in _DYNDNS2_FATAL:
        return DdnsResult("fatal", code, _DYNDNS2_MESSAGES.get(code, body.strip()[:120]))
    if code in _DYNDNS2_RETRY:
        return DdnsResult("retry", code, _DYNDNS2_MESSAGES.get(code, body.strip()[:120]))
    return DdnsResult("retry", code or "unknown", body.strip()[:120])


_DYNDNS2_MESSAGES = {
    "badauth": "The username or password was rejected.",
    "nohost": "That hostname doesn't exist under this account.",
    "notfqdn": "The hostname isn't a fully qualified domain name.",
    "abuse": "The provider has blocked this hostname for abuse.",
    "!yours": "That hostname belongs to a different account.",
    "!active": "That hostname isn't active yet.",
    "badsys": "The provider rejected the request type.",
    "numhost": "Too many hostnames in one update.",
    "911": "The provider is in maintenance — retrying later.",
    "dnserr": "The provider reported a DNS error — retrying later.",
    "servererror": "The provider had a server error — retrying later.",
}


def _update_duckdns(hostname: str, creds: dict, ip: str) -> DdnsResult:
    token = creds.get("token", "")
    if not token:
        return DdnsResult("fatal", "nocreds", "A DuckDNS token is required.")
    # DuckDNS wants the BARE subdomain; the full x.duckdns.org returns KO.
    sub = hostname.strip()
    if sub.endswith(".duckdns.org"):
        sub = sub[: -len(".duckdns.org")]
    url = "https://www.duckdns.org/update?" + urllib.parse.urlencode(
        {"domains": sub, "token": token, "ip": ip})
    try:
        _, body = _get(url)
    except OSError as e:
        return DdnsResult("retry", "network", str(e))
    out = body.strip()
    if out.startswith("OK"):
        return DdnsResult("ok", "OK", "Hostname updated.", ip)
    if out.startswith("KO"):
        # DuckDNS gives no detail on failure — the token or domain is wrong.
        return DdnsResult("fatal", "KO", "DuckDNS rejected the update — check "
                                         "the domain and token.")
    return DdnsResult("retry", "unknown", out[:120])


def _update_cloudflare(hostname: str, creds: dict, ip: str) -> DdnsResult:
    token = creds.get("token", "")
    if not token:
        return DdnsResult("fatal", "nocreds", "A Cloudflare API token is required.")
    zone = creds.get("zone", "")
    if not zone:
        # zone is everything after the first label, e.g. nas.example.com -> example.com
        parts = hostname.split(".")
        zone = ".".join(parts[1:]) if len(parts) > 2 else hostname
    api = "https://api.cloudflare.com/client/v4"
    try:
        st, z = _json_req(f"{api}/zones?{urllib.parse.urlencode({'name': zone})}", token)
    except OSError as e:
        return DdnsResult("retry", "network", str(e))
    if st in (401, 403):
        return DdnsResult("fatal", "badauth", "Cloudflare rejected the API token.")
    zres = (z or {}).get("result") or []
    if not zres:
        return DdnsResult("fatal", "nozone", f"No Cloudflare zone found for {zone}.")
    zone_id = zres[0].get("id", "")

    q = urllib.parse.urlencode({"name": hostname, "type": "A"})
    try:
        st, rec = _json_req(f"{api}/zones/{zone_id}/dns_records?{q}", token)
    except OSError as e:
        return DdnsResult("retry", "network", str(e))
    rres = (rec or {}).get("result") or []
    if not rres:
        return DdnsResult("fatal", "norecord",
                          f"No A record named {hostname} in that zone — create it first.")
    record = rres[0]
    if record.get("content") == ip:
        return DdnsResult("nochg", "nochg", "Already up to date.", ip)

    # PATCH, not PUT: only `content` changes, and PUT replaces the whole record.
    try:
        st, out = _json_req(f"{api}/zones/{zone_id}/dns_records/{record.get('id','')}",
                            token, method="PATCH", payload={"content": ip})
    except OSError as e:
        return DdnsResult("retry", "network", str(e))
    if (out or {}).get("success"):
        return DdnsResult("ok", "good", "Record updated.", ip)
    errs = (out or {}).get("errors") or []
    msg = (errs[0].get("message") if errs and isinstance(errs[0], dict) else "") or "Update failed."
    return DdnsResult("fatal" if st in (400, 401, 403) else "retry", str(st), msg[:120])


def _update_custom(hostname: str, creds: dict, ip: str) -> DdnsResult:
    tpl = creds.get("url", "")
    if not tpl:
        return DdnsResult("fatal", "nourl", "A custom update URL is required.")
    url = tpl.replace("{ip}", urllib.parse.quote(ip)).replace(
        "{hostname}", urllib.parse.quote(hostname))
    if not url.lower().startswith(("http://", "https://")):
        return DdnsResult("fatal", "badurl", "The update URL must be http(s).")
    try:
        st, body = _get(url)
    except OSError as e:
        return DdnsResult("retry", "network", str(e))
    if 200 <= st < 300:
        return DdnsResult("ok", str(st), body.strip()[:120] or "Update accepted.", ip)
    if st in (401, 403):
        return DdnsResult("fatal", str(st), "The endpoint rejected the credentials.")
    return DdnsResult("retry", str(st), body.strip()[:120])


def update(cfg: dict, ip: str) -> DdnsResult:
    """Push `ip` to the configured provider."""
    provider = cfg.get("provider", "")
    hostname = cfg.get("hostname", "")
    creds = cfg.get("credentials") or {}
    if provider not in PROVIDERS:
        return DdnsResult("fatal", "noprovider", "No DDNS provider configured.")
    if not hostname:
        return DdnsResult("fatal", "nohostname", "No hostname configured.")
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return DdnsResult("retry", "noip", "Could not determine the public IP.")

    if provider in _DYNDNS2_HOSTS:
        return _update_dyndns2(provider, hostname, creds, ip)
    if provider == "duckdns":
        return _update_duckdns(hostname, creds, ip)
    if provider == "cloudflare":
        return _update_cloudflare(hostname, creds, ip)
    return _update_custom(hostname, creds, ip)


# ════════════════════════════════════════════════════════════════════
# SCHEDULER TICK  (called from the app's existing 60s loop)
# ════════════════════════════════════════════════════════════════════
def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def due(cfg: dict, now_ts: float) -> bool:
    """Is an update owed? Enabled, configured, and past the interval."""
    if not cfg.get("enabled") or not cfg.get("provider"):
        return False
    # A prior FATAL result parks the loop — re-sending only earns a ban or
    # rate-limit. The user clears it by saving new settings (which resets
    # last_status) or hitting Test.
    if cfg.get("last_status") == "fatal":
        return False
    interval = max(5, int(cfg.get("interval_minutes", 5))) * 60
    return (now_ts - float(cfg.get("last_ts", 0))) >= interval


def tick(now_ts: float) -> Optional[DdnsResult]:
    """One scheduler step. Returns the result if an update ran, else None.

    Only pushes when the public IP actually differs from what was last
    confirmed — dyndns2 providers treat repeated unchanged updates as abuse.
    Persists outcome (including the parked-on-fatal state) so it survives a
    restart and the UI can show it.
    """
    cfg = load()
    if not due(cfg, now_ts):
        return None
    ip = detect_public_ip()
    if not ip:
        # transient — try again next tick, don't record a fatal
        return DdnsResult("retry", "noip", "Public IP unavailable.")
    if ip == cfg.get("last_ip") and cfg.get("last_status") in ("ok", "nochg"):
        # nothing to do; just advance the clock so we don't re-check every tick
        cfg["last_ts"] = now_ts
        _persist(cfg)
        return None

    res = update(cfg, ip)
    cfg["last_ts"] = now_ts
    cfg["last_update"] = _now_iso()
    cfg["last_status"] = res.status
    cfg["last_message"] = res.message
    if res.success:
        cfg["last_ip"] = res.ip or ip
    _persist(cfg)
    if res.status == "fatal":
        logger.warning("ddns: parked after fatal result (%s): %s", res.code, res.message)
    return res


def _persist(cfg: dict) -> None:
    try:
        save(cfg)
    except OSError as e:
        logger.warning("ddns: could not persist state: %s", e)
