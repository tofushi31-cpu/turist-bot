import logging
from unittest.mock import MagicMock

import payments


def test_create_payment_link_builds_request_and_returns_url(monkeypatch):
    monkeypatch.setattr(payments, "YOOKASSA_SHOP_ID", "shop123")
    monkeypatch.setattr(payments, "YOOKASSA_SECRET_KEY", "secret123")
    fake_payment = MagicMock()
    fake_payment.confirmation.confirmation_url = "https://yookassa.ru/pay/abc"
    monkeypatch.setattr(payments.Payment, "create", MagicMock(return_value=fake_payment))

    url = payments.create_payment_link(42, "1500", "Оплата тура «Остров Клеопатры» (заявка #42)")

    assert url == "https://yookassa.ru/pay/abc"
    request, _idempotence_key = payments.Payment.create.call_args.args
    assert request["amount"] == {"value": "1500.00", "currency": "RUB"}
    assert request["description"] == "Оплата тура «Остров Клеопатры» (заявка #42)"
    assert request["metadata"] == {"booking_id": 42}


def test_create_payment_link_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(payments, "YOOKASSA_SHOP_ID", None)
    monkeypatch.setattr(payments, "YOOKASSA_SECRET_KEY", None)
    assert payments.create_payment_link(42, "1500", "тест") is None


def test_create_payment_link_failure_is_logged_and_returns_none(monkeypatch, caplog):
    monkeypatch.setattr(payments, "YOOKASSA_SHOP_ID", "shop123")
    monkeypatch.setattr(payments, "YOOKASSA_SECRET_KEY", "secret123")
    monkeypatch.setattr(payments.Payment, "create", MagicMock(side_effect=RuntimeError("недоступно")))

    with caplog.at_level(logging.ERROR, logger="turist-bot"):
        url = payments.create_payment_link(42, "1500", "тест")

    assert url is None
    assert "Не удалось создать ссылку на оплату" in caplog.text
