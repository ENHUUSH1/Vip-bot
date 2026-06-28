import sqlite3
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
import config

logger = logging.getLogger(__name__)

import os
os.makedirs("data", exist_ok=True)
DB_PATH = "data/vip_bot.db"

DEFAULT_AUTO_REPLY = (
    "🎬 VIP кино группт элсэх бол төлбөрөө төлөөд хүлээнэ үү.\n"
    "Асуух зүйл байвал бичнэ үү, бид хариулах болно!"
)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                registered_at TEXT NOT NULL,
                is_vip        INTEGER DEFAULT 0,
                vip_started   TEXT,
                vip_expires   TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        # Анхны автомат хариулт
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("auto_reply", DEFAULT_AUTO_REPLY)
        )
    logger.info("Database бэлэн болсон.")


# ─────────────────────────────────────────────
# Хэрэглэгч
# ─────────────────────────────────────────────

def register_user(user_id: int, username: str, first_name: str) -> bool:
    """Шинэ хэрэглэгч бүртгэх. Буцаах: True=шинэ, False=байсан."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()

        if existing:
            return False

        conn.execute(
            """INSERT INTO users (user_id, username, first_name, registered_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, username, first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        return True


def get_user_info(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────
# VIP
# ─────────────────────────────────────────────

def add_vip(user_id: int, days: int) -> bool:
    now = datetime.now()
    expires = now + timedelta(days=days)
    with get_conn() as conn:
        result = conn.execute(
            """UPDATE users
               SET is_vip=1, vip_started=?, vip_expires=?
               WHERE user_id=?""",
            (now.strftime("%Y-%m-%d %H:%M:%S"),
             expires.strftime("%Y-%m-%d %H:%M:%S"),
             user_id)
        )
        return result.rowcount > 0


def extend_vip(user_id: int, days: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT vip_expires, is_vip FROM users WHERE user_id=?", (user_id,)
        ).fetchone()

        if not row or not row['is_vip']:
            return False

        current_expiry = datetime.strptime(row['vip_expires'], "%Y-%m-%d %H:%M:%S")
        # Хэрэв дуусчихсан бол одооноос тооцно
        base = max(current_expiry, datetime.now())
        new_expiry = base + timedelta(days=days)

        conn.execute(
            "UPDATE users SET vip_expires=? WHERE user_id=?",
            (new_expiry.strftime("%Y-%m-%d %H:%M:%S"), user_id)
        )
        return True


def remove_vip(user_id: int) -> bool:
    with get_conn() as conn:
        result = conn.execute(
            "UPDATE users SET is_vip=0 WHERE user_id=? AND is_vip=1",
            (user_id,)
        )
        return result.rowcount > 0


def deactivate_vip(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET is_vip=0 WHERE user_id=?", (user_id,)
        )


def get_vip_expiry(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT vip_expires FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        return row['vip_expires'] if row else "-"


def get_all_vips(self=None):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE is_vip=1 ORDER BY vip_expires"
        ).fetchall()
        return [dict(r) for r in rows]


def get_expired_vips():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE is_vip=1 AND vip_expires <= ?", (now,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_vips_expiring_in_days(days: int):
    now = datetime.now()
    target_start = (now + timedelta(days=days - 1)).strftime("%Y-%m-%d %H:%M:%S")
    target_end = (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM users
               WHERE is_vip=1 AND vip_expires > ? AND vip_expires <= ?""",
            (target_start, target_end)
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Статистик
# ─────────────────────────────────────────────

def get_stats() -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_vip = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_vip=1"
        ).fetchone()[0]
        expired_vip = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_vip=0 AND vip_started IS NOT NULL"
        ).fetchone()[0]
        return {
            "total_users": total_users,
            "total_vip": total_vip,
            "expired_vip": expired_vip,
        }


# ─────────────────────────────────────────────
# Автомат хариулт
# ─────────────────────────────────────────────

def get_auto_reply() -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key='auto_reply'"
        ).fetchone()
        return row['value'] if row else DEFAULT_AUTO_REPLY


def set_auto_reply(text: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_reply', ?)",
            (text,)
        )
