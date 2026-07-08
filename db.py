import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "bookings.db"

STATUSES = ("new", "confirmed", "paid", "cancelled")


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                tour_id TEXT NOT NULL,
                tour_title TEXT NOT NULL,
                tour_date TEXT,
                comment TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                reminder_3d_sent INTEGER NOT NULL DEFAULT 0,
                reminder_1d_sent INTEGER NOT NULL DEFAULT 0,
                people_count INTEGER,
                wishes TEXT,
                segment TEXT,
                source TEXT,
                alt_contact TEXT,
                custom_wish TEXT
            )
            """
        )
        columns = [row[1] for row in conn.execute("PRAGMA table_info(bookings)")]
        migrations = {
            "tour_date": "TEXT",
            "reminder_3d_sent": "INTEGER NOT NULL DEFAULT 0",
            "reminder_1d_sent": "INTEGER NOT NULL DEFAULT 0",
            "people_count": "INTEGER",
            "wishes": "TEXT",
            "segment": "TEXT",
            "source": "TEXT",
            "alt_contact": "TEXT",
            "custom_wish": "TEXT",
        }
        for column, decl in migrations.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE bookings ADD COLUMN {column} {decl}")


def add_booking(
    user_id: int,
    username: str,
    tour_id: str,
    tour_title: str,
    tour_date: str,
    comment: str,
    people_count: int | None = None,
    wishes: str | None = None,
    segment: str | None = None,
    source: str | None = None,
    alt_contact: str | None = None,
    custom_wish: str | None = None,
) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO bookings "
            "(user_id, username, tour_id, tour_title, tour_date, comment, "
            " people_count, wishes, segment, source, alt_contact, custom_wish) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, username, tour_id, tour_title, tour_date, comment,
                people_count, wishes, segment, source, alt_contact, custom_wish,
            ),
        )
        return cursor.lastrowid


def update_status(booking_id: int, status: str):
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))


def mark_reminder_sent(booking_id: int, which: str):
    column = f"reminder_{which}_sent"
    if column not in ("reminder_3d_sent", "reminder_1d_sent"):
        raise ValueError(f"Unknown reminder: {which}")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE bookings SET {column} = 1 WHERE id = ?", (booking_id,))


def get_booking(booking_id: int) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else None


def count_wishes() -> dict[str, int]:
    counts: dict[str, int] = {}
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT wishes FROM bookings WHERE status != 'cancelled' AND wishes IS NOT NULL AND wishes != ''"
        ).fetchall()
    for (wishes_str,) in rows:
        for tag in wishes_str.split(","):
            tag = tag.strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return counts


def list_recent_bookings(limit: int = 10) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM bookings ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def list_all_bookings() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM bookings WHERE status != 'cancelled' ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_client_bookings(user_id: int) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM bookings WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]
