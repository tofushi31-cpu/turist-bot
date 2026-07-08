# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# run the bot
python3 bot.py

# tests
pytest                          # all tests
pytest tests/test_bot.py        # one file
pytest tests/test_bot.py -k booking   # by name
```

Test config is in `pytest.ini` (`pythonpath = .`, `asyncio_mode = auto`, `testpaths = tests`) — no need to mark async tests manually.

## Architecture

Almost all logic lives in one file, **`bot.py`** (aiogram 3, async): menus, the booking FSM, admin panel, and image-card generation for Instagram posts. `db.py`, `payments.py`, and `sheets.py` are the only other modules.

**Optional integrations degrade silently.** `payments.py` (YooKassa) and `sheets.py` (Google Sheets) each check their own env vars / credentials file and return `None` / no-op if not configured (`is_configured()` in payments, `_get_worksheet()` returning `None` in sheets) — they never raise on missing config. When touching these, preserve that pattern rather than adding hard failures.

**Booking flow** is an aiogram FSM (`BookingStates` in `bot.py`): date (via inline calendar) → people count → wishes (multi-select tags) → segment (tourist/relocant) → source → optional backup contact → comment. Each step has a callback/message handler pair; state data accumulates until `handle_booking_comment` writes the row via `db.add_booking` and pushes it to `sheets.append_booking` / notifies admins.

**Static content is in-code, not in the DB**: the `tours` dict and `VISA_INFO` dict (both in `bot.py`) hold tour details and visa requirements per country. `db.py`/SQLite only stores bookings (`bookings.db`), keyed by autoincrement id with a `status` column (`new`/`confirmed`/`paid`/`cancelled`).

**Access control** is a flat env-based allowlist: `ADMIN_IDS` (or legacy `ADMIN_ID`) parsed into a set, checked via `is_admin()`. Admin-only menu items (content generation, bookings list, notifications, schedule, wish stats) are appended conditionally in `build_main_menu`.

**Image generation** (`build_content_card`, `build_visa_card` in `bot.py`, via Pillow) renders Instagram-style cards on the fly from tour photos in `images/` — gradient overlay, wrapped title/caption text, price. Not cached; regenerated per request into `tmp/`.

**Tests** stub external integrations globally via `tests/conftest.py` autouse fixtures (`sheets`/`payments` monkeypatched to act unconfigured) and use an isolated SQLite path per test (`isolated_db` fixture) — real `bookings.db` is never touched by the test suite.
