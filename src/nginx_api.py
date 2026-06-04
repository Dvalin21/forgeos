"""ForgeOS — NGINX API surface.

Mounts under the existing FastAPI app via:

    from nginx_api import router as nginx_router, set_helpers as set_nginx_helpers
    set_nginx_helpers(run_args=_run_args, audit=_audit)
    app.include_router(nginx_router)

Routes (/api/nginx/*): vhosts (CRUD), raw config (GET/PUT), reload, test, certbot
"""
from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from forgeos_auth import verify_token

logger = logging.getLogger("forgeos-api")

router = APIRouter()

# Injected by main module — see set_helpers().
_run_args: Optional[Callable[..., str]] = None
_audit: Optional[Callable[..., None]] = None


def set_helpers(
    run_args: Callable[..., str],
    audit: Callable[..., None],
) -> None:
    global _run_args, _audit
    _run_args = run_args
    _audit = audit


@router.get("/api/nginx/vhosts")
async def nginx_vhosts(user=Depends(verify_token)):
    """List all vhosts from forgeos.d/*.conf"""
    vhosts = []
    conf_dir = Path("/etc/nginx/forgeos.d")
    if not conf_dir.exists():
        return {"vhosts": []}
    for f in sorted(conf_dir.glob("*.conf")):
        text = f.read_text()
        domain = re.search(r"server_name\s+(\S+);", text)
        upstream = re.search(r"proxy_pass\s+http://\S+:(\d+)", text)
        has_ssl = "ssl_certificate" in text
        name = f.stem
        vhosts.append({
            "name": name,
            "domain": domain.group(1) if domain else name,
            "upstream_port": upstream.group(1) if upstream else "?",
            "ssl": has_ssl,
            "enabled": True,
            "raw": text,
        })
    return {"vhosts": vhosts}


@router.post("/api/nginx/vhost")
async def add_vhost(body: dict, user=Depends(verify_token)):
    """Add a new vhost via forgeos-nginx CLI"""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")
    name   = re.sub(r"[^a-z0-9-]", "", body["name"].lower())
    domain = body["domain"]
    port   = int(body["port"])
    tls    = body.get("tls", "acme")
    ws     = body.get("websocket", False)
    auth   = body.get("auth", "none")

    if not 1 <= port <= 65535:
        raise HTTPException(400, "Invalid port")

    # Sanitize all user inputs before passing to shell
    name   = re.sub(r"[^a-z0-9-]", "", name.lower())[:64]
    domain = re.sub(r"[^a-zA-Z0-9.\-]", "", domain)[:253]
    tls    = tls   if tls  in ("acme", "selfsigned", "none") else "acme"
    auth   = auth  if auth in ("none", "basic", "oidc")      else "none"
    result = _run_args([
        "forgeos-nginx", "add-vhost", name, domain, str(port),
        tls, auth, "yes" if ws else "no"
    ])
    _audit(user["sub"], "nginx.vhost.create", "success",
            f"Vhost '{name}' for {domain} (port {port}, tls={tls})")
    return {"ok": True, "message": result}


@router.delete("/api/nginx/vhost/{name}")
async def remove_vhost(name: str, user=Depends(verify_token)):
    if user.get("role") != "admin":
        raise HTTPException(403)
    name = re.sub(r"[^a-z0-9-]", "", name)
    result = _run_args(["forgeos-nginx", "remove-vhost", name])
    _audit(user["sub"], "nginx.vhost.delete", "success", f"Vhost '{name}' removed")
    return {"ok": True, "message": result}


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

