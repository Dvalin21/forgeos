#!/usr/bin/env python3
"""forgeos-app — ForgeOS app-store command-line interface.

Usage:
  forgeos-app sync                 sync the catalog (git clone/pull)
  forgeos-app list                 list installed apps
  forgeos-app catalog              list available apps in the catalog
  forgeos-app install <app-id>     install an app
  forgeos-app uninstall <app-id>   uninstall an app (keeps data)
  forgeos-app uninstall <app-id> --remove-data
  forgeos-app status               show installed apps + ports
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forgeos_config as fc  # noqa: E402
from forgeos_appstore_exec import AppStore, AppStoreError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="forgeos-app")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync", help="sync the catalog")
    sub.add_parser("list", help="list installed apps")
    sub.add_parser("catalog", help="list available apps in the catalog")
    sub.add_parser("status", help="show installed apps + ports")

    p_inst = sub.add_parser("install", help="install an app")
    p_inst.add_argument("app_id")

    p_uninst = sub.add_parser("uninstall", help="uninstall an app")
    p_uninst.add_argument("app_id")
    p_uninst.add_argument("--remove-data", action="store_true")

    args = ap.parse_args(argv)
    store = AppStore()

    try:
        if args.cmd == "sync":
            store.sync_catalog()
            print("✓ catalog synced")
            return 0

        if args.cmd in ("list", "status"):
            cfg = fc.load()
            if not cfg.apps:
                print("No apps installed.")
                return 0
            for a in cfg.apps:
                state = "enabled" if a.enabled else "disabled"
                print(f"  {a.id:20} v{a.version or '?':12} port {a.webui_port}  [{state}]")
            return 0

        if args.cmd == "catalog":
            cat = Path(store.catalog_dir) / "catalog.json"
            if not cat.exists():
                print("Catalog not synced. Run: forgeos-app sync", file=sys.stderr)
                return 1
            data = json.loads(cat.read_text())
            for app in data.get("apps", []):
                print(f"  {app['id']:20} {app.get('tagline','')}")
            return 0

        if args.cmd == "install":
            plan = store.install(args.app_id)
            print(f"✓ installed {plan.app_id} (port {plan.webui_port})")
            print(f"  URL: https://{plan.vhost_domain}")
            return 0

        if args.cmd == "uninstall":
            store.uninstall(args.app_id, remove_data=args.remove_data)
            msg = " (data removed)" if args.remove_data else " (data kept)"
            print(f"✓ uninstalled {args.app_id}{msg}")
            return 0

    except AppStoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
