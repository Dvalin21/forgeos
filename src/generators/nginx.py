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
CONFD_DIR = "/etc/nginx/conf.d"

# Default-deny catch-all. Named 00-* so it sorts first; default_server makes
# it the fallback for any unmatched Host on :80 and :443. 444 closes the
# connection with no response (nginx-specific). Real vhosts sort after and
# match by their own server_name.
_DEFAULT_DENY = """# ForgeOS default-deny — GENERATED, do not edit by hand.
# Drops any request whose Host header matches no known ForgeOS vhost.
server {{
    listen 80 default_server;
    listen [::]:80 default_server;
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    ssl_certificate     {cert};
    ssl_certificate_key {key};

    return 444;
}}
"""
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
        if not nginx.vhosts:
            return []
        # Stock Debian nginx includes conf.d/*.conf but NOT our forgeos.d/.
        # Emit a one-line include into conf.d so our vhosts are actually read
        # (without this the vhost files exist on disk but nginx never loads
        # them, so :443 never comes up).
        out.append(
            RenderedFile(
                path=f"{CONFD_DIR}/forgeos.conf",
                content=(
                    "# ForgeOS — GENERATED. Pulls in ForgeOS-managed vhosts.\n"
                    f"include {VHOST_DIR}/*.conf;\n"
                ),
                mode=0o644,
            )
        )
        # Default-deny catch-all (Option B). Any request whose Host matches no
        # known vhost is dropped with 444 (close, no response). This is the
        # principled replacement for deleting the stock sites-enabled/default:
        # we OWN the catch-all explicitly rather than relying on a distro
        # file's absence. Sorts first (00-) and claims default_server.
        cert, key = self._cert_paths(cfg.nginx.vhosts[0].domain)
        out.append(
            RenderedFile(
                path=f"{VHOST_DIR}/00-default-deny.conf",
                content=_DEFAULT_DENY.format(cert=cert, key=key),
                mode=0o644,
            )
        )
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
