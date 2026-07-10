"""ForgeOS — NGINX API surface.

Mounts under the existing FastAPI app via:

    from nginx_api import router as nginx_router, set_helpers as set_nginx_helpers
    set_nginx_helpers(run_args=_run_args, audit=_audit)
    app.include_router(nginx_router)

Routes (/api/nginx/*): vhosts (CRUD), raw config (GET/PUT), reload, test, certbot
"""
from __future__ import annotations

import re
import subprocess
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

import forgeos_config as fc
from generators import registry
from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_run_args: Optional[Callable[..., str]] = None
_audit: Optional[Callable[..., None]] = None


def set_helpers(
    run_args: Callable[..., str],
    audit: Callable[..., None],
    start_task: Callable[..., str] | None = None,
) -> None:
    global _run_args, _audit, _start_task
    _run_args = run_args
    _audit = audit
    _start_task = start_task


_start_task: Callable[..., str] | None = None


# certbot-dns-multi credential store. A 0600 ini the API owns; certbot reads it
# for DNS-01 challenges. Module-level so tests can isolate it.
DNS_CREDS_FILE = Path("/etc/letsencrypt/dns-multi.ini")   # legacy single-provider path


def _provider_creds_path(code: str) -> Path:
    """One creds file PER PROVIDER — same provider + many domains share it."""
    return Path(f"/etc/letsencrypt/dns-{code}.ini")
_DNS_PROVIDER_RE = re.compile(r"^[a-z0-9_]+$")          # lego provider codes
_DNS_CRED_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")     # env-var names


def _atomic_write_0600(path: Path, content: str) -> None:
    """Atomically write `content` with 0600 perms (the file holds DNS API
    tokens). Temp-file + fsync + chmod + os.replace, same as the user store."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dns-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# Save the config-DB then regenerate + reload nginx via the v2 generator.
# Overridable in tests so they don't write /etc or touch systemctl. Mirrors the
# Samba API pattern — config-DB is the single source of truth; the generator
# renders forgeos.d/<name>.conf and reconciles away orphans.
_apply = None


def _apply_nginx(cfg) -> None:
    if _apply is not None:
        _apply(cfg)
        return
    fc.save(cfg)
    registry.apply_one("nginx", cfg=cfg)


def set_apply(fn) -> None:
    """Test seam: inject a fake apply (save+generate+reload)."""
    global _apply
    _apply = fn


def _cert_state(domain: str) -> str:
    """'letsencrypt' if a live cert dir covers this domain (exact, or the
    parent domain for wildcard coverage), else 'self-signed' (snakeoil)."""
    base = domain[2:] if domain.startswith("*.") else domain
    candidates = [base]
    if "." in base:
        candidates.append(base.split(".", 1)[1])   # wildcard on the parent
    for c in candidates:
        if Path(f"/etc/letsencrypt/live/{c}/fullchain.pem").exists():
            return "letsencrypt"
    return "self-signed"


@router.get("/api/nginx/vhosts")
async def nginx_vhosts(user=Depends(verify_token)):
    # V2 engine: read vhosts from the config-DB, not by scraping forgeos.d/*.conf.
    cfg = fc.load()
    return {"vhosts": [{**v.model_dump(), "cert": _cert_state(v.domain)}
                       for v in cfg.nginx.vhosts]}


@router.get("/api/nginx/certs")
async def list_certs(user=Depends(verify_token)):
    """Issued certs under /etc/letsencrypt/live/, with the SANs each covers —
    lets a vhost SELECT an existing/wildcard cert instead of issuing its own.
    Reads the cert to report real coverage (wildcards included)."""
    out = []
    seen = set()
    # 1) Registered EXTERNAL certs first (they win path resolution too).
    cfg = fc.load()
    for c in getattr(cfg.nginx, "external_certs", []):
        p_fc = Path(c.fullchain_path)
        out.append({"name": c.name, "covers": _cert_sans(p_fc),
                    "source": "external", "present": p_fc.exists(),
                    "expires": _cert_expiry(p_fc)})
        seen.add(c.name)
    # 2) Let's Encrypt issued certs.
    live = Path("/etc/letsencrypt/live")
    if live.is_dir():
        for d in sorted(live.iterdir()):
            fc_pem = d / "fullchain.pem"
            if not d.is_dir() or not fc_pem.exists() or d.name in seen:
                continue
            out.append({"name": d.name, "covers": _cert_sans(fc_pem),
                        "source": "letsencrypt", "present": True,
                        "expires": _cert_expiry(fc_pem)})
    return {"certs": out}


@router.post("/api/nginx/certs/register")
async def register_cert(body: dict, user=Depends(verify_token)):
    """Register an EXTERNALLY-managed cert (e.g. a porkbun-certbot container's
    output) by name + PEM paths, so vhosts can select it. ForgeOS does not
    issue or renew it — the external tool owns its lifecycle."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    name = str(body.get("name", "")).strip()
    fullchain = str(body.get("fullchain_path", "")).strip()
    privkey = str(body.get("privkey_path", "")).strip()
    if not (name and fullchain and privkey):
        raise HTTPException(400, "name, fullchain_path, privkey_path required")
    # Must exist and be readable now — fail loud, not at nginx reload.
    for pth in (fullchain, privkey):
        if not Path(pth).is_file():
            raise HTTPException(400, f"file not found: {pth}")
    cfg = fc.load()
    cfg.nginx.external_certs = [c for c in cfg.nginx.external_certs if c.name != name]
    try:
        cfg.nginx.external_certs.append(
            fc.ExternalCert(name=name, fullchain_path=fullchain, privkey_path=privkey))
    except Exception as e:
        raise HTTPException(400, f"invalid: {e}")
    fc.save(cfg)
    assert _audit is not None
    _audit(user["sub"], "nginx.cert.register", "success", f"registered external cert {name}")
    return {"ok": True}


