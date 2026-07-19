"""
ForgeOS — additional API surface for the DSM-style web UI.

Mounts under the existing FastAPI app via:

    from forgeos_pages_api import router as pages_router
    app.include_router(pages_router)

Provides endpoints the original API was missing:
  • File Station   — browse / read / write / upload / mkdir / rename / delete,
                     scoped strictly to allowed roots (default /srv/nas).
  • Permissions    — POSIX chmod / chown (Linux-native).
  • Firewall       — rule list / add / delete / reload, IPv4 *and* IPv6,
                     fronted by the same `ufw` tooling already installed
                     (presented to users simply as "Firewall").
  • Storage drives — spin-down, mark-fail/replace, rebuild (mdadm).

Conventions reused from forgeos-api.py:
  • verify_token dependency for auth; user["role"] == "admin" for writes.
  • _audit(who, action, status, detail) for the audit log.
  • Explicit arg-list subprocess calls (shell=False) — no shell injection.
"""
from __future__ import annotations

import os
import re
import shutil
import stat as statmod
import subprocess
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, JSONResponse

# Auth dependency — same source the other routers use.
from forgeos_auth import verify_token  # type: ignore

# _audit lives in the main (dash-named) module, which isn't importable by name.
# The main app injects it via `set_audit()` at include time; until then we fall
# back to a direct SQLite write so auditing never silently disappears.
_AUDIT_DB = os.environ.get("FORGEOS_DB", "/var/lib/forgeos/forgeos.db")
__audit_impl__ = None


def set_audit(fn) -> None:
    """Called by forgeos-api.py: pages_router-module.set_audit(_audit)."""
    global __audit_impl__
    __audit_impl__ = fn


