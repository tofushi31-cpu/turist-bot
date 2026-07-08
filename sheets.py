import logging
import os

import gspread

logger = logging.getLogger("turist-bot")

GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")

HEADERS = [
    "ID", "Тур", "Дата тура", "Человек", "Пожелания", "Сегмент", "Источник",
    "Запасной контакт", "Клиент", "ID клиента", "Комментарий", "Статус", "Создано",
]
STATUS_COLUMN = 12

_worksheet = None


def _get_worksheet():
    global _worksheet
    if _worksheet is not None:
        return _worksheet

    if not GOOGLE_SHEETS_ID or not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        logger.info("Google Sheets не настроен — синхронизация пропущена")
        return None

    try:
        client = gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)
        worksheet = client.open_by_key(GOOGLE_SHEETS_ID).sheet1
        if not worksheet.acell("A1").value:
            worksheet.append_row(HEADERS)
        _worksheet = worksheet
    except Exception:
        logger.exception("Не удалось подключиться к Google Таблице")
        return None

    return _worksheet


def append_booking(booking, wishes_text, segment_label, source_label, customer_name, status_label):
    ws = _get_worksheet()
    if ws is None:
        return
    try:
        ws.append_row([
            booking["id"], booking["tour_title"], booking.get("tour_date") or "не указана",
            booking.get("people_count") or "не указано", wishes_text, segment_label, source_label,
            booking.get("alt_contact") or "не указан", customer_name, booking["user_id"],
            booking.get("comment") or "", status_label, booking.get("created_at") or "",
        ])
    except Exception:
        logger.exception("Не удалось добавить заявку #%s в Google Таблицу", booking.get("id"))


def update_status(booking_id, status_label):
    ws = _get_worksheet()
    if ws is None:
        return
    try:
        cell = ws.find(str(booking_id), in_column=1)
        if cell is None:
            logger.warning("Заявка #%s не найдена в Google Таблице для обновления статуса", booking_id)
            return
        ws.update_cell(cell.row, STATUS_COLUMN, status_label)
    except Exception:
        logger.exception("Не удалось обновить статус заявки #%s в Google Таблице", booking_id)