@router.delete("/api/nginx/certs/{name}")
async def delete_cert(name: str, user=Depends(verify_token)):
    """Remove a cert. External: forget the registration (files untouched).
    Let's Encrypt: delete the lineage via certbot. Refuses if any vhost still
    selects it — no silent fallback to snakeoil behind the user's back."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    cfg = fc.load()
    users = [v.name for v in cfg.nginx.vhosts if (v.cert_name or v.domain) == name]
    if users:
        raise HTTPException(409, f"cert in use by vhost(s): {', '.join(users)}")
    ext = [c for c in cfg.nginx.external_certs if c.name == name]
    if ext:
        cfg.nginx.external_certs = [c for c in cfg.nginx.external_certs if c.name != name]
        fc.save(cfg)
        assert _audit is not None
        _audit(user["sub"], "nginx.cert.delete", "success", f"unregistered external cert {name}")
        return {"ok": True, "source": "external"}
    # Let's Encrypt lineage
    if not Path(f"/etc/letsencrypt/live/{name}").exists():
        raise HTTPException(404, f"no such cert: {name}")
    assert _run_args is not None
    _run_args(["certbot", "delete", "--cert-name", name, "--non-interactive"], timeout=60)
    assert _audit is not None
    _audit(user["sub"], "nginx.cert.delete", "success", f"deleted LE cert {name}")
    return {"ok": True, "source": "letsencrypt"}


def _cert_expiry(fullchain: Path) -> str:
    """notAfter date (ISO-ish) via openssl, or "" if unreadable/missing."""
    try:
        if not fullchain.exists():
            return ""
        r = subprocess.run(
            ["openssl", "x509", "-in", str(fullchain), "-noout", "-enddate"],
            capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and "=" in r.stdout:
            return r.stdout.split("=", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _cert_sans(fullchain: Path) -> list[str]:
    """SAN list from a cert, via openssl (no python crypto dep). Best-effort:
    empty on any failure — the dropdown still lists the cert by dir name."""
    try:
        r = subprocess.run(
            ["openssl", "x509", "-in", str(fullchain), "-noout", "-ext", "subjectAltName"],
            capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return []
        # output: "    DNS:example.com, DNS:*.example.com"
        return [tok.strip()[4:] for tok in r.stdout.split(",")
                if tok.strip().startswith("DNS:")]
    except (OSError, subprocess.SubprocessError):
        return []


@router.post("/api/nginx/apply")
async def nginx_apply(user=Depends(verify_token)):
    """Re-render + reload without changing config — needed after cert
    issuance completes so the generator switches snakeoil -> LE cert."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    _apply_nginx(fc.load())
    return {"ok": True}