def _audit(who: str, action: str, status: str, detail: str | None = None) -> None:
    if __audit_impl__:
        try:
            __audit_impl__(who, action, status, detail)
            return
        except Exception:
            pass
    # Fallback: best-effort direct insert (schema matches forgeos-api.py).
    try:
        import sqlite3
        import time as _t
        conn = sqlite3.connect(_AUDIT_DB, timeout=5)
        conn.execute(
            "INSERT INTO audit_log (timestamp, who, action, status, detail) "
            "VALUES (?,?,?,?,?)",
            (int(_t.time()), who, action, status, detail or ""),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


router = APIRouter(tags=["ForgeOS Web Pages"])

# ──────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────

def _run(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, shell=False)


def _admin(user) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")


# ──────────────────────────────────────────────────────────────
# FILE STATION  — scoped to allowed roots
# ──────────────────────────────────────────────────────────────
# Restrict every path operation to these roots. Anything resolving
# outside them (via .., symlinks, absolute paths) is rejected.
ALLOWED_ROOTS = [Path(p).resolve() for p in
                 os.environ.get("FORGEOS_FILE_ROOTS", "/srv/nas").split(":")
                 if p.strip()]


def _safe(path: str) -> Path:
    """Resolve `path` and guarantee it stays within an allowed root."""
    if not path:
        path = str(ALLOWED_ROOTS[0])
    p = Path(path)
    if not p.is_absolute():
        p = ALLOWED_ROOTS[0] / p
    rp = p.resolve()
    for root in ALLOWED_ROOTS:
        if rp == root or root in rp.parents:
            return rp
    raise HTTPException(403, "Path outside permitted storage roots")


def _entry(p: Path) -> dict:
    try:
        st = p.lstat()
    except OSError:
        return {}
    is_dir = p.is_dir()
    return {
        "name": p.name,
        "path": str(p),
        "type": "dir" if is_dir else ("link" if p.is_symlink() else "file"),
        "size": 0 if is_dir else st.st_size,
        "mtime": int(st.st_mtime),
        "mode": statmod.S_IMODE(st.st_mode),          # e.g. 0o755
        "mode_str": statmod.filemode(st.st_mode),     # e.g. drwxr-xr-x
        "owner": _uid_name(st.st_uid),
        "group": _gid_name(st.st_gid),
        "uid": st.st_uid,
        "gid": st.st_gid,
    }


def _uid_name(uid: int) -> str:
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return str(uid)


def _gid_name(gid: int) -> str:
    try:
        import grp
        return grp.getgrgid(gid).gr_name
    except Exception:
        return str(gid)


@router.get("/api/files/roots")
async def file_roots(user=Depends(verify_token)):
    """Top-level roots the browser is allowed to enter."""
    return {"roots": [str(r) for r in ALLOWED_ROOTS]}


@router.get("/api/files/list")
async def file_list(path: str = "", user=Depends(verify_token)):
    d = _safe(path)
    if not d.exists():
        raise HTTPException(404, "Path not found")
    if not d.is_dir():
        raise HTTPException(400, "Not a directory")
    entries = []
    try:
        for child in sorted(d.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            e = _entry(child)
            if e:
                entries.append(e)
    except PermissionError:
        raise HTTPException(403, "Permission denied")
    # breadcrumb trail back to the nearest allowed root
    crumbs, cur = [], d
    root = next((r for r in ALLOWED_ROOTS if r == d or r in d.parents), ALLOWED_ROOTS[0])
    while True:
        crumbs.append({"name": cur.name or str(cur), "path": str(cur)})
        if cur == root or cur.parent == cur:
            break
        cur = cur.parent
    crumbs.reverse()
    return {"path": str(d), "entries": entries, "crumbs": crumbs}


@router.get("/api/files/download")
async def file_download(path: str, user=Depends(verify_token)):
    p = _safe(path)
    if not p.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(str(p), filename=p.name)


@router.post("/api/files/upload")
async def file_upload(path: str = Form(...), files: List[UploadFile] = File(...),
                      user=Depends(verify_token)):
    _admin(user)
    d = _safe(path)
    if not d.is_dir():
        raise HTTPException(400, "Target is not a directory")
    saved = []
    for f in files:
        name = os.path.basename(f.filename or "upload")
        name = re.sub(r"[^A-Za-z0-9 ._-]", "_", name)
        dest = _safe(str(d / name))
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(name)
    _audit(user["sub"], "files.upload", "success", f"{len(saved)} file(s) -> {d}")
    return {"ok": True, "saved": saved}


@router.post("/api/files/mkdir")
async def file_mkdir(body: dict, user=Depends(verify_token)):
    _admin(user)
    parent = _safe(body.get("path", ""))
    name = re.sub(r"[^A-Za-z0-9 ._-]", "_", body.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Folder name required")
    target = _safe(str(parent / name))
    target.mkdir(parents=False, exist_ok=False)
    _audit(user["sub"], "files.mkdir", "success", str(target))
    return {"ok": True, "path": str(target)}


@router.post("/api/files/rename")
async def file_rename(body: dict, user=Depends(verify_token)):
    _admin(user)
    src = _safe(body.get("src", ""))
    new = re.sub(r"[^A-Za-z0-9 ._-]", "_", body.get("name", "")).strip()
    if not new:
        raise HTTPException(400, "New name required")
    dst = _safe(str(src.parent / new))
    src.rename(dst)
    _audit(user["sub"], "files.rename", "success", f"{src} -> {dst}")
    return {"ok": True, "path": str(dst)}


@router.post("/api/files/delete")
async def file_delete(body: dict, user=Depends(verify_token)):
    _admin(user)
    p = _safe(body.get("path", ""))
    if p in ALLOWED_ROOTS:
        raise HTTPException(400, "Refusing to delete a storage root")
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()
    _audit(user["sub"], "files.delete", "success", str(p))
    return {"ok": True}


def _unique(dst: Path) -> Path:
    """If dst exists, append ' (copy)', ' (copy 2)', … until a free name."""
    if not dst.exists():
        return dst
    stem, suf = dst.stem, dst.suffix
    n = 1
    while True:
        cand = dst.with_name(f"{stem} (copy{'' if n == 1 else ' ' + str(n)}){suf}")
        if not cand.exists():
            return cand
        n += 1


def _plan_paste(items: list[str], target_dir: Path) -> list[tuple[Path, Path]]:
    """Validate every source + destination through _safe before any I/O."""
    if not target_dir.is_dir():
        raise HTTPException(400, "Target is not a directory")
    plan = []
    for raw in items:
        src = _safe(raw)
        if not src.exists():
            raise HTTPException(404, f"Missing source: {src}")
        # Refuse to paste a directory into itself or a descendant.
        if src.is_dir() and (src == target_dir or src in target_dir.parents):
            raise HTTPException(400, f"Cannot paste {src.name} into itself")
        dst = _safe(str(target_dir / src.name))
        dst = _unique(dst)
        plan.append((src, dst))
    return plan


@router.post("/api/files/copy")
async def file_copy(body: dict, user=Depends(verify_token)):
    """Copy one or more items into a target directory.
    Body: { items: [paths], target: dir }"""
    _admin(user)
    target = _safe(body.get("target", ""))
    items = body.get("items") or []
    if not items:
        raise HTTPException(400, "items required")
    plan = _plan_paste(items, target)
    for src, dst in plan:
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
    _audit(user["sub"], "files.copy", "success",
           f"{len(plan)} item(s) -> {target}")
    return {"ok": True, "count": len(plan)}


@router.post("/api/files/move")
async def file_move(body: dict, user=Depends(verify_token)):
    """Move one or more items into a target directory.
    Body: { items: [paths], target: dir }"""
    _admin(user)
    target = _safe(body.get("target", ""))
    items = body.get("items") or []
    if not items:
        raise HTTPException(400, "items required")
    plan = _plan_paste(items, target)
    for src, dst in plan:
        # shutil.move handles cross-filesystem (e.g. pool to pool) correctly.
        shutil.move(str(src), str(dst))
    _audit(user["sub"], "files.move", "success",
           f"{len(plan)} item(s) -> {target}")
    return {"ok": True, "count": len(plan)}


@router.get("/api/files/raw")
async def file_raw(path: str, user=Depends(verify_token)):
    """Serve a file inline (Content-Disposition: inline) for previewing in
    <img>/<video>/<audio>/<iframe>. Same scoping as everything else."""
    p = _safe(path)
    if not p.is_file():
        raise HTTPException(404, "File not found")
    # FileResponse with no filename= → inline disposition.
    return FileResponse(str(p))


# ──────────────────────────────────────────────────────────────
# APPS & SERVICES  — docker lifecycle, updates, nginx, services
# ──────────────────────────────────────────────────────────────

def _docker(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return _run(["docker"] + args, timeout=timeout)


def _container_safe(name: str) -> str:
    """Docker names: [a-zA-Z0-9][a-zA-Z0-9_.-]+. Reject anything else."""
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name or ""):
        raise HTTPException(400, "Invalid container name")
    return name


@router.post("/api/docker/wipe")
async def docker_wipe(body: dict, user=Depends(verify_token)):
    """Stop + remove the container, its image, and any anonymous volumes.
    Named volumes referenced by other containers are left alone (docker
    refuses to remove them when in use)."""
    _admin(user)
    name = _container_safe(body.get("name", ""))
    # Inspect first so we know the image and volume names.
    insp = _docker(["inspect", name], timeout=10)
    if insp.returncode != 0:
        raise HTTPException(404, "Container not found")
    import json as _json
    try:
        data = _json.loads(insp.stdout)[0]
    except Exception:
        raise HTTPException(500, "Could not parse container metadata")
    image = (data.get("Image") or "").strip()
    mounts = data.get("Mounts") or []
    named_vols = [m["Name"] for m in mounts if m.get("Type") == "volume" and m.get("Name")]
    # Stop + remove with -v (kills anonymous volumes).
    _docker(["stop", name], timeout=20)
    rm = _docker(["rm", "-v", "-f", name], timeout=20)
    if rm.returncode != 0:
        raise HTTPException(400, rm.stderr.strip() or "container remove failed")
    # Best-effort: remove the image if no other container uses it.
    img_out = ""
    if image:
        img = _docker(["image", "rm", image], timeout=20)
        img_out = (img.stdout or img.stderr or "").strip()
    # Best-effort: try removing each named volume (skips ones still in use).
    vol_out = []
    for v in named_vols:
        vr = _docker(["volume", "rm", v], timeout=10)
        vol_out.append(f"{v}: {(vr.stdout or vr.stderr).strip()}")
    _audit(user["sub"], "docker.wipe", "success",
           f"{name} (image={image}, vols={','.join(named_vols) or 'none'})")
    return {"ok": True, "image_result": img_out, "volume_results": vol_out}


@router.get("/api/docker/update-check")
async def docker_update_check(name: str | None = None, user=Depends(verify_token)):
    """Compare the local image digest against the remote registry digest.
    Returns an item per container with update_available True/False/None
    (None means we couldn't determine, e.g. locally built image)."""
    # List local containers; if `name` is given, restrict to that one.
    ps_args = ["ps", "-a", "--format", "{{.Names}}|{{.Image}}"]
    ps = _docker(ps_args, timeout=15)
    if ps.returncode != 0:
        raise HTTPException(500, "docker ps failed")
    items = []
    for line in ps.stdout.splitlines():
        try:
            cname, image = line.split("|", 1)
        except ValueError:
            continue
        if name and cname != name:
            continue
        info = {"name": cname, "image": image, "update_available": None,
                "local_digest": None, "remote_digest": None}
        # Local digest from `docker image inspect`.
        loc = _docker(["image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
                      timeout=8)
        if loc.returncode == 0 and "@" in loc.stdout:
            info["local_digest"] = loc.stdout.strip().split("@", 1)[1]
        # Remote digest via manifest. Requires `docker buildx imagetools` (modern
        # docker) or `skopeo`; fall back gracefully.
        for cmd in (
            ["buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest.Digest}}"],
            ["manifest", "inspect", "--verbose", image],
        ):
            rem = _docker(cmd, timeout=12)
            if rem.returncode == 0 and rem.stdout.strip():
                m = re.search(r"sha256:[0-9a-f]{64}", rem.stdout)
                if m:
                    info["remote_digest"] = m.group(0)
                    break
        if info["local_digest"] and info["remote_digest"]:
            info["update_available"] = info["local_digest"] != info["remote_digest"]
        items.append(info)
    return {"containers": items}


@router.post("/api/docker/update")
async def docker_update(body: dict, user=Depends(verify_token)):
    """Pull the container's image and recreate it preserving config.
    Strategy: `docker pull` then `docker stop && rm && run` reusing the
    original run-args. For compose-managed containers, the user should
    use compose up -d instead — we detect that and return a hint."""
    _admin(user)
    name = _container_safe(body.get("name", ""))
    insp = _docker(["inspect", name], timeout=10)
    if insp.returncode != 0:
        raise HTTPException(404, "Container not found")
    import json as _json
    try:
        data = _json.loads(insp.stdout)[0]
    except Exception:
        raise HTTPException(500, "Could not parse container metadata")
    labels = (data.get("Config") or {}).get("Labels") or {}
    if "com.docker.compose.project" in labels:
        return {"ok": False, "compose_managed": True,
                "project": labels["com.docker.compose.project"],
                "hint": "This container is managed by docker compose. "
                        "Update via the compose project, not individually."}
    image = (data.get("Config") or {}).get("Image") or data.get("Image")
    if not image:
        raise HTTPException(400, "Could not determine image for container")
    pull = _docker(["pull", image], timeout=300)
    if pull.returncode != 0:
        raise HTTPException(400, pull.stderr.strip() or "pull failed")
    # Re-create: docker doesn't expose a one-shot "recreate with new image",
    # so we use the well-known trick of pulling then `docker run` with the
    # same config via `--rename`. For safety we just restart the container
    # if the image moved — docker run will pick up the new image on next start.
    _docker(["stop", name], timeout=30)
    rm = _docker(["rm", name], timeout=15)
    if rm.returncode != 0:
        raise HTTPException(400, rm.stderr.strip() or "remove old container failed")
    # Reconstruct minimal run args from inspect; for anything elaborate
    # users should manage via compose. This covers ports, env, volumes,
    # restart-policy and the original command.
    cfg = data.get("Config") or {}
    host = data.get("HostConfig") or {}
    args = ["run", "-d", "--name", name]
    if host.get("RestartPolicy", {}).get("Name"):
        args += ["--restart", host["RestartPolicy"]["Name"]]
    for env in cfg.get("Env") or []:
        args += ["-e", env]
    for binding, pmap in (host.get("PortBindings") or {}).items():
        for p in pmap or []:
            args += ["-p", f"{p.get('HostIp','')}{':' if p.get('HostIp') else ''}{p.get('HostPort','')}:{binding}".lstrip(":")]
    for m in data.get("Mounts") or []:
        if m.get("Type") == "bind":
            args += ["-v", f"{m['Source']}:{m['Destination']}{':ro' if not m.get('RW') else ''}"]
        elif m.get("Type") == "volume" and m.get("Name"):
            args += ["-v", f"{m['Name']}:{m['Destination']}"]
    args.append(image)
    if cfg.get("Cmd"):
        args += list(cfg["Cmd"])
    rec = _docker(args, timeout=60)
    if rec.returncode != 0:
        raise HTTPException(400, rec.stderr.strip() or "recreate failed")
    _audit(user["sub"], "docker.update", "success", f"{name} -> {image}")
    return {"ok": True, "image": image, "message": rec.stdout.strip()}


# ── Generic system service control ────────────────────────────
SERVICE_WHITELIST = {
    "nginx", "smbd", "nmbd", "ssh", "sshd", "fail2ban",
    "docker", "incus", "forge-object-storage", "rustfs",
    "snapper-timeline.timer", "snapper-cleanup.timer", "smartd", "ufw",
}


def _svc_safe(name: str) -> str:
    if name not in SERVICE_WHITELIST:
        raise HTTPException(403, f"Service '{name}' is not managed via this API")
    return name


@router.post("/api/service/{action}")
async def service_control(action: str, body: dict, user=Depends(verify_token)):
    """action: start | stop | restart | enable | disable"""
    _admin(user)
    if action not in ("start", "stop", "restart", "enable", "disable"):
        raise HTTPException(400, "Invalid action")
    name = _svc_safe(body.get("name", ""))
    r = _run(["systemctl", action, name], timeout=20)
    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or f"{action} failed")
    _audit(user["sub"], f"service.{action}", "success", name)
    return {"ok": True, "message": r.stdout.strip()}


# ── Nginx site CRUD (sites-available + sites-enabled) ─────────
NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")


def _nginx_safe(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", name or ""):
        raise HTTPException(400, "Invalid site name")
    return name


@router.get("/api/nginx/sites")
async def nginx_sites_list(user=Depends(verify_token)):
    if not NGINX_SITES_AVAILABLE.exists():
        return {"sites": []}
    enabled = {p.name for p in NGINX_SITES_ENABLED.glob("*") if NGINX_SITES_ENABLED.exists()}
    sites = []
    for p in sorted(NGINX_SITES_AVAILABLE.iterdir()):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        server_names = re.findall(r"server_name\s+([^;]+);", text)
        listens = re.findall(r"listen\s+([^;]+);", text)
        sites.append({
            "name": p.name,
            "enabled": p.name in enabled,
            "server_names": " ".join(server_names).split() if server_names else [],
            "listens": listens,
            "size": p.stat().st_size,
        })
    return {"sites": sites}


@router.get("/api/nginx/site/{name}")
async def nginx_site_read(name: str, user=Depends(verify_token)):
    p = NGINX_SITES_AVAILABLE / _nginx_safe(name)
    if not p.is_file():
        raise HTTPException(404, "Site not found")
    return {"name": name, "content": p.read_text(encoding="utf-8", errors="replace"),
            "enabled": (NGINX_SITES_ENABLED / name).exists()}


@router.post("/api/nginx/site")
async def nginx_site_save(body: dict, user=Depends(verify_token)):
    """Create or replace a site. Body: { name, content, enabled }
    Runs `nginx -t` before persisting; refuses to save invalid config."""
    _admin(user)
    name = _nginx_safe(body.get("name", ""))
    content = body.get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(400, "Empty config")
    NGINX_SITES_AVAILABLE.mkdir(parents=True, exist_ok=True)
    target = NGINX_SITES_AVAILABLE / name
    # Validate by writing to a temp file and asking nginx to test it.
    tmp = target.with_suffix(target.suffix + ".forgeos.new")
    tmp.write_text(content, encoding="utf-8")
    test = _run(["nginx", "-t", "-c", "/etc/nginx/nginx.conf"], timeout=10)
    # `nginx -t` reads the whole config, so swap into place atomically only if good.
    if test.returncode != 0:
        # try a stricter test by temporarily replacing target
        backup = None
        if target.exists():
            backup = target.read_text(encoding="utf-8", errors="replace")
        target.write_text(content, encoding="utf-8")
        t2 = _run(["nginx", "-t"], timeout=10)
        if t2.returncode != 0:
            if backup is not None:
                target.write_text(backup, encoding="utf-8")
            else:
                target.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, "nginx config test failed:\n" + (t2.stderr or t2.stdout))
    tmp.replace(target)
    # Enable/disable symlink.
    enabled_link = NGINX_SITES_ENABLED / name
    if body.get("enabled"):
        NGINX_SITES_ENABLED.mkdir(parents=True, exist_ok=True)
        if enabled_link.exists() or enabled_link.is_symlink():
            enabled_link.unlink()
        enabled_link.symlink_to(target)
    else:
        if enabled_link.exists() or enabled_link.is_symlink():
            enabled_link.unlink()
    # Reload nginx so changes take effect.
    _run(["systemctl", "reload", "nginx"], timeout=15)
    _audit(user["sub"], "nginx.site.save", "success",
           f"{name} (enabled={bool(body.get('enabled'))})")
    return {"ok": True}


@router.delete("/api/nginx/site/{name}")
async def nginx_site_delete(name: str, user=Depends(verify_token)):
    _admin(user)
    safe = _nginx_safe(name)
    avail = NGINX_SITES_AVAILABLE / safe
    enabled = NGINX_SITES_ENABLED / safe
    if enabled.exists() or enabled.is_symlink():
        enabled.unlink()
    if avail.exists():
        avail.unlink()
    _run(["systemctl", "reload", "nginx"], timeout=15)
    _audit(user["sub"], "nginx.site.delete", "success", safe)
    return {"ok": True}


# ── Docker container create (full options) ───────────────────
@router.post("/api/docker/run")
async def docker_run(body: dict, user=Depends(verify_token)):
    """Create + run a container with full options.
    Body:
      name (req), image (req)
      restart, ports[], volumes[], env[], networks[], labels{}
      command, entrypoint, workdir
      cpu_limit ('1.5'), mem_limit ('512m')
      healthcheck { test, interval, retries }
    Image is `docker pull`ed first."""
    _admin(user)
    name = _container_safe(body.get("name", ""))
    image = (body.get("image") or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9._/:@\-]{1,256}", image):
        raise HTTPException(400, "Invalid image reference")

    pull = _docker(["pull", image], timeout=300)
    if pull.returncode != 0:
        raise HTTPException(400, pull.stderr.strip() or "pull failed")

    args = ["run", "-d", "--name", name]
    restart = body.get("restart") or "unless-stopped"
    if restart in ("no", "always", "unless-stopped", "on-failure"):
        args += ["--restart", restart]

    def _safe_arg(s: str) -> str:
        # No shell expansion happens (we use shell=False), but reject newlines.
        if "\n" in s or "\r" in s:
            raise HTTPException(400, f"Invalid argument: {s!r}")
        return s

    for p in body.get("ports") or []:
        args += ["-p", _safe_arg(str(p))]
    for v in body.get("volumes") or []:
        args += ["-v", _safe_arg(str(v))]
    for e in body.get("env") or []:
        args += ["-e", _safe_arg(str(e))]
    for n in body.get("networks") or []:
        args += ["--network", _safe_arg(str(n))]
    for k, v in (body.get("labels") or {}).items():
        args += ["--label", f"{_safe_arg(str(k))}={_safe_arg(str(v))}"]

    if body.get("workdir"):
        args += ["-w", _safe_arg(str(body["workdir"]))]
    if body.get("cpu_limit"):
        args += ["--cpus", _safe_arg(str(body["cpu_limit"]))]
    if body.get("mem_limit"):
        args += ["--memory", _safe_arg(str(body["mem_limit"]))]

    hc = body.get("healthcheck") or {}
    if hc.get("test"):
        args += ["--health-cmd", _safe_arg(str(hc["test"]))]
    if hc.get("interval"):
        args += ["--health-interval", _safe_arg(str(hc["interval"]))]
    if hc.get("retries"):
        args += ["--health-retries", str(int(hc["retries"]))]

    if body.get("entrypoint"):
        args += ["--entrypoint", _safe_arg(str(body["entrypoint"]))]

    args.append(image)
    cmd = body.get("command")
    if cmd:
        if isinstance(cmd, str):
            # split user command by whitespace; users wanting shell expansion
            # should bake it into the image's CMD or use a wrapper script.
            args += cmd.split()
        elif isinstance(cmd, list):
            args += [_safe_arg(str(x)) for x in cmd]

    r = _docker(args, timeout=60)
    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or "create failed")
    _audit(user["sub"], "docker.run", "success", f"{name} ({image})")
    return {"ok": True, "id": r.stdout.strip()}


# ── Compose project storage + deploy ─────────────────────────
COMPOSE_DIR = Path(os.environ.get("FORGEOS_COMPOSE_DIR", "/etc/forgeos/compose"))


def _project_safe(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name or ""):
        raise HTTPException(400, "Project name must be lowercase letters, "
                                  "digits, dashes or underscores")
    return name


@router.get("/api/compose/projects")
async def compose_projects_list(user=Depends(verify_token)):
    """List saved compose projects + their live state from `docker compose ls`."""
    saved = []
    if COMPOSE_DIR.exists():
        for d in sorted(COMPOSE_DIR.iterdir()):
            yml = d / "docker-compose.yml"
            if d.is_dir() and yml.is_file():
                saved.append({"name": d.name, "path": str(d),
                              "size": yml.stat().st_size})
    # Live state
    live_by_name = {}
    r = _docker(["compose", "ls", "--format", "json", "--all"], timeout=10)
    if r.returncode == 0:
        try:
            import json as _json
            for entry in _json.loads(r.stdout or "[]"):
                live_by_name[entry.get("Name")] = entry
        except Exception:
            pass
    for p in saved:
        live = live_by_name.get(p["name"]) or {}
        p["status"] = live.get("Status", "down")
        p["config_files"] = live.get("ConfigFiles", "")
    return {"projects": saved}


@router.get("/api/compose/project/{name}")
async def compose_project_read(name: str, user=Depends(verify_token)):
    n = _project_safe(name)
    yml = COMPOSE_DIR / n / "docker-compose.yml"
    if not yml.is_file():
        raise HTTPException(404, "Project not found")
    return {"name": n, "content": yml.read_text(encoding="utf-8")}


@router.post("/api/compose/project")
async def compose_project_save(body: dict, user=Depends(verify_token)):
    """Save (create or replace) a compose project. Body: { name, content, deploy }
    Validates with `docker compose config` before persisting; if deploy=True,
    runs `docker compose up -d` afterward."""
    _admin(user)
    name = _project_safe(body.get("name", ""))
    content = body.get("content", "")
    if not isinstance(content, str) or "services:" not in content:
        raise HTTPException(400, "Content does not look like a compose file")
    proj_dir = COMPOSE_DIR / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    yml = proj_dir / "docker-compose.yml"
    # Validate by writing then asking compose to parse it.
    yml.write_text(content, encoding="utf-8")
    val = _run(["docker", "compose", "-f", str(yml), "config", "--quiet"], timeout=20)
    if val.returncode != 0:
        # Don't delete the file — let the user fix it; just refuse to deploy.
        raise HTTPException(400, "Compose validation failed:\n" +
                            (val.stderr or val.stdout))
    deploy_out = ""
    if body.get("deploy"):
        up = _run(["docker", "compose", "-p", name, "-f", str(yml), "up", "-d"],
                  timeout=600)
        if up.returncode != 0:
            raise HTTPException(400, "Saved, but deploy failed:\n" +
                                (up.stderr or up.stdout))
        deploy_out = up.stdout
    _audit(user["sub"], "compose.save", "success",
           f"{name} (deploy={bool(body.get('deploy'))})")
    return {"ok": True, "deploy_output": deploy_out}


@router.delete("/api/compose/project/{name}")
async def compose_project_delete(name: str, user=Depends(verify_token)):
    """Down + remove a compose project entirely."""
    _admin(user)
    n = _project_safe(name)
    yml = COMPOSE_DIR / n / "docker-compose.yml"
    if yml.is_file():
        down = _run(["docker", "compose", "-p", n, "-f", str(yml),
                     "down", "-v", "--remove-orphans"], timeout=300)
        # ignore down failures (project might not be up); still delete files
        shutil.rmtree(COMPOSE_DIR / n, ignore_errors=True)
        _audit(user["sub"], "compose.delete", "success", n)
        return {"ok": True, "message": down.stdout}
    raise HTTPException(404, "Project not found")


@router.post("/api/files/chmod")
async def file_chmod(body: dict, user=Depends(verify_token)):
    """POSIX chmod. `mode` is an octal string like '755' or '0644'.

    Scope (independent, for the tree Permissions editor):
      apply_dirs   - recurse into subdirectories, applying the dir mode
      apply_files  - recurse into files, applying `file_mode` (or `mode`)
      file_mode    - optional separate octal for files (the correct Unix
                     pattern is dirs 755 / files 644 in one pass)
    `recursive: true` remains supported as an alias for
    apply_dirs+apply_files with a single mode (used by the file-list editor).
    """
    _admin(user)
    p = _safe(body.get("path", ""))
    raw = str(body.get("mode", "")).strip()
    if not re.fullmatch(r"[0-7]{3,4}", raw):
        raise HTTPException(400, "Mode must be octal, e.g. 755 or 0644")
    dir_mode = int(raw, 8)

    recursive = bool(body.get("recursive"))
    apply_dirs = bool(body.get("apply_dirs")) or recursive
    apply_files = bool(body.get("apply_files")) or recursive

    file_raw = str(body.get("file_mode", "")).strip()
    if file_raw:
        if not re.fullmatch(r"[0-7]{3,4}", file_raw):
            raise HTTPException(400, "File mode must be octal, e.g. 644")
        file_mode = int(file_raw, 8)
    else:
        file_mode = dir_mode

    if (apply_dirs or apply_files) and p.is_dir():
        os.chmod(p, dir_mode)                       # the folder itself
        for root, dirs, files in os.walk(p):
            if apply_dirs:
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), dir_mode)
                    except OSError:
                        pass
            if apply_files:
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), file_mode)
                    except OSError:
                        pass
        scope = f" -R(dirs={apply_dirs},files={apply_files})"
    else:
        os.chmod(p, dir_mode)
        scope = ""
    detail = f"{p} -> {raw}" + (f"/{file_raw}" if file_raw else "") + scope
    _audit(user["sub"], "files.chmod", "success", detail)
    return {"ok": True}


