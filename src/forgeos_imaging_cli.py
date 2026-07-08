"""forgeos-imaging — root CLI for the native UrBackup server."""
from __future__ import annotations

import argparse
import json
import sys

import forgeos_imaging as fim


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forgeos-imaging")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("install")
    p_un = sub.add_parser("uninstall")
    p_un.add_argument("--purge", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "status":
            print(json.dumps(fim.status(), indent=2)); return 0
        if args.cmd == "install":
            st = fim.install()
            print(f"\u2713 urbackup-server {st['version']} installed and running: {st['running']}")
            print(f"  URL: {st['url']}  (set the backup storage path in UrBackup's Settings)")
            return 0
        if args.cmd == "uninstall":
            fim.uninstall(purge=args.purge)
            print("\u2713 urbackup-server removed"); return 0
    except fim.ImagingError as e:
        print(f"error: {e}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