@router.post("/api/nginx/vhost")
async def add_vhost(body: dict, user=Depends(verify_token)):
    """Create a vhost in the config-DB and regenerate. Exposes every NginxVhost
    option (the N1 advanced fields), validated by the model at the boundary."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    try:
        vhost = fc.NginxVhost(**body)
    except (ValidationError, KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, detail=f"invalid vhost: {e}")
    cfg = fc.load()
    if any(v.name.lower() == vhost.name.lower() for v in cfg.nginx.vhosts):
        raise HTTPException(409, detail=f"vhost '{vhost.name}' already exists")
    cfg.nginx.vhosts.append(vhost)
    _apply_nginx(cfg)
    assert _audit is not None
    _audit(user["sub"], "nginx.vhost.create", "success",
           f"Vhost '{vhost.name}' for {vhost.domain} -> "
           f"{vhost.upstream_host}:{vhost.upstream_port}")
    return {"ok": True, "vhost": vhost.model_dump()}


@router.put("/api/nginx/vhost/{name}")
async def update_vhost(name: str, body: dict, user=Depends(verify_token)):
    """Edit an existing vhost. The URL name is the key; rename = delete+create."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    cfg = fc.load()
    idx = next((i for i, v in enumerate(cfg.nginx.vhosts) if v.name == name), None)
    if idx is None:
        raise HTTPException(404, detail=f"vhost '{name}' not found")
    try:
        vhost = fc.NginxVhost(**{**body, "name": name})
    except (ValidationError, KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, detail=f"invalid vhost: {e}")
    cfg.nginx.vhosts[idx] = vhost
    _apply_nginx(cfg)
    assert _audit is not None
    _audit(user["sub"], "nginx.vhost.update", "success",
           f"Vhost '{name}' updated -> {vhost.domain}:{vhost.upstream_port}")
    return {"ok": True, "vhost": vhost.model_dump()}