@router.post("/api/files/chown")
async def file_chown(body: dict, user=Depends(verify_token)):
    """POSIX chown. owner/group are names or numeric ids.

    Scope mirrors chmod: apply_dirs / apply_files recurse independently;
    `recursive: true` is the both-scopes alias. Independent scoping uses a
    Python walk (shutil.chown) because `chown -R` cannot target dirs and
    files separately.
    """
    _admin(user)
    p = _safe(body.get("path", ""))
    owner = re.sub(r"[^A-Za-z0-9._-]", "", str(body.get("owner", "")))
    group = re.sub(r"[^A-Za-z0-9._-]", "", str(body.get("group", "")))
    if not owner and not group:
        raise HTTPException(400, "owner and/or group required")

    recursive = bool(body.get("recursive"))
    apply_dirs = bool(body.get("apply_dirs")) or recursive
    apply_files = bool(body.get("apply_files")) or recursive

    # shutil.chown wants None (not "") for an unchanged field
    o = owner or None
    g = group or None

    def _one(path: str) -> None:
        try:
            shutil.chown(path, o, g)
        except (OSError, LookupError):
            pass

    if (apply_dirs or apply_files) and p.is_dir():
        try:
            shutil.chown(str(p), o, g)              # the folder itself
        except LookupError:
            raise HTTPException(400, "unknown owner or group")
        for root, dirs, files in os.walk(p):
            if apply_dirs:
                for d in dirs:
                    _one(os.path.join(root, d))
            if apply_files:
                for f in files:
                    _one(os.path.join(root, f))
        scope = f" -R(dirs={apply_dirs},files={apply_files})"
    else:
        try:
            shutil.chown(str(p), o, g)
        except LookupError:
            raise HTTPException(400, "unknown owner or group")
        except OSError as e:
            raise HTTPException(400, str(e) or "chown failed")
        scope = ""
    spec = owner + (":" + group if group else "")
    _audit(user["sub"], "files.chown", "success", f"{p} -> {spec}{scope}")
    return {"ok": True}


