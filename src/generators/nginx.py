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
        # Pick the primary vhost that owns the catch-all (default_server): the
        # forgeos-ui vhost if present, else the first. The appliance answers on
        # ANY Host — its domain, its LAN IP, or localhost — because that's how
        # people actually reach a home NAS. App vhosts (grafana.* etc.) are NOT
        # default and match only their own server_name.
        #
        # (This replaces the earlier separate default-deny server, which was
        # too strict: it 444'd every request whose Host wasn't exactly the
        # domain — including access by IP and localhost, i.e. normal use.)
        default_name = "forgeos-ui" if any(
            v.name == "forgeos-ui" for v in nginx.vhosts) else nginx.vhosts[0].name
        ext = {c.name: (c.fullchain_path, c.privkey_path)
               for c in getattr(nginx, "external_certs", [])}
        for v in nginx.vhosts:
            cert, key = self._cert_paths(v.cert_name or v.domain, ext)
            content = tpl.render(v=v, cert_path=cert, key_path=key,
                                 is_default=(v.name == default_name))
            out.append(
                RenderedFile(
                    path=f"{VHOST_DIR}/{v.name}.conf",
                    content=content,
                    mode=0o644,
                )
            )
        return out

    def apply(self, cfg, *, do_reload: bool = True) -> list[str]:
        """Render + write vhosts, THEN reconcile: remove any ForgeOS-managed
        .conf in forgeos.d/ that we no longer generate. Generators that only
        ever add/overwrite leave orphans — and an orphan vhost here is
        dangerous: e.g. a stale 'default-deny' (return 444) keeps default_server
        and silently drops ALL traffic (ERR_EMPTY_RESPONSE) even after the code
        that produced it was removed. forgeos.d/ is a glob-include we OWN, so on
        each apply it must reflect EXACTLY the current config, nothing stale.
        """
        files = self.render(cfg)
        self.validate(files)
        written: list[str] = []
        for rf in files:
            self._atomic_write(rf)
            written.append(rf.path)

        # Reconcile forgeos.d/: delete *.conf we own but didn't just write.
        vhost_dir = Path(VHOST_DIR)
        if vhost_dir.is_dir():
            keep = {Path(p).name for p in written if Path(p).parent == vhost_dir}
            for existing in vhost_dir.glob("*.conf"):
                if existing.name not in keep:
                    try:
                        existing.unlink()
                        written.append(f"-{existing}")  # '-' marks a removal
                    except OSError:
                        pass

        if do_reload:
            self.reload()
        return written

    @staticmethod
    def _cert_paths(cert_name: str, external: dict | None = None) -> tuple[str, str]:
        # Resolution order: a registered EXTERNAL cert by that name, then a
        # Let's Encrypt live dir, else snakeoil. cert_name defaults to the
        # vhost domain (per-host), or names a shared/wildcard/external cert.
        if external and cert_name in external:
            fc, pk = external[cert_name]
            if Path(fc).exists() and Path(pk).exists():
                return fc, pk
        le_dir = Path(f"/etc/letsencrypt/live/{cert_name}")
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
