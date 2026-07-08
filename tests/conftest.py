import asyncio

import pytest

import db
import mailer
import payments
import sheets


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_bookings.db")
    db.init_db()
    return db


@pytest.fixture(scope="session", autouse=True)
def _close_bot_session():
    yield
    import bot

    asyncio.run(bot.bot.session.close())


@pytest.fixture(autouse=True)
def _stub_external_integrations(monkeypatch):
    monkeypatch.setattr(sheets, "_worksheet", None)
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: None)
    monkeypatch.setattr(payments, "YOOKASSA_SHOP_ID", None)
    monkeypatch.setattr(payments, "YOOKASSA_SECRET_KEY", None)
    monkeypatch.setattr(mailer, "SMTP_USER", None)
    monkeypatch.setattr(mailer, "SMTP_PASSWORD", None)