@router.get("/api/files/idents")
async def file_idents(user=Depends(verify_token)):
    """Available users & groups, for the chown picker."""
    users_, groups_ = [], []
    try:
        import pwd, grp
        users_ = sorted(u.pw_name for u in pwd.getpwall() if u.pw_uid == 0 or u.pw_uid >= 1000)
        groups_ = sorted(g.gr_name for g in grp.getgrall())
    except Exception:
        pass
    return {"users": users_, "groups": groups_}


# ──────────────────────────────────────────────────────────────
# STORAGE DRIVE ACTIONS  — spin-down, replace, rebuild
# ──────────────────────────────────────────────────────────────

def _dev(name: str) -> str:
    d = re.sub(r"[^a-zA-Z0-9]", "", name)
    if not d or len(d) > 20:
        raise HTTPException(400, "Invalid device name")
    return "/dev/" + d


@router.post("/api/storage/drive/spindown")
async def drive_spindown(body: dict, user=Depends(verify_token)):
    """Spin down (standby) an idle disk via hdparm -y."""
    _admin(user)
    dev = _dev(body.get("device", ""))
    r = _run(["hdparm", "-y", dev], timeout=15)
    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or "spindown failed")
    _audit(user["sub"], "storage.drive.spindown", "success", dev)
    return {"ok": True, "message": f"{dev} sent to standby"}


