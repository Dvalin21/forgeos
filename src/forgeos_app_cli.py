"""forgeos-app — ForgeOS app-store CLI (importable; console_scripts entry).

The real CLI used by the installed `forgeos-app` command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import forgeos_config as fc
from forgeos_appstore_exec import AppStore, AppStoreError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forgeos-app")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    sub.add_parser("list")
    sub.add_parser("catalog")
    sub.add_parser("status")
    p_inst = sub.add_parser("install"); p_inst.add_argument("app_id")
    p_un = sub.add_parser("uninstall"); p_un.add_argument("app_id")
    p_un.add_argument("--remove-data", action="store_true")
    args = ap.parse_args(argv)

    store = AppStore()
    try:
        if args.cmd == "sync":
            store.sync_catalog(); print("\u2713 catalog synced"); return 0
        if args.cmd in ("list", "status"):
            cfg = fc.load()
            if not cfg.apps:
                print("No apps installed."); return 0
            for a in cfg.apps:
                state = "enabled" if a.enabled else "disabled"
                print(f"  {a.id:20} v{a.version or '?':12} port {a.webui_port}  [{state}]")
            return 0
        if args.cmd == "catalog":
            cat = Path(store.catalog_dir) / "catalog.json"
            if not cat.exists():
                print("Catalog not synced. Run: forgeos-app sync", file=sys.stderr); return 1
            for app in json.loads(cat.read_text()).get("apps", []):
                print(f"  {app['id']:20} {app.get('tagline','')}")
            return 0
        if args.cmd == "install":
            plan = store.install(args.app_id)
            print(f"\u2713 installed {plan.app_id} (port {plan.webui_port})")
            print(f"  URL: https://{plan.vhost_domain}")
            return 0
        if args.cmd == "uninstall":
            store.uninstall(args.app_id, remove_data=args.remove_data)
            print(f"\u2713 uninstalled {args.app_id}"
                  f"{' (data removed)' if args.remove_data else ' (data kept)'}")
            return 0
    except AppStoreError as e:
        print(f"error: {e}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
