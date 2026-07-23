"""ForgeOS v2 service-config generator framework.

Each service has a generator that turns the config DB into the files that
service needs, then applies them and reloads the service. The design splits
PURE rendering (config -> file contents, no side effects, fully unit-
testable) from APPLY (mkdir -p, atomic write, chmod) and RELOAD.

This is the architectural fix for the whole class of install bugs that came
from bash modules writing /etc files imperatively:
  - "no such file or directory" (heredoc to a dir not yet created)
    -> apply() mkdir -p's every parent before writing, by construction.
  - hand-written config drifting from user choices
    -> there is one source of truth (the config DB) and config is rendered.
  - generated CLIs with their own syntax errors
    -> no generated bash CLIs; the API edits the DB and calls the generator.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from forgeos_atomic import atomic_write


@dataclass(frozen=True)
class RenderedFile:
    """A file the generator wants to exist. Pure data — no I/O yet."""

    path: str
    content: str
    mode: int = 0o644


class GeneratorError(RuntimeError):
    pass


class ServiceGenerator:
    """Base class. Subclasses implement render(); reload() is optional."""

    name: str = "base"

    def render(self, cfg) -> list[RenderedFile]:
        """Pure: config -> list of RenderedFile. No side effects. Override."""
        raise NotImplementedError

    def validate(self, files: list[RenderedFile]) -> None:
        """Optional pre-apply validation hook (e.g. testparm). Override."""
        return None

    def reload(self) -> None:
        """Restart/reload the managed service. Override."""
        return None

    # ---- apply: the only part that touches the system ----

    def apply(self, cfg, *, do_reload: bool = True) -> list[str]:
        """Render -> validate -> atomically write each file -> reload.

        Returns the list of paths written. Idempotent and re-runnable.
        """
        files = self.render(cfg)
        self.validate(files)
        written: list[str] = []
        for rf in files:
            self._atomic_write(rf)
            written.append(rf.path)
        if do_reload:
            self.reload()
        return written

    @staticmethod
    def _atomic_write(rf: RenderedFile) -> None:
        """Adapter: RenderedFile -> the shared atomic writer."""
        atomic_write(rf.path, rf.content, rf.mode)

    @staticmethod
    def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, check=check, capture_output=True, text=True
        )