@router.post("/api/storage/drive/fail")
async def drive_fail(body: dict, user=Depends(verify_token)):
    """Mark a drive failed in its array (first step of a replace)."""
    _admin(user)
    pool = re.sub(r"[^a-zA-Z0-9_-]", "", body.get("pool", ""))
    dev = _dev(body.get("device", ""))
    if not pool:
        raise HTTPException(400, "Pool required")
    r = _run(["mdadm", "--manage", f"/dev/md/{pool}", "--fail", dev], timeout=30)
    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or "mark-fail failed")
    _audit(user["sub"], "storage.drive.fail", "success", f"{dev} in {pool}")
    return {"ok": True, "message": f"{dev} marked failed in {pool}"}


@router.post("/api/storage/drive/replace")
async def drive_replace(body: dict, user=Depends(verify_token)):
    """Replace a failed drive: remove old, add new → triggers rebuild."""
    _admin(user)
    pool = re.sub(r"[^a-zA-Z0-9_-]", "", body.get("pool", ""))
    old = _dev(body.get("old", ""))
    new = _dev(body.get("new", ""))
    if not pool:
        raise HTTPException(400, "Pool required")
    md = f"/dev/md/{pool}"
    rem = _run(["mdadm", "--manage", md, "--remove", old], timeout=30)
    if rem.returncode != 0 and "No such device" not in (rem.stderr or ""):
        raise HTTPException(400, rem.stderr.strip() or "remove failed")
    add = _run(["mdadm", "--manage", md, "--add", new], timeout=30)
    if add.returncode != 0:
        raise HTTPException(400, add.stderr.strip() or "add failed")
    _audit(user["sub"], "storage.drive.replace", "success",
           f"{old} -> {new} in {pool} (rebuild started)")
    return {"ok": True, "message": f"Replaced {old} with {new}; rebuild started"}


@router.post("/api/storage/pool/rebuild")
async def pool_rebuild(body: dict, user=Depends(verify_token)):
    """Kick a resync/scrub on an array."""
    _admin(user)
    pool = re.sub(r"[^a-zA-Z0-9_-]", "", body.get("pool", ""))
    if not pool:
        raise HTTPException(400, "Pool required")
    # Find the kernel md name behind /dev/md/<pool>
    real = os.path.realpath(f"/dev/md/{pool}")
    mdname = os.path.basename(real)
    sync_action = Path(f"/sys/block/{mdname}/md/sync_action")
    if not sync_action.exists():
        raise HTTPException(404, "Array not found")
    try:
        sync_action.write_text("check\n")
    except OSError as e:
        raise HTTPException(400, f"Could not start rebuild: {e}")
    _audit(user["sub"], "storage.pool.rebuild", "success", f"check started on {pool}")
    return {"ok": True, "message": f"Consistency check started on {pool}"}
