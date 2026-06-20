"""CLI for ForgeOS storage pools (btrfs), guarded by forgeos_diskprep.

  forgeos-storage disks                 list disks + which are usable/system
  forgeos-storage plan  NAME LEVEL D... show what creating a pool WOULD do
  forgeos-storage create NAME LEVEL D... actually create the pool (guarded)
  forgeos-storage list                  list configured pools
  forgeos-storage status                pools + mount state

A user should NEVER run mkfs/parted by hand — this is the safe path. Every
create re-checks the guards (system disk untouchable, etc.) right before
writing, and records the pool in the config-DB by UUID.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forgeos_config as fc            # noqa: E402
import forgeos_diskprep as dp          # noqa: E402


def _resolve(disk_idents):
    disks = dp.inspect_disks()
    return [dp.find_disk(disks, i) for i in disk_idents], disks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forgeos-storage",
                                 description="ForgeOS btrfs storage pools (guarded)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("disks", help="list disks + usable/system status")
    sub.add_parser("list", help="list configured pools")
    sub.add_parser("status", help="pools + mount state")

    for cmd in ("plan", "create"):
        p = sub.add_parser(cmd, help=f"{cmd} a btrfs pool")
        p.add_argument("name")
        p.add_argument("level", help="single|raid0|raid1|raid10|raid5|raid6")
        p.add_argument("disks", nargs="+", help="disk identifiers (sda, /dev/sdc, by-id)")
        p.add_argument("--mountpoint", default="")
        p.add_argument("--force", action="store_true",
                       help="allow wiping a disk that has a table/fs (NEVER the system disk)")

    args = ap.parse_args(argv)

    if args.cmd == "disks":
        for d in dp.inspect_disks():
            tag = ("SYSTEM (never usable)" if d.is_system else
                   "mounted" if d.mounted else
                   "in-array" if d.in_array else
                   "has-data (needs --force)" if (d.has_partition_table or d.has_filesystem) else
                   "BLANK (usable)")
            gb = d.size_bytes / (1024**3)
            print(f"  {d.path:12} {gb:6.1f}G  {tag}")
        return 0

    if args.cmd in ("list", "status"):
        cfg = fc.load()
        if not cfg.storage.pools:
            print("no pools configured")
            return 0
        for p in cfg.storage.pools:
            line = f"  {p.name}  {p.raid_level}  -> {p.resolved_mountpoint()}"
            if args.cmd == "status":
                mounted = Path(p.resolved_mountpoint()).is_mount()
                line += f"  [{'mounted' if mounted else 'NOT mounted'}]  uuid={p.uuid or '?'}"
            print(line)
        return 0

    # plan / create
    try:
        disks, _all = _resolve(args.disks)
        plan = dp.plan_pool(args.name, args.level, disks,
                            mountpoint=args.mountpoint, force=args.force)
    except dp.DiskGuardError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2

    if args.cmd == "plan":
        print(f"Plan for pool '{plan.name}' ({plan.raid_level}) -> {plan.mountpoint}:")
        for line in plan.describe():
            print(f"  {line}")
        print("\n(no changes made; run 'create' to apply)")
        return 0

    # create — re-inspect right before executing (guards re-check inside)
    def _record(result):
        # Save the pool into the config-DB and VERIFY it persisted by reloading.
        cfg = fc.load()
        cfg.storage.pools.append(fc.StoragePool(
            name=plan.name, raid_level=plan.raid_level,
            devices=plan.devices, mountpoint=result["mountpoint"],
            uuid=result["uuid"]))
        fc.save(cfg)
        # verify-after-write: reload and confirm the pool is actually there
        reloaded = fc.load()
        if not any(p.uuid == result["uuid"] for p in reloaded.storage.pools):
            raise RuntimeError(
                "config-DB save did not persist the pool (check that "
                "/opt/forgeos/forgeos_config.py is current and writable)")

    try:
        disks_now, _ = _resolve(args.disks)
        result = dp.execute_pool(plan, disks_now, force=args.force, record=_record)
    except dp.DiskGuardError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2

    print(f"pool '{plan.name}' created and mounted at {result['mountpoint']} "
          f"(uuid={result['uuid']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
