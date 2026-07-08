import logging
from unittest.mock import MagicMock

import mailer


def test_send_email_returns_false_when_not_configured(monkeypatch, caplog):
    monkeypatch.setattr(mailer, "SMTP_USER", None)
    monkeypatch.setattr(mailer, "SMTP_PASSWORD", None)

    with caplog.at_level(logging.INFO, logger="turist-bot"):
        result = mailer.send_email("client@example.com", "Тема", "Текст письма")

    assert result is False
    assert "Почта не настроена" in caplog.text


def test_send_email_success_returns_true(monkeypatch):
    monkeypatch.setattr(mailer, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(mailer, "SMTP_PASSWORD", "secret")

    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_cls = MagicMock(return_value=smtp_instance)
    monkeypatch.setattr(mailer.smtplib, "SMTP", smtp_cls)

    result = mailer.send_email("client@example.com", "Тема", "Текст письма")

    assert result is True
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("bot@example.com", "secret")
    smtp_instance.send_message.assert_called_once()


def test_send_email_failure_is_logged_and_returns_false(monkeypatch, caplog):
    monkeypatch.setattr(mailer, "SMTP_USER", "bot@example.com")
    monkeypatch.setattr(mailer, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(mailer.smtplib, "SMTP", MagicMock(side_effect=RuntimeError("недоступно")))

    with caplog.at_level(logging.ERROR, logger="turist-bot"):
        result = mailer.send_email("client@example.com", "Тема", "Текст письма")

    assert result is False
    assert "Не удалось отправить письмо" in caplog.text
