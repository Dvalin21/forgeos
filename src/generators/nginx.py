"""nginx reverse-proxy generator (v2).

Renders one vhost file per enabled site under /etc/nginx/forgeos.d/. Vhosts
are DERIVED from the config DB (which is in turn derived from which services
are actually enabled) — not a hardcoded list that references services that
may not exist (the bug in the legacy module that emitted grafana/gotify/
immich vhosts unconditionally).

Cert path strategy: if a Let's Encrypt cert exists for the domain, use it;
otherwise fall back to the ForgeOS self-signed snakeoil cert so nginx can
start before certs are issued (another legacy failure point).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from generators import RenderedFile, ServiceGenerator

_TEMPLATES = Path(__file__).parent / "templates"
VHOST_DIR = "/etc/nginx/forgeos.d"
SNAKEOIL_CERT = "/etc/ssl/certs/ssl-cert-snakeoil.pem"
SNAKEOIL_KEY = "/etc/ssl/private/ssl-cert-snakeoil.key"


class NginxGenerator(ServiceGenerator):
    name = "nginx"

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)),
            autoescape=select_autoescape(enabled_extensions=()),
            trim_blocks=True,
            lstrip_blocks=False,
            keep_trailing_newline=True,
        )

    def render(self, cfg) -> list[RenderedFile]:
        nginx = cfg.nginx
        if not nginx.enabled:
            return []
        tpl = self._env.get_template("nginx_vhost.conf.j2")
        out: list[RenderedFile] = []
        for v in nginx.vhosts:
            cert, key = self._cert_paths(v.domain)
            content = tpl.render(v=v, cert_path=cert, key_path=key)
            out.append(
                RenderedFile(
                    path=f"{VHOST_DIR}/{v.name}.conf",
                    content=content,
                    mode=0o644,
                )
            )
        return out

    @staticmethod
    def _cert_paths(domain: str) -> tuple[str, str]:
        le_dir = Path(f"/etc/letsencrypt/live/{domain}")
        if (le_dir / "fullchain.pem").exists():
            return str(le_dir / "fullchain.pem"), str(le_dir / "privkey.pem")
        return SNAKEOIL_CERT, SNAKEOIL_KEY

    def validate(self, files: list[RenderedFile]) -> None:
        return None

    def reload(self) -> None:
        if not _have("nginx") or not _have("systemctl"):
            return
        test = self._run(["nginx", "-t"], check=False)
        if test.returncode == 0:
            self._run(["systemctl", "reload", "nginx"], check=False)


def _have(cmd: str) -> bool:
    import shutil

    return shutil.which(cmd) is not None