@router.delete("/api/nginx/vhost/{name}")
async def remove_vhost(name: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    # The UI's own front door — deleting it drops the :443 default_server and
    # locks the operator out. Never removable through the API.
    if name == "forgeos-ui":
        raise HTTPException(403, detail="cannot delete the ForgeOS UI vhost")
    cfg = fc.load()
    before = len(cfg.nginx.vhosts)
    cfg.nginx.vhosts = [v for v in cfg.nginx.vhosts if v.name != name]
    if len(cfg.nginx.vhosts) == before:
        raise HTTPException(404, detail=f"vhost '{name}' not found")
    _apply_nginx(cfg)
    assert _audit is not None
    _audit(user["sub"], "nginx.vhost.delete", "success", f"Vhost '{name}' removed")
    return {"ok": True}


@router.get("/api/nginx/raw")
async def nginx_raw_config(user=Depends(verify_token)):
    return {"config": Path("/etc/nginx/nginx.conf").read_text() if Path("/etc/nginx/nginx.conf").exists() else ""}


@router.put("/api/nginx/raw")
async def nginx_save_raw(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    config = body.get("config", "")
    # Test first using a secure temp file
    import tempfile
    import os as _os
    _fd, _tmp = tempfile.mkstemp(prefix="forgeos-nginx-", suffix=".conf")
    try:
        with _os.fdopen(_fd, "w") as _fh:
            _fh.write(config)
        test = _run_args(["nginx", "-t", "-c", _tmp])
    finally:
        _os.unlink(_tmp) if _os.path.exists(_tmp) else None
    if "failed" in test.lower():
        raise HTTPException(400, detail={"error": "Config test failed", "output": test})
    Path("/etc/nginx/nginx.conf").write_text(config)
    # Test live config, then reload — never reload a broken config
    test = _run_args(["nginx", "-t"], timeout=10)
    if "failed" in test.lower() or "test is successful" not in test:
        raise HTTPException(400, detail={"error": "Live config test failed", "output": test})
    _run_args(["systemctl", "reload", "nginx"])
    _audit(user["sub"], "nginx.config.update", "success", "Raw nginx config updated & reloaded")
    return {"ok": True}


@router.post("/api/nginx/reload")
async def nginx_reload(user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    # Test config first, only reload if test passes
    test = _run_args(["nginx", "-t"], timeout=10)
    if "test is successful" not in test:
        return {"ok": False, "error": "Config test failed", "output": test}
    result = _run_args(["systemctl", "reload", "nginx"])
    _audit(user["sub"], "nginx.reload", "success", "Nginx reloaded")
    return {"ok": True, "output": result}


@router.post("/api/nginx/test")
async def nginx_test(user=Depends(verify_token)):
    return {"output": _run_args(["nginx", "-t"], timeout=10)}


@router.post("/api/nginx/certbot")
async def request_cert(body: dict, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    domain = body.get("domain", "")
    email  = body.get("email", "")
    if not domain:
        raise HTTPException(400, "domain required")
    # Strict validation: only allow valid domain/email chars - no shell metacharacters
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}[a-zA-Z0-9]$", domain):
        raise HTTPException(400, "Invalid domain name")
    if email and not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email):
        raise HTTPException(400, "Invalid email address")
    # Use arg list - no shell injection possible
    cmd = ["certbot", "certonly", "--nginx", "--non-interactive",
           "--agree-tos", "--email", email or f"admin@{domain}", "-d", domain]
    result = _run_args(cmd, timeout=120)
    _audit(user["sub"], "nginx.certbot", "success", f"Cert requested for {domain}")
    return {"ok": True, "output": result}



# ── DNS-01 (certbot-dns-multi) ────────────────────────────────────────────────
# DNS-01 issues certs (incl. wildcards, and without exposing port 80) by proving
# control via a DNS TXT record. certbot-dns-multi bridges certbot to lego's 117+
# providers via a single 0600 credentials file. Certs land in the standard
# /etc/letsencrypt/live/<domain>/ path, so the nginx generator picks them up with
# no changes — same as HTTP-01.

@router.get("/api/nginx/acme/dns")
async def get_dns_provider(user=Depends(verify_token)):
    """Return the configured DNS provider. NEVER returns the credentials —
    they are write-only."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    if not DNS_CREDS_FILE.exists():
        return {"configured": False, "provider": None}
    provider = None
    for line in DNS_CREDS_FILE.read_text().splitlines():
        if line.strip().startswith("dns_multi_provider"):
            provider = line.split("=", 1)[1].strip()
            break
    return {"configured": provider is not None, "provider": provider}


@router.put("/api/nginx/acme/dns")
async def set_dns_provider(body: dict, user=Depends(verify_token)):
    """Configure the DNS-01 provider + credentials. Writes
    /etc/letsencrypt/dns-multi.ini at 0600. Credentials never leave the box via
    the API. Provider/key/value are validated to keep the .ini uninjectable."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    provider = str(body.get("provider", "")).strip().lower()
    if not _DNS_PROVIDER_RE.match(provider):
        raise HTTPException(400, "Invalid provider code (lowercase letters, digits, underscore)")
    creds = body.get("credentials")
    if not isinstance(creds, dict) or not creds:
        raise HTTPException(400, "At least one credential is required")
    lines = [f"dns_multi_provider = {provider}"]
    for k, v in creds.items():
        k = str(k).strip()
        v = str(v)
        if not _DNS_CRED_KEY_RE.match(k):
            raise HTTPException(400, f"Invalid credential key: {k!r} (expected ENV_VAR style)")
        if any(c in v for c in "\n\r\x00"):
            raise HTTPException(400, f"Invalid value for {k} (control characters not allowed)")
        lines.append(f"{k} = {v}")
    _atomic_write_0600(DNS_CREDS_FILE, "\n".join(lines) + "\n")
    assert _audit is not None
    _audit(user["sub"], "nginx.acme.dns.config", "success", f"DNS provider set to {provider}")
    return {"ok": True, "provider": provider}


@router.delete("/api/nginx/acme/dns")
async def delete_dns_provider(user=Depends(verify_token)):
    """Remove the DNS provider credentials."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    existed = DNS_CREDS_FILE.exists()
    if existed:
        DNS_CREDS_FILE.unlink()
    assert _audit is not None
    _audit(user["sub"], "nginx.acme.dns.delete", "success", "DNS provider removed")
    return {"ok": True, "removed": existed}


@router.get("/api/nginx/domains")
async def list_domains(user=Depends(verify_token)):
    """Managed domains + their cert state. A domain's cert is named after the
    domain; vhosts under it inherit that cert automatically."""
    cfg = fc.load()
    out = []
    for d in cfg.nginx.domains:
        live = Path(f"/etc/letsencrypt/live/{d.name}/fullchain.pem")
        out.append({"name": d.name, "provider": d.provider, "wildcard": d.wildcard,
                    "cert_present": live.exists(), "covers": _cert_sans(live),
                    "expires": _cert_expiry(live)})
    providers = [{"code": p.code} for p in cfg.nginx.dns_providers]
    return {"domains": out, "providers": providers}


@router.post("/api/nginx/domains")
async def add_domain(body: dict, user=Depends(verify_token)):
    """Add a domain: store the provider creds (shared per provider), record the
    domain, and ISSUE its cert now. wildcard -> name + *.name; else just name.

    NOTE: ForgeOS issues the CERT. The A/CNAME record that makes the name
    resolve must already exist at the DNS provider — ForgeOS cannot create it.
    """
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    name = str(body.get("name", "")).strip().lower()
    provider = str(body.get("provider", "")).strip().lower()
    wildcard = bool(body.get("wildcard", True))
    creds = body.get("credentials")            # {ENV: value}; optional if provider already saved
    email = str(body.get("email", "")).strip()
    if not name or not provider:
        raise HTTPException(400, "name and provider required")
    if not _DNS_PROVIDER_RE.match(provider):
        raise HTTPException(400, "invalid provider code")

    cfg = fc.load()

    # 1. provider creds: write if given, else must already exist (shared reuse)
    creds_path = _provider_creds_path(provider)
    if creds:
        lines = [f"dns_multi_provider = {provider}"]
        for k, v in creds.items():
            if not _DNS_CRED_KEY_RE.match(str(k)):
                raise HTTPException(400, f"invalid credential key: {k}")
            lines.append(f"{k} = {v}")
        _atomic_write_0600(creds_path, "\n".join(lines) + "\n")
        if not any(pp.code == provider for pp in cfg.nginx.dns_providers):
            cfg.nginx.dns_providers.append(
                fc.DnsProvider(code=provider, creds_path=str(creds_path)))
    elif not creds_path.exists():
        raise HTTPException(400, f"no saved credentials for '{provider}' — provide them")

    # 2. record the domain (replace if re-adding)
    cfg.nginx.domains = [d for d in cfg.nginx.domains if d.name != name]
    try:
        cfg.nginx.domains.append(fc.Domain(name=name, provider=provider, wildcard=wildcard))
    except Exception as e:
        raise HTTPException(400, f"invalid: {e}")
    fc.save(cfg)

    # 3. issue the cert now (background task; propagation can take minutes)
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}[a-zA-Z0-9]$", name):
        raise HTTPException(400, "Invalid domain name")
    cmd = ["certbot", "certonly", "-a", "dns-multi",
           "--dns-multi-credentials", str(creds_path),
           "--non-interactive", "--agree-tos",
           "--email", email or f"admin@{name}",
           "--cert-name", name, "-d", name]
    if wildcard:
        cmd += ["-d", f"*.{name}"]
    assert _start_task is not None
    task_id = _start_task(cmd, "certbot", "domain-add", timeout=3900)
    assert _audit is not None
    _audit(user["sub"], "nginx.domain.add", "success",
           f"added {name} ({provider}, {'wildcard' if wildcard else 'single'})")
    return {"ok": True, "task_id": task_id,
            "note": "Cert issuing in the background. Ensure the domain's A/CNAME "
                    "record points to this server at your DNS provider."}


@router.delete("/api/nginx/domains/{name}")
async def remove_domain(name: str, user=Depends(verify_token)):
    """Forget a domain (and delete its LE cert). Refuses if a vhost is under it
    — those vhosts would silently drop to self-signed otherwise."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    cfg = fc.load()
    name = name.strip().lower()
    users = [v.name for v in cfg.nginx.vhosts
             if v.domain.lower() == name or v.domain.lower().endswith("." + name)]
    if users:
        raise HTTPException(409, f"domain in use by vhost(s): {', '.join(users)}")
    if not any(d.name == name for d in cfg.nginx.domains):
        raise HTTPException(404, f"no such domain: {name}")
    cfg.nginx.domains = [d for d in cfg.nginx.domains if d.name != name]
    fc.save(cfg)
    if Path(f"/etc/letsencrypt/live/{name}").exists():
        assert _run_args is not None
        _run_args(["certbot", "delete", "--cert-name", name, "--non-interactive"], timeout=60)
    assert _audit is not None
    _audit(user["sub"], "nginx.domain.delete", "success", f"removed domain {name}")
    return {"ok": True}


@router.post("/api/nginx/cert/dns")
async def request_cert_dns(body: dict, user=Depends(verify_token)):
    """Issue a cert via DNS-01 (certbot-dns-multi). Supports wildcard. The cert
    lands in /etc/letsencrypt/live/<domain>/ for the generator to pick up."""
    if user.get("role") != "admin":
        raise HTTPException(403)
    if not DNS_CREDS_FILE.exists():
        raise HTTPException(400, "No DNS provider configured — set one first")
    domain = str(body.get("domain", "")).strip()
    email = str(body.get("email", "")).strip()
    wildcard = bool(body.get("wildcard", False))
    # apex controls whether the bare domain is included. Default True keeps
    # back-compat (domain always issued). Three combos:
    #   wildcard=F, apex=T  -> example.com
    #   wildcard=T, apex=T  -> example.com + *.example.com
    #   wildcard=T, apex=F  -> *.example.com only
    apex = bool(body.get("apex", True))
    # Same strict validation as the HTTP-01 path — no shell metacharacters.
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,253}[a-zA-Z0-9]$", domain):
        raise HTTPException(400, "Invalid domain name")
    if email and not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email):
        raise HTTPException(400, "Invalid email address")
    if not apex and not wildcard:
        raise HTTPException(400, "Nothing to issue: enable apex, wildcard, or both")
    # arg-list (no shell). Labels are CONSTRUCTED from the validated domain.
    cmd = ["certbot", "certonly", "-a", "dns-multi",
           "--dns-multi-credentials", str(DNS_CREDS_FILE),
           "--non-interactive", "--agree-tos",
           "--email", email or f"admin@{domain}"]
    # cert lineage name = the apex domain so it's predictable/selectable even
    # for a wildcard-only cert (certbot would otherwise name it after *.).
    cmd += ["--cert-name", domain]
    if apex:
        cmd += ["-d", domain]
    if wildcard:
        cmd += ["-d", f"*.{domain}"]
    # DNS-01 waits for propagation — lego's per-provider defaults run 600s
    # (Porkbun) up to 3600s (Namecheap). A synchronous request dies three
    # ways: subprocess timeout, blocked event loop (workers=1), and nginx's
    # 60s proxy timeout. Background task + polling is the only honest shape.
    # 3900s ceiling = worst provider default + certbot overhead.
    assert _start_task is not None
    task_id = _start_task(cmd, "certbot", "dns-01", timeout=3900)
    assert _audit is not None
    _audit(user["sub"], "nginx.cert.dns", "success",
           f"DNS-01 cert requested for {domain}{' (+wildcard)' if wildcard else ''}")
    return {"ok": True, "task_id": task_id,
            "note": "Issuance runs in the background; DNS propagation can "
                    "take up to your provider's timeout (e.g. Porkbun 600s)."}
