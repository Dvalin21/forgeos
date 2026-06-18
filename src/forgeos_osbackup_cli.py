"""CLI for ForgeOS bare-metal DR (ReaR). Exposes the OsBackupRunner so an
operator can enable the schedule, run a backup by hand, or disable it —
without needing to know the systemd unit names.

Subcommands:
  forgeos-osbackup run                 run a backup now (rear mkbackup)
  forgeos-osbackup enable [--at SPEC]  enable the scheduled backup timer
  forgeos-osbackup disable             disable the scheduled backup timer
  forgeos-osbackup status              show whether DR is configured/enabled
"""
import argparse
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))

import forgeos_config as fc            # noqa: E402
from forgeos_osbackup import OsBackupRunner  # noqa: E402


def _require_rear() -> str | None:
    import shutil
    return None if shutil.which("rear") else (
        "rear is not installed — install the 'rear' package (it is in the "
        "ForgeOS base package set; reinstall or `apt-get install rear`)."
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forgeos-osbackup",
                                 description="ForgeOS bare-metal disaster recovery (ReaR)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run a backup now (rear mkbackup)")
    p_en = sub.add_parser("enable", help="enable the scheduled backup timer")
    p_en.add_argument("--at", default="*-*-* 02:00:00",
                      help="systemd OnCalendar spec (default: daily 02:00)")
    sub.add_parser("disable", help="disable the scheduled backup timer")
    sub.add_parser("status", help="show DR config + whether it's enabled")
    args = ap.parse_args(argv)

    cfg = fc.load()
    ob = cfg.osbackup

    if args.cmd == "status":
        print(f"osbackup enabled in config: {ob.enabled}")
        print(f"output: {ob.output}   backup_path: {ob.backup_path}")
        print(f"rear installed: {_require_rear() is None}")
        print(f"config: /etc/rear/local.conf "
              f"({'present' if Path('/etc/rear/local.conf').exists() else 'NOT rendered — run forgeos-generate osbackup'})")
        return 0

    if not ob.enabled and args.cmd in ("run", "enable"):
        ap.error("osbackup is disabled in the config DB. Enable it "
                 "(set osbackup.enabled) and run `forgeos-generate osbackup` "
                 "first so /etc/rear/local.conf exists.")

    runner = OsBackupRunner()

    if args.cmd == "run":
        err = _require_rear()
        if err:
            print(err, file=sys.stderr)
            return 2
        if not Path("/etc/rear/local.conf").exists():
            print("/etc/rear/local.conf missing — run `forgeos-generate osbackup` first",
                  file=sys.stderr)
            return 2
        ok = runner.run_backup(
            cloud_sync=bool(ob.cloud_sync),
            cloud_remote=getattr(ob, "cloud_remote", ""),
            backup_path=ob.backup_path,
        )
        print("backup OK" if ok else "backup FAILED", file=sys.stderr if not ok else sys.stdout)
        return 0 if ok else 1

    if args.cmd == "enable":
        runner.setup_timer(args.at)
        print(f"osbackup timer enabled ({args.at})")
        return 0

    if args.cmd == "disable":
        runner.disable_timer()
        print("osbackup timer disabled")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
