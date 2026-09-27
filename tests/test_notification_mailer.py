"""SMTP protocol tests use a fake transport, not production delivery evidence."""
import smtplib

import pytest

from packages.notification_engine import mailer


@pytest.fixture(autouse=True)
def smtp_env(monkeypatch):
    for name in ("HOST", "PORT", "USER", "PASSWORD", "FROM", "USE_SSL", "USE_TLS"):
        monkeypatch.delenv("SMTP_" + name, raising=False)
        monkeypatch.delenv("LV_SMTP_" + name, raising=False)


def test_missing_and_invalid_configuration_are_not_success(monkeypatch):
    assert mailer.send_approval_email("user@example.test", "User").status == "UNAVAILABLE"
    monkeypatch.setenv("LV_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("LV_SMTP_FROM", "sender@example.test")
    monkeypatch.setenv("LV_SMTP_PORT", "not-a-number")
    assert mailer.smtp_configuration()["error_code"] == "SMTP_INVALID_CONFIGURATION"
    monkeypatch.setenv("LV_SMTP_PORT", "587")
    monkeypatch.setenv("LV_SMTP_USE_TLS", "false")
    assert not mailer.smtp_configuration()["configured"]


@pytest.mark.parametrize("port", ["587", "465"])
def test_verified_tls_html_escaping_and_smtp_acceptance(monkeypatch, port):
    calls = []
    class SMTP:
        def __init__(self, host, port, **kwargs):
            calls.append((host, port, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def starttls(self, **kwargs):
            assert kwargs["context"].check_hostname
            calls.append("tls")
        def login(self, user, password):
            calls.append("login")
        def send_message(self, message):
            html = next(p for p in message.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
            assert "&lt;script&gt;" in html and "<script>" not in html
            calls.append("send")
            return {}
    for name, value in {"HOST":"smtp.example.test", "PORT":port, "FROM":"sender@example.test",
                        "USER":"sender", "PASSWORD":"test-secret"}.items():
        monkeypatch.setenv("LV_SMTP_" + name, value)
    monkeypatch.setattr(mailer.smtplib, "SMTP" if port == "587" else "SMTP_SSL", SMTP)
    result = mailer.send_approval_email("user@example.test", "<script>")
    assert result.status == "SMTP_ACCEPTED" and bool(result)
    assert ("tls" in calls) == (port == "587")
    assert calls[-2:] == ["login", "send"]


def test_auth_failure_is_redacted(monkeypatch, caplog):
    monkeypatch.setenv("LV_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("LV_SMTP_FROM", "sender@example.test")
    def fail(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"do-not-log-secret")
    monkeypatch.setattr(mailer.smtplib, "SMTP", fail)
    result = mailer.send_approval_email("private@example.test", "User")
    assert result.status == "FAILED" and result.error_code == "SMTP_AUTHENTICATION_FAILED"
    assert "do-not-log-secret" not in caplog.text and "private@example.test" not in caplog.text


@pytest.mark.parametrize("during_data,expected", [(True, "UNKNOWN"), (False, "SMTP_ACCEPTED")])
def test_disconnect_never_replays_ambiguous_or_accepted_mail(monkeypatch, during_data, expected):
    monkeypatch.setenv("LV_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("LV_SMTP_FROM", "sender@example.test")
    class SMTP:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            if not during_data:
                raise smtplib.SMTPServerDisconnected("quit failed")
        def starttls(self, **kwargs):
            pass
        def send_message(self, message):
            if during_data:
                raise smtplib.SMTPServerDisconnected("data reply lost")
            return {}
    monkeypatch.setattr(mailer.smtplib, "SMTP", SMTP)
    assert mailer.send_approval_email("user@example.test", "User").status == expected


def test_explicit_data_rejection_is_failed_not_ambiguous(monkeypatch):
    monkeypatch.setenv("LV_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("LV_SMTP_FROM", "sender@example.test")
    class SMTP:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def starttls(self, **kwargs):
            pass
        def send_message(self, message):
            raise smtplib.SMTPDataError(554, b"rejected")
    monkeypatch.setattr(mailer.smtplib, "SMTP", SMTP)
    assert mailer.send_approval_email("user@example.test", "User").status == "FAILED"
