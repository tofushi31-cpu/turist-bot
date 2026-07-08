import sqlite3

import db


def test_add_booking_stores_custom_wish(isolated_db):
    booking_id = db.add_booking(
        user_id=1, username="tester", tour_id="tour_1", tour_title="Тур",
        tour_date="10.10.2026", comment="без комментария", custom_wish="Хочу яхту",
    )
    booking = db.get_booking(booking_id)
    assert booking["custom_wish"] == "Хочу яхту"


def test_add_booking_custom_wish_defaults_to_none(isolated_db):
    booking_id = db.add_booking(
        user_id=2, username="tester2", tour_id="tour_1", tour_title="Тур",
        tour_date="10.10.2026", comment="без комментария",
    )
    booking = db.get_booking(booking_id)
    assert booking["custom_wish"] is None


def test_init_db_migrates_custom_wish_column_on_old_schema(tmp_path, monkeypatch):
    old_db_path = tmp_path / "legacy.db"
    with sqlite3.connect(old_db_path) as conn:
        conn.execute(
            """
            CREATE TABLE bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                tour_id TEXT NOT NULL,
                tour_title TEXT NOT NULL,
                tour_date TEXT,
                comment TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

    monkeypatch.setattr(db, "DB_PATH", old_db_path)
    db.init_db()

    with sqlite3.connect(old_db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(bookings)")]
    assert "custom_wish" in columns

    booking_id = db.add_booking(
        user_id=3, username="tester3", tour_id="tour_1", tour_title="Тур",
        tour_date="10.10.2026", comment="без комментария", custom_wish="Особое пожелание",
    )
    assert db.get_booking(booking_id)["custom_wish"] == "Особое пожелание"


def test_get_setting_returns_default_when_missing(isolated_db):
    assert db.get_setting("rental_price_text", default="нет данных") == "нет данных"
    assert db.get_setting("rental_price_text") is None


def test_set_setting_then_get_setting_round_trip(isolated_db):
    db.set_setting("rental_price_text", "150-300 THB/день")
    assert db.get_setting("rental_price_text") == "150-300 THB/день"


def test_set_setting_overwrites_existing_value(isolated_db):
    db.set_setting("rental_price_text", "150-300 THB/день")
    db.set_setting("rental_price_text", "200-350 THB/день")
    assert db.get_setting("rental_price_text") == "200-350 THB/день"


def test_list_tour_photos_empty_for_tour_without_uploads(isolated_db):
    assert db.list_tour_photos("tour_1") == []


def test_add_tour_photo_then_list_tour_photos_round_trip(isolated_db):
    db.add_tour_photo("tour_1", "tour_1_upload_abc.jpg")
    assert db.list_tour_photos("tour_1") == ["tour_1_upload_abc.jpg"]


def test_list_tour_photos_preserves_insertion_order_and_is_scoped_to_tour(isolated_db):
    db.add_tour_photo("tour_1", "tour_1_upload_first.jpg")
    db.add_tour_photo("tour_2", "tour_2_upload_other.jpg")
    db.add_tour_photo("tour_1", "tour_1_upload_second.jpg")

    assert db.list_tour_photos("tour_1") == ["tour_1_upload_first.jpg", "tour_1_upload_second.jpg"]
    assert db.list_tour_photos("tour_2") == ["tour_2_upload_other.jpg"]
