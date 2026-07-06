"""WireGuard generator (v2).

Renders the whole wg interface config from the config DB's peer list. The
legacy module APPENDED peers to the file imperatively (`cat >>`), which
could drift; here the file is regenerated wholesale, always consistent with
the DB.

Secret material policy: the server PRIVATE key never lives in the config DB.
It stays in the keystore (/etc/forgeos/wireguard/server.key, 0600) and is
read in at render time. The DB holds only peer public keys + addresses.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from generators import GeneratorError, RenderedFile, ServiceGenerator

_TEMPLATES = Path(__file__).parent / "templates"
WG_KEY_DIR = "/etc/forgeos/wireguard"


class WireGuardGenerator(ServiceGenerator):
    name = "wireguard"

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)),
            autoescape=select_autoescape(enabled_extensions=()),
            trim_blocks=True,
            lstrip_blocks=False,
            keep_trailing_newline=True,
        )

    def _server_key_path(self) -> Path:
        return Path(WG_KEY_DIR) / "server.key"

    def render(self, cfg) -> list[RenderedFile]:
        wg = cfg.wireguard
        if not wg.enabled:
            return []

        server_key = self._read_server_key()
        prefix = ipaddress.ip_network(wg.subnet, strict=False).prefixlen

        tpl = self._env.get_template("wireguard.conf.j2")
        content = tpl.render(
            server_address=wg.server_address,
            prefix=prefix,
            listen_port=wg.listen_port,
            server_private_key=server_key,
            interface=wg.interface,
            egress_nic=wg.egress_nic,
            subnet=wg.subnet,
            peers=wg.peers,
        )
        return [
            RenderedFile(
                path=f"/etc/wireguard/{wg.interface}.conf",
                content=content,
                mode=0o600,
            )
        ]

    def _read_server_key(self) -> str:
        p = self._server_key_path()
        if p.exists():
            return p.read_text().strip()
        return "__FORGEOS_WG_SERVER_KEY_MISSING__"

    def ensure_server_key(self) -> str:
        """Generate the server keypair if absent; return the public key.
        Called by the API before add-peer so a fresh box just works."""
        priv = self._server_key_path()
        pub = priv.with_suffix(".pub")
        if priv.exists() and pub.exists():
            return pub.read_text().strip()
        priv.parent.mkdir(parents=True, exist_ok=True)
        import subprocess
        key = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True).stdout.strip()
        pubkey = subprocess.run(["wg", "pubkey"], input=key, capture_output=True, text=True, check=True).stdout.strip()
        # 0600 private, written atomically via the base helper contract
        priv.write_text(key + "\n"); priv.chmod(0o600)
        pub.write_text(pubkey + "\n"); pub.chmod(0o644)
        return pubkey

    def server_pubkey(self) -> str:
        pub = self._server_key_path().with_suffix(".pub")
        return pub.read_text().strip() if pub.exists() else self.ensure_server_key()

    def validate(self, files: list[RenderedFile]) -> None:
        for f in files:
            if "__FORGEOS_WG_SERVER_KEY_MISSING__" in f.content:
                raise GeneratorError(
                    f"WireGuard server key not found at {self._server_key_path()} "
                    "— generate it first (wg genkey)."
                )

    def reload(self) -> None:
        if not _have("systemctl"):
            return
        self._run(["systemctl", "restart", "wg-quick@wg0"], check=False)


def _have(cmd: str) -> bool:
    import shutil

    return shutil.which(cmd) is not None
