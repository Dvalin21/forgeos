"""Tests for the SMTP notification sender — no real mail server needed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import forgeos_config as fc  # noqa: E402
import forgeos_smtp as sm  # noqa: E402


def _cfg(**over):
    base = dict(
        enabled=True, host="smtp.example.com", port=587, use_tls=True,
        use_ssl=False, username="alerts@example.com",
        from_addr="alerts@example.com", to_addrs=["admin@example.com"],
    )
    base.update(over)
    return fc.SmtpConfig(**base)


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, pw):
        self.logged_in = (user, pw)

    def send_message(self, msg):
        self.sent = msg


@pytest.fixture(autouse=True)
def _reset():
    FakeSMTP.instances = []


def test_build_message_sets_headers():
    msg = sm.build_message(_cfg(), "Disk failing", "sdb is dying")
    assert msg["From"] == "alerts@example.com"
    assert msg["To"] == "admin@example.com"
    assert msg["Subject"] == "[ForgeOS] Disk failing"
    assert "sdb is dying" in msg.get_content()


def test_build_message_multiple_recipients():
    cfg = _cfg(to_addrs=["a@x.com", "b@x.com"])
    msg = sm.build_message(cfg, "s", "b")
    assert msg["To"] == "a@x.com, b@x.com"


def test_build_message_requires_from():
    with pytest.raises(sm.SmtpError):
        sm.build_message(_cfg(from_addr=""), "s", "b")


def test_build_message_requires_recipients():
    with pytest.raises(sm.SmtpError):
        sm.build_message(_cfg(to_addrs=[]), "s", "b")


def test_config_rejects_bad_email():
    with pytest.raises(ValueError):
        fc.SmtpConfig(to_addrs=["not-an-email"])


def test_send_starttls_path():
    sm.send(_cfg(), "Sub", "Body", password="secret", smtp_factory=FakeSMTP)
    f = FakeSMTP.instances[0]
    assert f.host == "smtp.example.com" and f.port == 587
    assert f.started_tls is True
    assert f.logged_in == ("alerts@example.com", "secret")
    assert f.sent is not None


def test_send_ssl_path_no_starttls():
    cfg = _cfg(use_ssl=True, use_tls=False, port=465)
    sm.send(cfg, "S", "B", password="pw", smtp_factory=FakeSMTP)
    f = FakeSMTP.instances[0]
    assert f.port == 465
    assert f.started_tls is False


def test_send_no_login_when_no_username():
    cfg = _cfg(username="")
    sm.send(cfg, "S", "B", password="", smtp_factory=FakeSMTP)
    assert FakeSMTP.instances[0].logged_in is None


def test_send_disabled_raises():
    with pytest.raises(sm.SmtpError):
        sm.send(_cfg(enabled=False), "S", "B", smtp_factory=FakeSMTP)


def test_send_no_host_raises():
    with pytest.raises(sm.SmtpError):
        sm.send(_cfg(host=""), "S", "B", smtp_factory=FakeSMTP)


def test_send_safe_returns_false_on_error():
    assert sm.send_safe(_cfg(enabled=False), "S", "B", smtp_factory=FakeSMTP) is False


def test_send_safe_returns_true_on_success():
    assert sm.send_safe(_cfg(), "S", "B", password="x", smtp_factory=FakeSMTP) is True


def test_send_wraps_transport_error():
    class BoomSMTP(FakeSMTP):
        def send_message(self, msg):
            raise OSError("connection refused")
    with pytest.raises(sm.SmtpError):
        sm.send(_cfg(), "S", "B", password="x", smtp_factory=BoomSMTP)


def test_password_read_from_keystore(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "SMTP_KEY_DIR", str(tmp_path))
    (tmp_path / "password").write_text("hunter2\n")
    assert sm.read_password() == "hunter2"


def test_password_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "SMTP_KEY_DIR", str(tmp_path))
    assert sm.read_password() == ""


def test_password_not_in_config_schema():
    assert not hasattr(fc.SmtpConfig(), "password")
