#!/usr/bin/env python3
"""forgeos-generate — render + apply ForgeOS service config from the config DB.

Usage:
  forgeos-generate all            render+apply every service
  forgeos-generate samba          render+apply one service
  forgeos-generate --list         list known services
  forgeos-generate <svc> --dry    show what WOULD be written, change nothing

This is what the web UI calls after writing the config DB (e.g. when the
security profile changes). Idempotent and re-runnable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forgeos_config as fc  # noqa: E402
from generators import registry  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="forgeos-generate")
    ap.add_argument("service", nargs="?", help="service name or 'all'")
    ap.add_argument("--list", action="store_true", help="list known services")
    ap.add_argument("--dry", action="store_true", help="show rendered output, write nothing")
    ap.add_argument("--no-reload", action="store_true", help="write files but don't reload services")
    args = ap.parse_args(argv)

    if args.list:
        for n in registry.names():
            print(n)
        return 0

    if not args.service:
        ap.error("specify a service name or 'all' (or --list)")

    cfg = fc.load()

    if args.dry:
        return _dry_run(args.service, cfg)

    do_reload = not args.no_reload
    if args.service == "all":
        results = registry.apply_all(cfg=cfg, do_reload=do_reload)
    else:
        try:
            results = [registry.apply_one(args.service, cfg=cfg, do_reload=do_reload)]
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    failures = 0
    for r in results:
        if r.ok:
            print(f"✓ {r.service}: applied ({len(r.written)} file(s))")
        else:
            failures += 1
            print(f"✗ {r.service}: {r.error}", file=sys.stderr)
    return 1 if failures else 0


def _dry_run(service: str, cfg) -> int:
    targets = registry.names() if service == "all" else [service]
    for name in targets:
        try:
            gen = registry.get(name)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        files = gen.render(cfg)
        if not files:
            print(f"# {name}: (disabled / nothing to render)")
            continue
        for rf in files:
            print(f"# ===== {name}: {rf.path} (mode {oct(rf.mode)}) =====")
            print(rf.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
