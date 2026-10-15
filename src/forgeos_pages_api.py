"""
ForgeOS — additional API surface for the DSM-style web UI.

Mounts under the existing FastAPI app via:

    from forgeos_pages_api import router as pages_router
    app.include_router(pages_router)

Provides endpoints the original API was missing:
  • File Station   — browse / read / write / upload / mkdir / rename / delete,
                     scoped strictly to the storage-pool roots (nothing on the OS disk).
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

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

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
#
# The roots ARE the storage pools: /srv/<pool> and below. The pool is the
# only user-data location on the box — nothing user-facing lives on the OS
# disk. No pools yet → no roots, and the UI shows "create a pool first"
# rather than exposing the OS filesystem.
_FILE_ROOTS_ENV = os.environ.get("FORGEOS_FILE_ROOTS", "").strip()


def _allowed_roots() -> list[Path]:
    if _FILE_ROOTS_ENV:                     # explicit operator override
        return [Path(p).resolve() for p in _FILE_ROOTS_ENV.split(":") if p.strip()]
    try:
        import forgeos_config as _fc
        return [Path(p.resolved_mountpoint()).resolve()
                for p in _fc.load().storage.pools]
    except Exception:
        return []


def _safe(path: str) -> Path:
    """Resolve `path` and guarantee it stays within an allowed root."""
    roots = _allowed_roots()
    if not roots:
        raise HTTPException(
            409, "No storage pool yet — create one first; all files live on it.")
    if not path:
        path = str(roots[0])
    p = Path(path)
    if not p.is_absolute():
        p = roots[0] / p
    rp = p.resolve()
    for root in roots:
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
    """Top-level roots the browser is allowed to enter — the storage pools."""
    return {"roots": [str(r) for r in _allowed_roots()]}


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
    roots = _allowed_roots()
    root = next((r for r in roots if r == d or r in d.parents), roots[0] if roots else d)
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
    if p in _allowed_roots():
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


# Units this API may control. `systemctl` driven from a web request is a
# privilege-escalation surface if unbounded (stop sshd, mask systemd…), so
# the set is explicit. wg-quick@<iface> instances are prefix-matched because
# the interface name varies. Keep in step with system_api's /api/services
# list — a unit the UI shows must be controllable here.
SERVICE_WHITELIST = {
    "docker", "smbd", "nmbd", "nginx", "fail2ban", "smartd",
    "postfix", "redis-server", "avahi-daemon", "incus",
    "nfs-kernel-server", "forgeos-api", "forgeos-mdns-alias",
    "forgeos-rustfs", "forgeos-scrub", "forgeos-scrub.timer",
    "forgeos-lhsr-snapshot", "forgeos-lhsr-snapshot.timer",
}
_WG_PREFIX = "wg-quick@"


def _svc_safe(name: str) -> str:
    if name not in SERVICE_WHITELIST and not name.startswith(_WG_PREFIX):
        raise HTTPException(403, f"Service '{name}' is not managed via this API")
    return name


def _systemctl_async(args: list[str]) -> None:
    """Fire-and-forget systemctl. A blocking call from inside the very unit
    it restarts is SIGKILLed when systemd tears down the old cgroup — rc=-9
    with empty stderr, so the action succeeded but the caller saw a failure.
    --no-block does not help (the job starts immediately). The HTTP response
    has to be out before the unit dies, so detach the call."""
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


@router.post("/api/service/{action}")
async def service_control(action: str, body: dict, user=Depends(verify_token)):
    """action: start | stop | restart | enable | disable"""
    _admin(user)
    if action not in ("start", "stop", "restart", "enable", "disable"):
        raise HTTPException(400, "Invalid action")
    name = _svc_safe(body.get("name", ""))
    _systemctl_async(["systemctl", action, name])
    _audit(user["sub"], f"service.{action}", "success", name)
    return {"ok": True, "message": f"{name}: {action} requested"}


# ── Docker container create (full options) ───────────────────

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
        if apply_dirs:
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


def _storage_pool_mount(pool: str) -> str:
    """Resolve a pool name to its mounted btrfs mountpoint. Delegates to
    storage_api's resolver so the config lookup + mounted-check live in one
    place (btrfs device ops are anchored on the mountpoint, not /dev/md)."""
    import storage_api  # type: ignore
    return storage_api._pool_mount(pool)


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
    """btrfs has no explicit 'fail a device' step like mdadm — you replace a
    device directly (online) or remove a missing one in degraded mount. This
    endpoint is kept for API compatibility but returns guidance rather than
    running a non-existent operation."""
    _admin(user)
    raise HTTPException(409, "btrfs pools don't 'fail' a device — use Replace "
                             "to swap a drive online, which rebuilds "
                             "redundancy automatically")


@router.post("/api/storage/drive/replace")
async def drive_replace(body: dict, user=Depends(verify_token)):
    """Replace a drive in a btrfs pool via `btrfs replace start` — online, no
    unmount, redundancy rebuilt automatically.

    If the old device is still present it's named directly; if it's gone
    (physically failed/removed), pass its btrfs devid and this uses -r to
    rebuild the replacement purely from RAID redundancy. The target must be
    the same size or larger than the source.
    """
    _admin(user)
    pool = re.sub(r"[^a-zA-Z0-9_-]", "", body.get("pool", ""))
    old_raw = str(body.get("old", "")).strip()
    new = _dev(body.get("new", ""))
    if not pool:
        raise HTTPException(400, "Pool required")
    mount = _storage_pool_mount(pool)

    # old is either a device name (present disk) or a numeric devid (missing)
    args = ["btrfs", "replace", "start", "-B"]      # -B = foreground, report result
    if old_raw.isdigit():
        args += ["-r", old_raw, new, mount]         # rebuild from redundancy
    else:
        old = _dev(old_raw)
        if not Path(old).exists():
            raise HTTPException(400, f"{old} is not present; pass its btrfs "
                                     f"devid instead to replace a missing disk")
        args += [old, new, mount]
    r = _run(args, timeout=30)
    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or "btrfs replace failed")
    _audit(user["sub"], "storage.drive.replace", "success",
           f"{old_raw} -> {new} in {pool} ({mount})")
    # keep config's device list truthful after the swap (see add_drive note)
    try:
        import storage_api  # type: ignore
        cfg = storage_api.fc.load()
        match = next((p for p in cfg.storage.pools if p.name == pool), None)
        if match is not None:
            if not old_raw.isdigit():
                old_path = _dev(old_raw)
                match.devices = [d for d in match.devices if d != old_path]
            if new not in match.devices:
                match.devices.append(new)
            storage_api.fc.save(cfg)
    except Exception:
        pass                         # config sync is best-effort; the swap succeeded
    return {"ok": True, "message": f"Replacing {old_raw} with {new}; "
                                   f"btrfs is rebuilding redundancy"}


@router.post("/api/storage/pool/rebuild")
async def pool_rebuild(body: dict, user=Depends(verify_token)):
    """Run a btrfs scrub — reads all data/metadata and verifies checksums,
    repairing from the good copy on a redundant profile. This is the btrfs
    equivalent of an mdadm consistency check, online and safe."""
    _admin(user)
    pool = re.sub(r"[^a-zA-Z0-9_-]", "", body.get("pool", ""))
    if not pool:
        raise HTTPException(400, "Pool required")
    mount = _storage_pool_mount(pool)
    r = _run(["btrfs", "scrub", "start", mount], timeout=20)
    if r.returncode != 0:
        raise HTTPException(400, r.stderr.strip() or "Could not start scrub")
    _audit(user["sub"], "storage.pool.rebuild", "success",
           f"scrub started on {pool} ({mount})")
    return {"ok": True, "message": f"Consistency check (scrub) started on {pool}"}
