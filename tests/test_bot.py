import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import bot as bot_module

HINT_TEXT = "Пожалуйста, выбери вариант, нажав на кнопку выше 👆"


class FakeState:
    def __init__(self, data=None):
        self._data = dict(data or {})
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)
        return dict(self._data)

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        self._data = {}
        self.state = None


def make_message(text="", user_id=1, username="tester"):
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    message.from_user = MagicMock(id=user_id, username=username, full_name="Test User")
    return message


def make_callback(data, user_id=1):
    callback = MagicMock()
    callback.data = data
    callback.from_user = MagicMock(id=user_id)
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.message.answer_photo = AsyncMock()
    callback.answer = AsyncMock()
    return callback


# --- Подсказки при неверном вводе (не по кнопке) ---

async def test_wishes_text_hint_prompts_to_use_buttons():
    message = make_message("привет")
    await bot_module.handle_wishes_text_hint(message)
    message.answer.assert_awaited_once_with(HINT_TEXT)


async def test_segment_text_hint_prompts_to_use_buttons():
    message = make_message("турист")
    await bot_module.handle_segment_text_hint(message)
    message.answer.assert_awaited_once_with(HINT_TEXT)


async def test_source_text_hint_prompts_to_use_buttons():
    message = make_message("инстаграм")
    await bot_module.handle_source_text_hint(message)
    message.answer.assert_awaited_once_with(HINT_TEXT)


# --- format_booking_wishes (своё пожелание + видимость в списках) ---

def test_format_booking_wishes_combines_tags_and_custom():
    booking = {"wishes": "sunset,food", "custom_wish": "Хочу вечером у моря"}
    result = bot_module.format_booking_wishes(booking)
    assert result == "🌅 Закат и красивые фото, 🍽 Особая еда/диета, Хочу вечером у моря"


def test_format_booking_wishes_empty():
    assert bot_module.format_booking_wishes({"wishes": None, "custom_wish": None}) == "не указаны"


def test_format_booking_wishes_only_custom():
    booking = {"wishes": "", "custom_wish": "Особое пожелание"}
    assert bot_module.format_booking_wishes(booking) == "Особое пожелание"


# --- Ошибки отправки логируются, а не глотаются молча ---

async def test_admin_notification_failure_is_logged_and_does_not_block_other_admins(monkeypatch, caplog):
    monkeypatch.setattr(bot_module, "ADMIN_IDS", {111, 222})
    monkeypatch.setattr(bot_module.db, "add_booking", MagicMock(return_value=42))
    monkeypatch.setattr(
        bot_module.db, "get_booking",
        MagicMock(return_value={"id": 42, "tour_title": "Остров Клеопатры", "user_id": 1}),
    )

    send_calls = []

    async def fake_send_message(chat_id, *args, **kwargs):
        send_calls.append(chat_id)
        if chat_id == 111:
            raise RuntimeError("Telegram недоступен")

    monkeypatch.setattr(bot_module.bot, "send_message", AsyncMock(side_effect=fake_send_message))

    state = FakeState({
        "tour_id": "tour_1", "tour_date": "10.10.2026",
        "people_count": "2", "wishes": [], "segment": "tourist", "source": "instagram",
    })
    message = make_message("+")

    with caplog.at_level(logging.ERROR, logger="turist-bot"):
        await bot_module.handle_booking_comment(message, state)

    assert sorted(send_calls) == [111, 222]
    assert "Не удалось отправить заявку" in caplog.text


async def test_reminder_send_failure_is_logged_and_reminder_still_marked(monkeypatch, caplog):
    booking = {
        "id": 7, "user_id": 555, "tour_title": "Панва Айленд", "tour_date": "10.10.2026",
        "status": "confirmed", "reminder_3d_sent": 0, "reminder_1d_sent": 0,
    }
    monkeypatch.setattr(bot_module.db, "list_all_bookings", MagicMock(return_value=[booking]))
    marked = []
    monkeypatch.setattr(
        bot_module.db, "mark_reminder_sent",
        lambda booking_id, which: marked.append((booking_id, which)),
    )
    monkeypatch.setattr(
        bot_module, "parse_tour_date",
        lambda text: datetime.now() + timedelta(days=3),
    )
    monkeypatch.setattr(bot_module.bot, "send_message", AsyncMock(side_effect=RuntimeError("сеть упала")))

    with caplog.at_level(logging.ERROR, logger="turist-bot"):
        await bot_module.send_reminders_once()

    assert marked == [(7, "3d")]
    assert "Не удалось отправить напоминание" in caplog.text


# --- Черновики контента больше не конфликтуют с данными брони (draft_tour_id/draft_variant) ---

async def test_draft_flow_uses_prefixed_keys_and_does_not_collide_with_booking_tour_id(monkeypatch):
    monkeypatch.setattr(bot_module, "generate_caption", lambda tour, variant: f"caption v{variant}")
    monkeypatch.setattr(bot_module, "build_content_card", lambda tour, out_path: out_path)

    admin_id = next(iter(bot_module.ADMIN_IDS)) if bot_module.ADMIN_IDS else 999
    monkeypatch.setattr(bot_module, "ADMIN_IDS", {admin_id})

    state = FakeState({"tour_id": "some_booking_in_progress", "people_count": "3"})
    callback = make_callback("draft_tour_1", user_id=admin_id)

    await bot_module.handle_draft_start(callback, state)
    data = await state.get_data()
    assert data["draft_tour_id"] == "tour_1"
    assert data["draft_variant"] == 0
    assert data["tour_id"] == "some_booking_in_progress"

    callback2 = make_callback("draft_regen", user_id=admin_id)
    await bot_module.handle_draft_regen(callback2, state)
    data = await state.get_data()
    assert data["draft_variant"] == 1
    assert data["tour_id"] == "some_booking_in_progress"
