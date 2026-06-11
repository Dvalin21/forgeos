# ForgeOS v2 — Config-DB + Generator Design

The core of v2: a single source of truth (config DB) and a generator that
renders every service's config files and manages the service. Replaces
inline `cat > /etc/...conf <<EOF` in bash.

## Why
Every install failure of the "heredoc to a missing dir", "hand-written
config drifts from user choice", "generated CLI has a syntax error" class
comes from bash modules writing config imperatively. OMV solved this with a
config DB (omv-confdbadm) + a deploy/generator step (omv-salt). We do the
same, lighter, in Python (matches the existing API stack).

## Components

### Config DB
- Storage: single JSON document at /etc/forgeos/config.json (0600).
  Human-inspectable, trivial to back up, no daemon. Migrate to sqlite later
  if it grows.
- Schema: validated by pydantic. Invalid config rejected at WRITE time.
- Access: forgeos_config module — load(), save(), typed models. The web API
  imports it directly, so a UI change writes the DB then triggers a render.

### Generator
- One renderer per service, common interface:
    class ServiceGenerator:
        name: str
        def render(self, cfg) -> list[RenderedFile]   # pure: cfg -> files
        def apply(self) -> None                        # mkdir -p, write, reload
        def validate(self, files) -> None              # optional pre-apply check
        def reload(self) -> None
- render() is PURE (returns file contents as data) — unit-testable without
  touching the system. apply() mkdir -p's every parent BEFORE writing (kills
  the "no such file or directory" class), writes atomically (temp + replace),
  sets mode. Templates: Jinja2 (trim_blocks=True, lstrip_blocks=False).

### Registry + CLI
- generators/registry.py knows every generator; apply_one / apply_all.
  apply_all isolates per-service failure (ok=False + captured error) so one
  bad generator never aborts the rest.
- forgeos-generate CLI: all | <svc> | --list | --dry | --no-reload. What the
  web UI calls after writing the config DB.

## Proven on (all green)
- samba: smb.conf + shares file, testparm validate, reload smbd.
- nginx: vhosts derived from enabled services, snakeoil cert fallback,
  nginx -t before reload.
- security: Low/Med/High declarative tier matrix.
- wireguard: peer metadata in DB, server key in keystore, whole-file regen.
- nfs: /etc/exports from export types.

## Status
244-test core proven; full base on the pattern. 86 v2 tests total.
