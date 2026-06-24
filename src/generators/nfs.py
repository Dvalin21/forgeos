"""NFS exports generator (v2).

Renders /etc/exports.d/forgeos.exports from the config DB (exportfs reads
/etc/exports plus /etc/exports.d/*.exports). Writing our own drop-in keeps the
file under a writable parent dir — /etc itself is read-only under the API's
ProtectSystem=strict namespace — and never clobbers a hand-written /etc/exports.
Export OPTIONS are derived from a fixed set of export types (rw/ro/public/backup)
rather than freeform — the same finite-template approach as Samba share types.
The NFSv4 root export (fsid=0) is always emitted when enabled.
"""

from __future__ import annotations

from generators import RenderedFile, ServiceGenerator

_TYPE_OPTS: dict[str, str] = {
    "rw": "rw,no_subtree_check,no_root_squash,async,sec=sys",
    "ro": "ro,no_subtree_check,root_squash,async,sec=sys",
    "public": "ro,no_subtree_check,all_squash,async,sec=sys",
    "backup": "rw,no_subtree_check,root_squash,sync,sec=sys",
}


class NfsGenerator(ServiceGenerator):
    name = "nfs"

    def render(self, cfg) -> list[RenderedFile]:
        nfs = cfg.nfs
        if not nfs.enabled:
            return []

        cidr = nfs.lan_cidr
        lines = [
            "# ForgeOS NFS exports — GENERATED, do not edit by hand.",
            "# Source: /etc/forgeos/config.json  (regenerate: forgeos-generate nfs)",
            "",
            "# NFSv4 pseudo-root",
            f"{nfs.nas_root} {cidr}(rw,fsid=0,no_subtree_check,crossmnt,async,sec=sys)",
            "",
        ]
        for e in nfs.exports:
            opts = _TYPE_OPTS[e.type]
            lines.append(f"{e.path} {cidr}({opts})")
        return [
            RenderedFile(
                path="/etc/exports.d/forgeos.exports",
                content="\n".join(lines) + "\n",
                mode=0o644,
            )
        ]

    def reload(self) -> None:
        if not _have("exportfs"):
            return
        self._run(["exportfs", "-ra"], check=False)


def _have(cmd: str) -> bool:
    import shutil

    return shutil.which(cmd) is not None
