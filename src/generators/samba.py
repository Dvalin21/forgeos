"""Samba config generator (v2 proof-of-concept).

Renders /etc/samba/smb.conf (global block) and the included shares file from
the config DB, validates with `testparm`, and reloads smbd. Replaces the
legacy 10b-samba-db.sh heredocs + the generated forgeos-samba bash CLI.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from generators import GeneratorError, RenderedFile, ServiceGenerator

_TEMPLATES = Path(__file__).parent / "templates"

SMB_CONF = "/etc/samba/smb.conf"
SHARES_FILE = "/etc/forgeos/samba/forgeos-shares.conf"
# User-managed raw directives (edited via the Shares page raw editor). The
# generator INCLUDES this file but never renders/overwrites it, so hand-written
# directives survive regeneration of the managed shares above.
CUSTOM_FILE = "/etc/forgeos/samba/forgeos-shares-custom.conf"


class SambaGenerator(ServiceGenerator):
    name = "samba"

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)),
            autoescape=select_autoescape(enabled_extensions=()),
            trim_blocks=True,
            lstrip_blocks=False,
            keep_trailing_newline=True,
        )

    def render(self, cfg) -> list[RenderedFile]:
        samba = cfg.samba
        if not samba.enabled:
            return []

        global_tpl = self._env.get_template("smb_global.conf.j2")
        shares_tpl = self._env.get_template("smb_shares.conf.j2")

        smb_conf = global_tpl.render(
            workgroup=samba.workgroup,
            server_string=samba.server_string,
            shares_file=SHARES_FILE,
            custom_file=CUSTOM_FILE,
        )
        db_shares = _data_connect_shares(cfg)
        # Section names must be unique across managed shares + DB shares. The
        # import API rejects collisions, but the config-DB is hand-editable —
        # a duplicate [section] silently merges directives, so fail loud here.
        seen = {s.name.lower() for s in samba.shares}
        dupes = [d["name"] for d in db_shares if d["name"].lower() in seen]
        if dupes:
            raise GeneratorError(
                f"data-connect share name collides with a samba share: {dupes}"
            )
        shares_conf = shares_tpl.render(shares=samba.shares, db_shares=db_shares)

        return [
            RenderedFile(path=SMB_CONF, content=smb_conf, mode=0o644),
            RenderedFile(path=SHARES_FILE, content=shares_conf, mode=0o644),
        ]

    def validate(self, files: list[RenderedFile]) -> None:
        """Run `testparm` against the rendered config in a temp location."""
        if not files:
            return
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_shares = Path(td) / "shares.conf"
            tmp_global = Path(td) / "smb.conf"
            rendered = {f.path: f.content for f in files}
            tmp_shares.write_text(rendered.get(SHARES_FILE, ""))
            # isolate managed validation from any live custom include
            tmp_custom = Path(td) / "custom.conf"
            tmp_custom.write_text("")
            global_txt = (
                rendered.get(SMB_CONF, "")
                .replace(f"include = {SHARES_FILE}", f"include = {tmp_shares}")
                .replace(f"include = {CUSTOM_FILE}", f"include = {tmp_custom}")
            )
            tmp_global.write_text(global_txt)
            if not _have("testparm"):
                return
            proc = self._run(["testparm", "-s", str(tmp_global)], check=False)
            if proc.returncode != 0:
                raise GeneratorError(
                    f"samba config failed testparm:\n{proc.stderr.strip()}"
                )

    def validate_custom(self, cfg, custom_text: str) -> None:
        """testparm the live managed config PLUS proposed raw custom directives.

        Raises GeneratorError (with the testparm output) if the combined config
        is invalid; no-ops if samba is disabled or testparm isn't installed.
        Used by the raw-editor PUT so a bad edit can never reach disk.
        """
        files = self.render(cfg)
        if not files:
            return
        import tempfile

        rendered = {f.path: f.content for f in files}
        with tempfile.TemporaryDirectory() as td:
            tmp_shares = Path(td) / "shares.conf"
            tmp_shares.write_text(rendered.get(SHARES_FILE, ""))
            tmp_custom = Path(td) / "custom.conf"
            tmp_custom.write_text(custom_text)
            tmp_global = Path(td) / "smb.conf"
            tmp_global.write_text(
                rendered.get(SMB_CONF, "")
                .replace(f"include = {SHARES_FILE}", f"include = {tmp_shares}")
                .replace(f"include = {CUSTOM_FILE}", f"include = {tmp_custom}")
            )
            if not _have("testparm"):
                return
            proc = self._run(["testparm", "-s", str(tmp_global)], check=False)
            if proc.returncode != 0:
                raise GeneratorError(proc.stderr.strip() or "testparm rejected the config")

    def reload(self) -> None:
        if not _have("systemctl"):
            return
        self._run(["systemctl", "reload", "smbd"], check=False)


def _data_connect_shares(cfg) -> list[dict]:
    """Protected share sections derived from Data Connect file DBs.

    cfg.data_connect is the single source of truth — nothing is mirrored into
    cfg.samba.shares, so tracked DBs and their shares can never drift apart.
    Server DBs (postgres/mysql) are excluded: their data dir must NEVER be on
    a share (SMB caching breaks their write ordering — corruption).
    """
    import forgeos_config as fc

    dc = getattr(cfg, "data_connect", None)
    if dc is None or not dc.enabled:
        return []
    out: list[dict] = []
    for db in dc.databases:
        if db.kind != "file":
            continue
        exts = fc.db_family_extensions(db.db_type)
        veto = "/" + "/".join(f"*{e}" for e in exts) + "/" if exts else ""
        comment = " — ".join(x for x in (db.app, db.db_type) if x) or db.name
        out.append({
            "name": db.name,
            "path": db.data_path,
            "comment": f"Data Connect: {comment}",
            "veto_pattern": veto,
        })
    return out


def _have(cmd: str) -> bool:
    import shutil

    return shutil.which(cmd) is not None
