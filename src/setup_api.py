"""ForgeOS LHSR — First-boot setup wizard API."""

from __future__ import annotations

import subprocess
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from forgeos_auth import verify_token

router = APIRouter()


@router.get("/api/setup/status")
async def setup_status(user=Depends(verify_token)):
    """Check if the system has been configured."""
    import forgeos_config as fc

    cfg = fc.load()
    pending = []

    if not cfg.naming.system_hostname:
        pending.append("hostname")

    try:
        r = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            pending.append("timezone")
    except Exception:
        pending.append("timezone")

    try:
        r = subprocess.run(
            ["ip", "-j", "addr", "show"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            pending.append("network")
    except Exception:
        pending.append("network")

    if not getattr(cfg.install, 'os_drive', None):
        pending.append("os_drive")

    if not cfg.lhsr.groups:
        pending.append("lhsr_groups")

    return {
        "configured": len(pending) == 0,
        "pending_steps": pending,
    }


@router.get("/api/setup/network-interfaces")
async def setup_network_interfaces(user=Depends(verify_token)):
    """Get available network interfaces."""
    import json

    r = subprocess.run(
        ["ip", "-j", "addr", "show"],
        capture_output=True, text=True, timeout=5,
    )
    if r.returncode != 0:
        raise HTTPException(500, "Failed to get network interfaces")

    interfaces = json.loads(r.stdout)
    result = []
    for iface in interfaces:
        name = iface.get("ifname", "")
        if name == "lo":
            continue
        addrs = []
        for addr in iface.get("addr_info", []):
            if addr.get("family") == "inet":
                addrs.append({
                    "address": addr.get("local"),
                    "prefixlen": addr.get("prefixlen"),
                })
        result.append({
            "name": name,
            "mac": iface.get("address"),
            "state": iface.get("operstate", "unknown"),
            "addresses": addrs,
        })

    return {"interfaces": result}


@router.get("/api/setup/timezones")
async def setup_timezones(user=Depends(verify_token)):
    """Get list of available timezones."""
    r = subprocess.run(
        ["timedatectl", "list-timezones"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        raise HTTPException(500, "Failed to get timezones")

    timezones = [tz.strip() for tz in r.stdout.strip().split("\n") if tz.strip()]
    return {"timezones": timezones}


@router.get("/api/setup/disks")
async def setup_disks(user=Depends(verify_token)):
    """Get available disks for OS and LHSR assignment."""
    import forgeos_diskprep as dp

    disks = dp.inspect_disks()
    result = []
    for d in disks:
        result.append({
            "name": d.name,
            "path": d.path,
            "size_bytes": d.size_bytes,
            "is_system": d.is_system,
            "mounted": d.mounted,
            "in_array": d.in_array,
            "has_partition_table": d.has_partition_table,
            "has_filesystem": d.has_filesystem,
            "mountpoints": d.mountpoints,
        })

    return {"disks": result}


@router.post("/api/setup/configure")
async def setup_configure(body: dict, user=Depends(verify_token)):
    """Apply first-boot configuration."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin required")

    results = {}

    hostname = body.get("hostname", "").strip()
    if hostname:
        r = subprocess.run(
            ["hostnamectl", "set-hostname", hostname],
            capture_output=True, text=True, timeout=10,
        )
        results["hostname"] = {
            "ok": r.returncode == 0,
            "detail": r.stderr.strip() if r.returncode != 0 else "Hostname set",
        }

    timezone = body.get("timezone", "").strip()
    if timezone:
        r = subprocess.run(
            ["timedatectl", "set-timezone", timezone],
            capture_output=True, text=True, timeout=10,
        )
        results["timezone"] = {
            "ok": r.returncode == 0,
            "detail": r.stderr.strip() if r.returncode != 0 else "Timezone set",
        }

    network = body.get("network", {})
    if network.get("interface"):
        results["network"] = _configure_network(network)

    os_drive = body.get("os_drive", "").strip()
    if os_drive:
        import forgeos_config as fc
        cfg = fc.load()
        cfg.install.os_drive = os_drive
        fc.save(cfg)
        results["os_drive"] = {"ok": True, "detail": f"OS drive set to {os_drive}"}

    lhsr_groups = body.get("lhsr_groups", [])
    if lhsr_groups:
        import forgeos_config as fc
        cfg = fc.load()
        cfg.lhsr.groups = []
        for group in lhsr_groups:
            g = fc.LhsrGroup(
                name=group.get("name", "default"),
                parity=int(group.get("parity", 1)),
                disks=group.get("disks", []),
            )
            cfg.lhsr.groups.append(g)
        cfg.lhsr.enabled = True
        fc.save(cfg)
        results["lhsr_groups"] = {"ok": True, "detail": f"{len(lhsr_groups)} LHSR group(s) configured"}

    return results


def _configure_network(network: dict) -> dict:
    """Configure static IP."""
    iface = network.get("interface", "")
    address = network.get("address", "")
    prefixlen = int(network.get("prefixlen", 24))
    gateway = network.get("gateway", "")
    dns = network.get("dns", "")

    if not iface or not address:
        return {"ok": False, "detail": "Interface and address required"}

    config = f"""[Match]
Name={iface}

[Network]
Address={address}/{prefixlen}
"""
    if gateway:
        config += f"Gateway={gateway}\n"
    if dns:
        config += f"DNS={dns}\n"

    config_path = f"/etc/systemd/network/10-{iface}.network"
    try:
        with open(config_path, "w") as f:
            f.write(config)

        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, text=True, timeout=10)
        subprocess.run(["systemctl", "enable", "--now", "systemd-networkd"], capture_output=True, text=True, timeout=10)
        subprocess.run(["systemctl", "restart", "systemd-networkd"], capture_output=True, text=True, timeout=10)

        return {"ok": True, "detail": f"Static IP {address}/{prefixlen} configured on {iface}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}
