#!/usr/bin/env python3
"""forgeos-install-cli — the v2 installer entry point (called by bootstrap.sh).

Collects install choices (interactively or from flags), then runs the phased
Python installer. The installer seeds the config DB and hands all config work
to the generators — no heredocs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# make src/ and this dir importable
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent.parent / "src"))

import forgeos_install as fi  # noqa: E402


def _prompt(text: str, default: str) -> str:
    try:
        ans = input(f"{text} [{default}]: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def _prompt_bool(text: str, default: bool) -> bool:
    d = "Y/n" if default else "y/N"
    ans = _prompt(f"{text} ({d})", "").lower()
    if not ans:
        return default
    return ans.startswith("y")


def collect_choices_interactive() -> fi.InstallChoices:
    print("\nForgeOS v2 — configuration\n")
    hostname = _prompt("Hostname (blank = keep current)", "")
    timezone = _prompt("Timezone, IANA name (blank = keep current)", "")
    domain = _prompt("LAN name (blank = <hostname>.local)", "")
    lan_cidr = _prompt("LAN CIDR", "10.0.0.0/24")
    profile = _prompt("Security profile (low/medium/high)", "medium")
    while profile not in ("low", "medium", "high"):
        profile = _prompt("  please enter low, medium, or high", "medium")
    wg = _prompt_bool("Enable WireGuard VPN", False)
    nfs = _prompt_bool("Enable NFS exports", False)
    filedb = _prompt_bool("Enable ForgeFileDB", False)
    coral = _prompt_bool("Enable Coral TPU (if present)", False)
    gpu = _prompt_bool("Enable GPU drivers (if present)", False)
    return fi.InstallChoices(
        domain=domain, hostname=hostname, timezone=timezone,
        lan_cidr=lan_cidr, security_profile=profile,
        enable_wireguard=wg, enable_nfs=nfs,
        enable_forgefiledb=filedb, enable_coral=coral, enable_gpu=gpu,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forgeos-install")
    ap.add_argument("--unattended", action="store_true",
                    help="use defaults / flags, no prompts")
    ap.add_argument("--domain", default="",
                    help="LAN name (default: derive <hostname>.local). A "
                         "custom .local name is published as an mDNS alias; a "
                         "non-.local name needs your own DNS.")
    ap.add_argument("--hostname", default="", help="set the OS hostname (default: keep)")
    ap.add_argument("--timezone", default="", help="IANA timezone (default: keep)")
    ap.add_argument("--lan-cidr", default="10.0.0.0/24")
    ap.add_argument("--profile", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--wireguard", action="store_true")
    ap.add_argument("--nfs", action="store_true")
    ap.add_argument("--forgefiledb", action="store_true")
    ap.add_argument("--coral", action="store_true")
    ap.add_argument("--gpu", action="store_true")
    args = ap.parse_args(argv)

    if args.unattended:
        choices = fi.InstallChoices(
            domain=args.domain, hostname=args.hostname, timezone=args.timezone,
            lan_cidr=args.lan_cidr,
            security_profile=args.profile,
            enable_wireguard=args.wireguard, enable_nfs=args.nfs,
            enable_forgefiledb=args.forgefiledb,
            enable_coral=args.coral, enable_gpu=args.gpu,
        )
    else:
        choices = collect_choices_interactive()

    installer = fi.Installer(choices=choices, repo_root=str(_here.parent.parent))
    print("\n==> Running installation\n")
    results = installer.run_all()

    print()
    failures = 0
    for r in results:
        mark = "✓" if r.ok else "✗"
        line = f"  {mark} {r.phase}"
        if r.detail:
            line += f" — {r.detail}"
        print(line)
        if not r.ok:
            failures += 1

    if failures:
        print(f"\nInstallation incomplete ({failures} phase(s) failed).")
        return 1
    print("\n✓ ForgeOS v2 base installed. Config DB: /etc/forgeos/config.json")
    if installer._admin_password:
        print("\n  ┌──────────────────────────────────────────────────────┐")
        print("  │  Web UI admin login — SAVE THIS, shown only once       │")
        print("  │    username: admin                                     │")
        print(f"  │    password: {installer._admin_password:<41} │")
        print("  └──────────────────────────────────────────────────────┘")
    else:
        print("  Web UI admin: existing api-users.json kept (password unchanged)")
    resolved = installer.build_config().naming.lan_name
    print(f"\n  Web UI:  https://{resolved}/   (or https://<this-host-ip>/)")
    if resolved.endswith(".local"):
        print("  Name resolution: resolves on the LAN via mDNS/avahi")
        print("  (Mac/Linux/Win10+/iOS/Android) with no client setup.")
    else:
        print(f"  Name resolution: '{resolved}' is NOT mDNS — point it at")
        print("  this box via your router/DNS or a client hosts-file entry, or")
        print("  just use the IP above.")
    print("  Manage services: forgeos-generate all")
    print("  Install apps:    forgeos-app sync && forgeos-app install <id>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
