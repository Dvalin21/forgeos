"""ForgeOS app-store manifest models + parser.

An app in the catalog is a directory with a docker-compose.yml whose
metadata rides in an `x-forgeos:` extension block (CasaOS-style — compose
ignores x-* keys, so the file stays a valid compose file).

This module is PURE: it parses + validates manifests with no Docker, no
network, no filesystem side effects beyond reading the file you hand it. The
install orchestration (compose up, port allocation, nginx vhost) is built on
top of this, separately, so the parsing/validation is fully unit-testable.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

# App IDs: same rule CasaOS uses for the compose `name:` key.
_APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ManifestError(ValueError):
    """Raised when an app manifest is malformed or fails validation."""


class AppTips(BaseModel):
    before_install: str = ""


class ForgeOSMeta(BaseModel):
    """The x-forgeos metadata block."""

    title: str
    tagline: str = ""
    description: str = ""
    category: str = "Uncategorized"
    author: str = "Unknown"
    icon: str = ""
    main: str                       # the main service name
    port_map: str = ""              # the container web-UI port, as a string
    architectures: list[str] = Field(default_factory=lambda: ["amd64"])
    tips: AppTips = Field(default_factory=AppTips)

    @field_validator("title", "main")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class AppManifest(BaseModel):
    """A parsed, validated app manifest."""

    app_id: str                     # the compose `name:` — unique store ID
    meta: ForgeOSMeta
    # The raw compose dict (services etc.) kept for install-time rendering.
    compose: dict
    # Convenience: pulled out of compose for validation/UX.
    images: list[str] = Field(default_factory=list)

    @field_validator("app_id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not _APP_ID_RE.match(v):
            raise ValueError(
                f"invalid app id {v!r}: must match {_APP_ID_RE.pattern}"
            )
        return v


def parse_manifest(text: str) -> AppManifest:
    """Parse + validate an app's docker-compose.yml (as text)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ManifestError(f"invalid YAML: {e}") from e

    if not isinstance(data, dict):
        raise ManifestError("compose file is not a mapping")

    app_id = data.get("name")
    if not app_id:
        raise ManifestError("compose file missing top-level 'name:' (the app id)")

    x = data.get("x-forgeos")
    if not isinstance(x, dict):
        raise ManifestError("compose file missing 'x-forgeos:' metadata block")

    services = data.get("services")
    if not isinstance(services, dict) or not services:
        raise ManifestError("compose file has no services")

    try:
        meta = ForgeOSMeta.model_validate(x)
    except Exception as e:  # pydantic ValidationError
        raise ManifestError(f"invalid x-forgeos metadata: {e}") from e

    # The declared main service must exist.
    if meta.main not in services:
        raise ManifestError(
            f"x-forgeos.main={meta.main!r} is not a service in the compose file "
            f"(have: {', '.join(services)})"
        )

    # Collect images; reject :latest (reproducibility — CasaOS rule).
    images: list[str] = []
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            raise ManifestError(f"service {svc_name!r} is not a mapping")
        img = svc.get("image")
        if not img:
            raise ManifestError(f"service {svc_name!r} has no image")
        if img.endswith(":latest") or (":" not in img.rsplit("/", 1)[-1]):
            raise ManifestError(
                f"service {svc_name!r} image {img!r} must be pinned to a "
                "specific tag (no :latest, no untagged)"
            )
        images.append(img)

    try:
        return AppManifest(app_id=app_id, meta=meta, compose=data, images=images)
    except Exception as e:
        raise ManifestError(str(e)) from e


def parse_manifest_file(path: str | Path) -> AppManifest:
    p = Path(path)
    if not p.exists():
        raise ManifestError(f"manifest not found: {p}")
    return parse_manifest(p.read_text())
