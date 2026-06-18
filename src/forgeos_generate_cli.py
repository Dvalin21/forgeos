"""forgeos-generate — render + apply ForgeOS service config from the config DB.

Importable module (valid name) so it can be a console_scripts entry point.
This is the real CLI used by the installed `forgeos-generate` command.
"""

from __future__ import annotations

import argparse
import sys

import forgeos_config as fc
from generators import registry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forgeos-generate")
    ap.add_argument("service", nargs="?", help="service name or 'all'")
    ap.add_argument("--list", action="store_true", help="list known services")
    ap.add_argument("--dry", action="store_true", help="show rendered output, write nothing")
    ap.add_argument("--no-reload", action="store_true", help="write files but don't reload")
    args = ap.parse_args(argv)

    if args.list:
        for n in registry.names():
            print(n)
        return 0

    if not args.service:
        ap.error("specify a service name or 'all' (or --list)")

    # load_and_upgrade: if this box has an older-schema config.json, migrate it
    # up and persist the upgrade once (V-012). forgeos-generate runs on every
    # apply, so this is the natural place an existing box gets upgraded.
    cfg = fc.load_and_upgrade()

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
            print(f"\u2713 {r.service}: applied ({len(r.written)} file(s))")
        else:
            failures += 1
            print(f"\u2717 {r.service}: {r.error}", file=sys.stderr)
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
