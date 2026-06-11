"""Tests for the app-store manifest parser — pure, no Docker."""

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_appstore as fa  # noqa: E402


def _compose(**over):
    """A valid baseline compose manifest, overridable for failure tests."""
    base = textwrap.dedent("""
        name: grafana
        services:
          grafana:
            image: grafana/grafana:11.4.0
            restart: unless-stopped
            ports:
              - target: 3000
                published: ${WEBUI_PORT:-3000}
        x-forgeos:
          title: Grafana
          tagline: Metrics dashboards
          category: Monitoring
          author: ForgeOS
          icon: icon.png
          main: grafana
          port_map: "3000"
          architectures: [amd64, arm64]
          tips:
            before_install: Default login admin/admin.
    """).strip()
    return over.get("text", base)


def test_parse_valid_manifest():
    m = fa.parse_manifest(_compose())
    assert m.app_id == "grafana"
    assert m.meta.title == "Grafana"
    assert m.meta.main == "grafana"
    assert m.meta.category == "Monitoring"
    assert "grafana/grafana:11.4.0" in m.images
    assert m.meta.tips.before_install.startswith("Default login")


def test_parse_keeps_raw_compose():
    m = fa.parse_manifest(_compose())
    assert "services" in m.compose
    assert m.compose["services"]["grafana"]["image"] == "grafana/grafana:11.4.0"


def test_invalid_yaml():
    with pytest.raises(fa.ManifestError):
        fa.parse_manifest("name: [unclosed")


def test_not_a_mapping():
    with pytest.raises(fa.ManifestError):
        fa.parse_manifest("- just\n- a\n- list")


def test_missing_name():
    text = textwrap.dedent("""
        services:
          x:
            image: foo/bar:1.0
        x-forgeos:
          title: X
          main: x
    """).strip()
    with pytest.raises(fa.ManifestError, match="name"):
        fa.parse_manifest(text)


def test_missing_x_forgeos():
    text = textwrap.dedent("""
        name: x
        services:
          x:
            image: foo/bar:1.0
    """).strip()
    with pytest.raises(fa.ManifestError, match="x-forgeos"):
        fa.parse_manifest(text)


def test_no_services():
    text = textwrap.dedent("""
        name: x
        services: {}
        x-forgeos:
          title: X
          main: x
    """).strip()
    with pytest.raises(fa.ManifestError, match="no services"):
        fa.parse_manifest(text)


def test_main_not_a_service():
    text = textwrap.dedent("""
        name: x
        services:
          web:
            image: foo/bar:1.0
        x-forgeos:
          title: X
          main: nonexistent
    """).strip()
    with pytest.raises(fa.ManifestError, match="main"):
        fa.parse_manifest(text)


def test_rejects_latest_tag():
    text = textwrap.dedent("""
        name: x
        services:
          web:
            image: foo/bar:latest
        x-forgeos:
          title: X
          main: web
    """).strip()
    with pytest.raises(fa.ManifestError, match="pinned"):
        fa.parse_manifest(text)


def test_rejects_untagged_image():
    text = textwrap.dedent("""
        name: x
        services:
          web:
            image: nginx
        x-forgeos:
          title: X
          main: web
    """).strip()
    with pytest.raises(fa.ManifestError, match="pinned"):
        fa.parse_manifest(text)


def test_service_missing_image():
    text = textwrap.dedent("""
        name: x
        services:
          web:
            restart: always
        x-forgeos:
          title: X
          main: web
    """).strip()
    with pytest.raises(fa.ManifestError, match="no image"):
        fa.parse_manifest(text)


def test_invalid_app_id():
    text = textwrap.dedent("""
        name: Bad_ID_With_Caps
        services:
          web:
            image: foo/bar:1.0
        x-forgeos:
          title: X
          main: web
    """).strip()
    with pytest.raises(fa.ManifestError):
        fa.parse_manifest(text)


def test_image_with_registry_and_port_pinned_ok():
    # registry:port/image:tag — the rsplit('/') logic must not be fooled by
    # the port colon in the registry host.
    text = textwrap.dedent("""
        name: x
        services:
          web:
            image: registry.example.com:5000/foo/bar:2.1
        x-forgeos:
          title: X
          main: web
    """).strip()
    m = fa.parse_manifest(text)
    assert "registry.example.com:5000/foo/bar:2.1" in m.images


def test_default_architectures():
    text = textwrap.dedent("""
        name: x
        services:
          web:
            image: foo/bar:1.0
        x-forgeos:
          title: X
          main: web
    """).strip()
    m = fa.parse_manifest(text)
    assert m.meta.architectures == ["amd64"]


def test_parse_file(tmp_path):
    p = tmp_path / "docker-compose.yml"
    p.write_text(_compose())
    m = fa.parse_manifest_file(p)
    assert m.app_id == "grafana"


def test_parse_file_missing(tmp_path):
    with pytest.raises(fa.ManifestError):
        fa.parse_manifest_file(tmp_path / "nope.yml")
