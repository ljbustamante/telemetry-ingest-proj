from __future__ import annotations

import src.application.job_failure_notifier as notifier_mod
from src.application.job_failure_notifier import notify_job_failure


class _FakeSES:
    def __init__(self):
        self.sent = {}

    def send_email(self, **kwargs):
        self.sent.update(kwargs)


def test_notify_skips_when_env_vars_missing(monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL_FROM", raising=False)
    monkeypatch.delenv("JOB_FAILURE_EMAIL_TO", raising=False)
    ses = _FakeSES()
    monkeypatch.setattr(notifier_mod.boto3, "client", lambda name, region_name=None: ses)
    notify_job_failure("test-job", ValueError("oops"))
    assert not ses.sent


def test_notify_skips_when_from_missing(monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL_FROM", raising=False)
    monkeypatch.setenv("JOB_FAILURE_EMAIL_TO", "ops@example.com")
    ses = _FakeSES()
    monkeypatch.setattr(notifier_mod.boto3, "client", lambda name, region_name=None: ses)
    notify_job_failure("test-job", ValueError("oops"))
    assert not ses.sent


def test_notify_sends_email_when_configured(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("JOB_FAILURE_EMAIL_TO", "ops@example.com")
    ses = _FakeSES()
    monkeypatch.setattr(notifier_mod.boto3, "client", lambda name, region_name=None: ses)

    notify_job_failure("my-job", RuntimeError("boom"))

    assert ses.sent["Source"] == "from@example.com"
    assert "ops@example.com" in ses.sent["Destination"]["ToAddresses"]
    assert "my-job" in ses.sent["Message"]["Subject"]["Data"]


def test_notify_includes_error_in_body(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("JOB_FAILURE_EMAIL_TO", "ops@example.com")
    ses = _FakeSES()
    monkeypatch.setattr(notifier_mod.boto3, "client", lambda name, region_name=None: ses)

    notify_job_failure("data-job", ValueError("disk full"))

    text_body = ses.sent["Message"]["Body"]["Text"]["Data"]
    assert "disk full" in text_body
    assert "data-job" in text_body


def test_notify_multiple_recipients(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("JOB_FAILURE_EMAIL_TO", "a@example.com, b@example.com")
    ses = _FakeSES()
    monkeypatch.setattr(notifier_mod.boto3, "client", lambda name, region_name=None: ses)

    notify_job_failure("job", ValueError("err"))

    recipients = ses.sent["Destination"]["ToAddresses"]
    assert "a@example.com" in recipients
    assert "b@example.com" in recipients


def test_notify_never_raises_when_ses_fails(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("JOB_FAILURE_EMAIL_TO", "ops@example.com")

    class _BrokenSES:
        def send_email(self, **kwargs):
            raise RuntimeError("SES unavailable")

    monkeypatch.setattr(notifier_mod.boto3, "client", lambda name, region_name=None: _BrokenSES())
    notify_job_failure("my-job", ValueError("original"))
