"""ForgeOS v2 generator registry + orchestration.

Single place that knows every service generator, so both the CLI
(`forgeos-generate`) and the web API call the SAME code path to render +
apply config. This is the integration seam: load config DB once, run the
requested generator(s), report what happened.

Adding a new service = register its generator here. Nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import forgeos_config as fc
from generators import GeneratorError, ServiceGenerator
from generators.nfs import NfsGenerator
from generators.nginx import NginxGenerator
from generators.samba import SambaGenerator
from generators.security import SecurityGenerator
from generators.wireguard import WireGuardGenerator

# Order matters for `apply all`: security (firewall) early, proxy after the
# services it fronts. Each entry is instantiated once.
_REGISTRY: dict[str, ServiceGenerator] = {
    "security": SecurityGenerator(),
    "samba": SambaGenerator(),
    "nfs": NfsGenerator(),
    "wireguard": WireGuardGenerator(),
    "nginx": NginxGenerator(),
}


def names() -> list[str]:
    return list(_REGISTRY)


def get(name: str) -> ServiceGenerator:
    if name not in _REGISTRY:
        raise KeyError(f"unknown generator: {name!r} (have: {', '.join(_REGISTRY)})")
    return _REGISTRY[name]


@dataclass
class ApplyResult:
    service: str
    ok: bool
    written: list[str] = field(default_factory=list)
    error: str = ""


def apply_one(name: str, *, cfg=None, do_reload: bool = True) -> ApplyResult:
    """Render + apply a single service. Never raises — returns a result."""
    gen = get(name)
    cfg = cfg if cfg is not None else fc.load()
    try:
        written = gen.apply(cfg, do_reload=do_reload)
        return ApplyResult(service=name, ok=True, written=written)
    except GeneratorError as e:
        return ApplyResult(service=name, ok=False, error=str(e))
    except Exception as e:  # noqa: BLE001 — registry must isolate failures
        return ApplyResult(service=name, ok=False, error=f"{type(e).__name__}: {e}")


def apply_all(*, cfg=None, do_reload: bool = True) -> list[ApplyResult]:
    """Apply every registered generator. One service's failure does NOT
    abort the others — each is isolated and reported.
    """
    cfg = cfg if cfg is not None else fc.load()
    results: list[ApplyResult] = []
    for name in _REGISTRY:
        results.append(apply_one(name, cfg=cfg, do_reload=do_reload))
    return results
