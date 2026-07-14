"""Avahi (mDNS) generator — broadcasts Data Connect on the local network.

When data_connect.broadcast is on, writes an Avahi service file announcing the
NAS as a Data Connect host, so network scanners / clients can discover it. When
off (or Data Connect disabled), the file is absent and the service isn't
announced. Idempotent: render reflects config, apply writes-or-removes.

Broadcasts on the ElevateDB-server service type (_edb-server._tcp) as well for
discovery compatibility with existing EDB-aware scanners — the port there is the
conventional 12010, informational only (ForgeOS doesn't run edbsrvr).
"""
from __future__ import annotations

from pathlib import Path

from generators import RenderedFile, ServiceGenerator

AVAHI_SERVICE = "/etc/avahi/services/forgeos-data-connect.service"
EDB_COMPAT_PORT = 12010


class AvahiGenerator(ServiceGenerator):
    name = "avahi"

    def render(self, cfg) -> list[RenderedFile]:
        dc = getattr(cfg, "data_connect", None)
        if dc is None or not dc.enabled or not dc.broadcast:
            return []          # nothing announced -> file removed on apply
        xml = (
            "<?xml version=\"1.0\" standalone='no'?>\n"
            "<!DOCTYPE service-group SYSTEM \"avahi-service.dtd\">\n"
            "<service-group>\n"
            "  <name replace-wildcards=\"yes\">Data Connect on %h</name>\n"
            "  <service>\n"
            "    <type>_data-connect._tcp</type>\n"
            f"    <port>{EDB_COMPAT_PORT}</port>\n"
            "    <txt-record>product=ForgeOS Data Connect</txt-record>\n"
            "    <txt-record>vendor=ForgeOS</txt-record>\n"
            "  </service>\n"
            "  <service>\n"
            "    <type>_edb-server._tcp</type>\n"
            f"    <port>{EDB_COMPAT_PORT}</port>\n"
            "    <txt-record>product=ForgeOS Data Connect</txt-record>\n"
            "  </service>\n"
        )
        # Standard mDNS service types per tracked server DB, so DB-aware
        # clients discover the real engine + port (not just the umbrella).
        _MDNS_TYPE = {"postgres": "_postgresql._tcp", "mysql": "_mysql._tcp"}
        for db in dc.databases:
            t = _MDNS_TYPE.get(db.kind)
            if t and db.port:
                xml += (
                    "  <service>\n"
                    f"    <type>{t}</type>\n"
                    f"    <port>{db.port}</port>\n"
                    f"    <txt-record>name={db.name}</txt-record>\n"
                    "    <txt-record>vendor=ForgeOS</txt-record>\n"
                    "  </service>\n"
                )
        xml += "</service-group>\n"
        return [RenderedFile(path=AVAHI_SERVICE, content=xml, mode=0o644)]

    def apply(self, cfg, *, do_reload: bool = True) -> list[str]:
        files = self.render(cfg)
        if not files:
            # broadcast off / disabled -> ensure the service file is gone
            p = Path(AVAHI_SERVICE)
            existed = p.exists()
            p.unlink(missing_ok=True)
            if existed and do_reload:
                self.reload()
            return []
        written: list[str] = []
        for rf in files:
            self._atomic_write(rf)
            written.append(rf.path)
        if do_reload:
            self.reload()
        return written

    def reload(self) -> None:
        import subprocess
        import shutil
        if not shutil.which("systemctl"):
            return
        try:
            subprocess.run(["systemctl", "reload", "avahi-daemon"],
                           check=False, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
