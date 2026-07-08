import logging
from unittest.mock import MagicMock

import sheets


def make_booking(**overrides):
    booking = {
        "id": 42, "user_id": 555, "tour_title": "Остров Клеопатры", "tour_date": "10.10.2026",
        "people_count": 2, "alt_contact": None, "client_email": None,
        "comment": "без комментария", "created_at": "2026-07-07 10:00:00",
    }
    booking.update(overrides)
    return booking


def test_append_booking_writes_expected_row(monkeypatch):
    ws = MagicMock()
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: ws)

    sheets.append_booking(make_booking(), "не указаны", "Турист", "Инстаграм", "@ivan", "🆕 новая")

    ws.append_row.assert_called_once_with([
        42, "Остров Клеопатры", "10.10.2026", 2, "не указаны", "Турист", "Инстаграм",
        "не указан", "не указан", "@ivan", 555, "без комментария", "🆕 новая", "2026-07-07 10:00:00",
    ])


def test_append_booking_skipped_when_not_configured(monkeypatch):
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: None)
    sheets.append_booking(make_booking(), "не указаны", "Турист", "Инстаграм", "@ivan", "🆕 новая")


def test_append_booking_failure_is_logged_and_does_not_raise(monkeypatch, caplog):
    ws = MagicMock()
    ws.append_row.side_effect = RuntimeError("API недоступен")
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: ws)

    with caplog.at_level(logging.ERROR, logger="turist-bot"):
        sheets.append_booking(make_booking(), "не указаны", "Турист", "Инстаграм", "@ivan", "🆕 новая")

    assert "Не удалось добавить заявку" in caplog.text


def test_update_status_finds_row_and_updates_status_cell(monkeypatch):
    ws = MagicMock()
    ws.find.return_value = MagicMock(row=5)
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: ws)

    sheets.update_status(42, "✅ подтверждена")

    ws.find.assert_called_once_with("42", in_column=1)
    ws.update_cell.assert_called_once_with(5, sheets.STATUS_COLUMN, "✅ подтверждена")


def test_update_status_skipped_when_not_configured(monkeypatch):
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: None)
    sheets.update_status(42, "✅ подтверждена")


def test_update_status_row_not_found_is_logged_and_does_not_raise(monkeypatch, caplog):
    ws = MagicMock()
    ws.find.return_value = None
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: ws)

    with caplog.at_level(logging.WARNING, logger="turist-bot"):
        sheets.update_status(42, "✅ подтверждена")

    assert "не найдена в Google Таблице" in caplog.text
    ws.update_cell.assert_not_called()


def test_update_status_failure_is_logged_and_does_not_raise(monkeypatch, caplog):
    ws = MagicMock()
    ws.find.side_effect = RuntimeError("quota exceeded")
    monkeypatch.setattr(sheets, "_get_worksheet", lambda: ws)

    with caplog.at_level(logging.ERROR, logger="turist-bot"):
        sheets.update_status(42, "✅ подтверждена")

    assert "Не удалось обновить статус" in caplog.text
