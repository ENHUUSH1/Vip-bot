import re
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)
DB_PATH = 'vip_bot.db'

MN_TZ = ZoneInfo("Asia/Ulaanbaatar")


def now_mn() -> datetime:
    """Ð¡ÐµÑ€Ð²ÐµÑ€Ð¸Ð¹Ð½ ÑÐ¸ÑÑ‚ÐµÐ¼ ÑÐ¼Ð°Ñ€ Ñ‡ timezone-Ñ‚Ð¾Ð¹ Ð±Ð°Ð¹ÑÐ°Ð½, Ò¯Ñ€Ð³ÑÐ»Ð¶ ÐœÐ¾Ð½Ð³Ð¾Ð»Ñ‹Ð½
    (Ð£Ð»Ð°Ð°Ð½Ð±Ð°Ð°Ñ‚Ð°Ñ€, UTC+8) Ñ†Ð°Ð³Ð¸Ð¹Ð³ naive datetime Ñ…ÑÐ»Ð±ÑÑ€ÑÑÑ€ Ð±ÑƒÑ†Ð°Ð°Ð½Ð°."""
    return datetime.now(MN_TZ).replace(tzinfo=None)


_DURATION_PATTERN = re.compile(r'(\d+)([dhm])')


def parse_duration(text: str) -> Optional[timedelta]:
    """Ð¥ÑƒÐ³Ð°Ñ†Ð°Ð°Ð½Ñ‹ Ñ‚ÐµÐºÑÑ‚Ð¸Ð¹Ð³ timedelta Ð±Ð¾Ð»Ð³Ð¾Ð½Ð¾.
    d = Ñ…Ð¾Ð½Ð¾Ð³, h = Ñ†Ð°Ð³, m = Ð¼Ð¸Ð½ÑƒÑ‚. Ð–Ð¸ÑˆÑÑ: '3d', '12h', '30m', '1d12h30m'.
    Ð—Ó©Ð²Ñ…Ó©Ð½ Ñ‚Ð¾Ð¾ Ó©Ð³Ð²Ó©Ð» (Ð¶Ð¸ÑˆÑÑ '3') Ñ…ÑƒÑƒÑ‡Ð¸Ð½ Ñ‘ÑÐ¾Ð¾Ñ€ Ñ…Ð¾Ð½Ð¾Ð³ Ð³ÑÐ¶ Ñ‚Ð¾Ð¾Ñ†Ð½Ð¾."""
    if text is None:
        return None
    cleaned = text.strip().lower().replace(' ', '')
    if not cleaned:
        return None

    if cleaned.isdigit():
        return timedelta(days=int(cleaned))

    matches = _DURATION_PATTERN.findall(cleaned)
    if not matches:
        return None

    reconstructed = ''.join(f'{n}{u}' for n, u in matches)
    if reconstructed != cleaned:
        return None  # Ñ‚ÐµÐºÑÑ‚ Ð´Ð¾Ñ‚Ð¾Ñ€ Ñ‚Ð¾Ð´Ð¾Ñ€Ñ…Ð¾Ð¹Ð³Ò¯Ð¹ Ñ‚ÑÐ¼Ð´ÑÐ³Ñ‚ Ò¯Ð»Ð´ÑÑÐ½ Ð±Ð¾Ð» Ð±ÑƒÑ€ÑƒÑƒ Ð³ÑÐ¶ Ò¯Ð·Ð½Ñ

    days = hours = minutes = 0
    for num, unit in matches:
        num = int(num)
        if unit == 'd':
            days += num
        elif unit == 'h':
            hours += num
        elif unit == 'm':
            minutes += num

    total = timedelta(days=days, hours=hours, minutes=minutes)
    return total if total.total_seconds() > 0 else None

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Ð¥ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð¹Ð½ ÐµÑ€Ó©Ð½Ñ…Ð¸Ð¹ Ð¼ÑÐ´ÑÑÐ»ÑÐ»
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            registered_at TEXT
        )
    ''')

    # Ð¥ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡ Ñ‚ÑƒÑ Ð±Ò¯Ñ€Ð¸Ð¹Ð½ channel Ñ‚ÑƒÑ Ð±Ò¯Ñ€Ð¸Ð¹Ð½ VIP Ð±Ð¸Ñ‡Ð»ÑÐ³
    c.execute('''
        CREATE TABLE IF NOT EXISTS vip_memberships (
            user_id      INTEGER,
            chat_id      INTEGER,
            chat_title   TEXT,
            vip_started  TEXT,
            vip_expiry   TEXT,
            warned_3day  INTEGER DEFAULT 0,
            warned_2day  INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS message_map (
            message_id INTEGER,
            admin_id   INTEGER,
            user_id    INTEGER,
            created_at TEXT,
            PRIMARY KEY (message_id, admin_id)
        )
    ''')

    c.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('auto_reply', 'ðŸŽ¬ VIP ÐºÐ¸Ð½Ð¾ Ð³Ñ€ÑƒÐ¿Ð¿Ñ‚ ÑÐ»ÑÑÑ… Ð±Ð¾Ð» Ñ‚Ó©Ð»Ð±Ó©Ñ€Ó©Ó© Ñ‚Ó©Ð»Ó©Ó©Ð´ Ñ…Ò¯Ð»ÑÑÐ½Ñ Ò¯Ò¯.\n\nÐÑÑƒÑƒÑ… Ð·Ò¯Ð¹Ð» Ð±Ð°Ð¹Ð²Ð°Ð» ÑÐ½Ñ Ð±Ð¾Ñ‚ Ñ€ÑƒÑƒ Ð±Ð¸Ñ‡Ð½Ñ Ò¯Ò¯, Ð±Ð¸Ð´ ÑƒÐ´Ð°Ñ…Ð³Ò¯Ð¹ Ñ…Ð°Ñ€Ð¸ÑƒÐ»Ð½Ð°.')
    ''')

    conn.commit()
    conn.close()
    logger.info("Database initialized")


def register_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    existing = c.fetchone()
    if existing:
        c.execute('UPDATE users SET username=?, first_name=? WHERE user_id=?',
                  (username, first_name, user_id))
        conn.commit()
        conn.close()
        return False
    c.execute('''
        INSERT INTO users (user_id, username, first_name, registered_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, now_mn().isoformat()))
    conn.commit()
    conn.close()
    return True


def ensure_user(user_id: int, username=None, first_name=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, registered_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, now_mn().isoformat()))
    conn.commit()
    conn.close()


def get_user_info(user_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def save_message_map(message_id: int, user_id: int, admin_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO message_map (message_id, admin_id, user_id, created_at)
        VALUES (?, ?, ?, ?)
    ''', (message_id, admin_id, user_id, now_mn().isoformat()))
    conn.commit()
    conn.close()


def get_user_from_message(message_id: int, admin_id: int) -> Optional[int]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT user_id FROM message_map WHERE message_id=? AND admin_id=?',
              (message_id, admin_id))
    row = c.fetchone()
    conn.close()
    return row['user_id'] if row else None


# â”€â”€â”€ VIP MEMBERSHIPS (channel Ñ‚ÑƒÑ Ð±Ò¯Ñ€ÑÑÑ€ Ñ‚ÑƒÑÐ´Ð°Ð°) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def add_vip(user_id: int, chat_id: int, duration: timedelta, chat_title: str = "",
            username=None, first_name=None) -> datetime:
    """Ð¢ÑƒÑ…Ð°Ð¹Ð½ user-Ð¸Ð¹Ð³ Ñ‚ÑƒÑ…Ð°Ð¹Ð½ chat_id-Ð´ VIP Ð±Ð¾Ð»Ð³Ð¾Ð½Ð¾. ÐÐ»ÑŒ Ñ…ÑÐ´Ð¸Ð¹Ð½ Ð¸Ð´ÑÐ²Ñ…Ñ‚ÑÐ¹ Ð±Ð¾Ð»
    Ð¾Ð´Ð¾Ð¾Ð³Ð¸Ð¹Ð½ Ð´ÑƒÑƒÑÐ°Ñ… Ñ…ÑƒÐ³Ð°Ñ†Ð°Ð°Ð½Ð°Ð°Ñ (ÑÑÐ²ÑÐ» Ð¾Ð´Ð¾Ð¾Ð½Ð¾Ð¾Ñ) duration-Ð¸Ð¹Ð³ Ð½ÑÐ¼Ð½Ñ."""
    ensure_user(user_id, username, first_name)
    conn = get_conn()
    c = conn.cursor()

    c.execute('SELECT vip_expiry FROM vip_memberships WHERE user_id=? AND chat_id=?',
              (user_id, chat_id))
    row = c.fetchone()

    now = now_mn()
    if row and row['vip_expiry']:
        existing_expiry = datetime.fromisoformat(row['vip_expiry'])
        base = existing_expiry if existing_expiry > now else now
    else:
        base = now

    expiry = base + duration

    c.execute('''
        INSERT INTO vip_memberships (user_id, chat_id, chat_title, vip_started, vip_expiry, warned_3day, warned_2day)
        VALUES (?, ?, ?, ?, ?, 0, 0)
        ON CONFLICT(user_id, chat_id) DO UPDATE SET
            chat_title=excluded.chat_title,
            vip_expiry=excluded.vip_expiry,
            warned_3day=0,
            warned_2day=0
    ''', (user_id, chat_id, chat_title, now.isoformat(), expiry.isoformat()))

    conn.commit()
    conn.close()
    return expiry


def set_vip(user_id: int, chat_id: int, duration: timedelta, chat_title: str = "",
            username=None, first_name=None) -> datetime:
    """Ð¢ÑƒÑ…Ð°Ð¹Ð½ user-Ð¸Ð¹Ð½ VIP Ñ…ÑƒÐ³Ð°Ñ†Ð°Ð°Ð³ ÐžÐ”ÐžÐžÐ“ÐžÐžÐ¡ ÑÑ…Ð»Ò¯Ò¯Ð»Ð¶ Ð¨Ð˜ÐÐ­Ð­Ð  Ñ‚Ð¾Ð³Ñ‚Ð¾Ð¾Ð½Ð¾
    (Ñ…ÑƒÑƒÑ‡Ð¸Ð½ Ð´ÑƒÑƒÑÐ°Ñ… Ñ…ÑƒÐ³Ð°Ñ†Ð°Ð°Ð³ Ò¯Ð» Ñ‚Ð¾Ð¾Ñ†Ð½Ð¾). Ð‘ÑƒÑ€ÑƒÑƒ Ð¾Ñ€ÑƒÑƒÐ»ÑÐ°Ð½ Ñ…ÑƒÐ³Ð°Ñ†Ð°Ð°Ð³ Ð·Ð°ÑÐ°Ñ…Ð°Ð´ Ð°ÑˆÐ¸Ð³Ð»Ð°Ð½Ð°."""
    ensure_user(user_id, username, first_name)
    conn = get_conn()
    c = conn.cursor()

    now = now_mn()
    expiry = now + duration

    c.execute('''
        INSERT INTO vip_memberships (user_id, chat_id, chat_title, vip_started, vip_expiry, warned_3day, warned_2day)
        VALUES (?, ?, ?, ?, ?, 0, 0)
        ON CONFLICT(user_id, chat_id) DO UPDATE SET
            chat_title=excluded.chat_title,
            vip_expiry=excluded.vip_expiry,
            warned_3day=0,
            warned_2day=0
    ''', (user_id, chat_id, chat_title, now.isoformat(), expiry.isoformat()))

    conn.commit()
    conn.close()
    return expiry


def extend_vip(user_id: int, chat_id: int, duration: timedelta) -> Optional[datetime]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT vip_expiry FROM vip_memberships WHERE user_id=? AND chat_id=?',
              (user_id, chat_id))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    current = datetime.fromisoformat(row['vip_expiry']) if row['vip_expiry'] else now_mn()
    base = current if current > now_mn() else now_mn()
    new_expiry = base + duration
    c.execute('''
        UPDATE vip_memberships SET vip_expiry=?, warned_3day=0, warned_2day=0
        WHERE user_id=? AND chat_id=?
    ''', (new_expiry.isoformat(), user_id, chat_id))
    conn.commit()
    conn.close()
    return new_expiry


def remove_vip(user_id: int, chat_id: int) -> bool:
    """Ð¢ÑƒÑ…Ð°Ð¹Ð½ user-Ð¸Ð¹Ð³ Ð·Ó©Ð²Ñ…Ó©Ð½ Ñ‚ÑƒÑ…Ð°Ð¹Ð½ chat_id-Ð¸Ð¹Ð½ VIP-Ð°Ð°Ñ Ñ…Ð°ÑÐ½Ð° (Ð±ÑƒÑÐ°Ð´ channel-Ð´ Ñ…ÑÐ²ÑÑÑ€)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT user_id FROM vip_memberships WHERE user_id=? AND chat_id=?',
              (user_id, chat_id))
    if not c.fetchone():
        conn.close()
        return False
    c.execute('DELETE FROM vip_memberships WHERE user_id=? AND chat_id=?', (user_id, chat_id))
    conn.commit()
    conn.close()
    return True


def remove_vip_all(user_id: int) -> List[int]:
    """Ð¥ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð¹Ð³ Ð‘Ò®Ð¥ channel-Ð°Ð°Ñ Ñ…Ð°ÑÐ½Ð°. Ð¥Ð°ÑÐ°Ð³Ð´ÑÐ°Ð½ chat_id-ÑƒÑƒÐ´Ñ‹Ð³ Ð±ÑƒÑ†Ð°Ð°Ð½Ð°."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT chat_id FROM vip_memberships WHERE user_id=?', (user_id,))
    chat_ids = [r['chat_id'] for r in c.fetchall()]
    c.execute('DELETE FROM vip_memberships WHERE user_id=?', (user_id,))
    conn.commit()
    conn.close()
    return chat_ids


def get_vip_memberships(user_id: int) -> List[Dict]:
    """Ð¢ÑƒÑ…Ð°Ð¹Ð½ Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð¹Ð½ Ð±Ò¯Ñ… Ð¸Ð´ÑÐ²Ñ…Ñ‚ÑÐ¹ VIP Ð±Ð¸Ñ‡Ð»ÑÐ³Ò¯Ò¯Ð´."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM vip_memberships WHERE user_id=? ORDER BY vip_expiry ASC', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_vips() -> List[Dict]:
    """Ð‘Ò¯Ñ… Ð¸Ð´ÑÐ²Ñ…Ñ‚ÑÐ¹ VIP Ð±Ð¸Ñ‡Ð»ÑÐ³Ò¯Ò¯Ð´ (Ð±Ò¯Ñ… Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡, Ð±Ò¯Ñ… channel) Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð¹Ð½ Ð½ÑÑ€Ñ‚ÑÐ¹ Ñ…Ð°Ð¼Ñ‚."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT vm.*, u.username, u.first_name
        FROM vip_memberships vm
        LEFT JOIN users u ON vm.user_id = u.user_id
        ORDER BY vm.vip_expiry ASC
    ''')
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> Dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as cnt FROM users')
    total_users = c.fetchone()['cnt']
    c.execute('SELECT COUNT(*) as cnt FROM vip_memberships')
    total_vip = c.fetchone()['cnt']
    c.execute('SELECT COUNT(DISTINCT user_id) as cnt FROM vip_memberships')
    total_vip_users = c.fetchone()['cnt']
    conn.close()
    return {
        'total_users': total_users,
        'total_vip': total_vip,
        'total_vip_users': total_vip_users
    }


def get_expiring_soon(days: int) -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    target = now_mn() + timedelta(days=days)
    date_str = target.strftime('%Y-%m-%d')
    warn_col = 'warned_3day' if days == 3 else 'warned_2day'
    c.execute(f'''
        SELECT vm.*, u.username, u.first_name
        FROM vip_memberships vm
        LEFT JOIN users u ON vm.user_id = u.user_id
        WHERE vm.vip_expiry LIKE ? AND vm.{warn_col}=0
    ''', (f'{date_str}%',))
    rows = c.fetchall()
    result = [dict(r) for r in rows]
    for r in result:
        c.execute(f'UPDATE vip_memberships SET {warn_col}=1 WHERE user_id=? AND chat_id=?',
                  (r['user_id'], r['chat_id']))
    conn.commit()
    conn.close()
    return result


def get_expired_vips() -> List[Dict]:
    """Ð¥ÑƒÐ³Ð°Ñ†Ð°Ð° Ð´ÑƒÑƒÑÑÐ°Ð½ Ð±Ð¸Ñ‡Ð»ÑÐ³Ò¯Ò¯Ð´ (Ð±Ò¯Ñ… channel Ð´Ð¾Ñ‚Ñ€Ð¾Ð¾Ñ)."""
    conn = get_conn()
    c = conn.cursor()
    now = now_mn().isoformat()
    c.execute('''
        SELECT vm.*, u.username, u.first_name
        FROM vip_memberships vm
        LEFT JOIN users u ON vm.user_id = u.user_id
        WHERE vm.vip_expiry < ?
    ''', (now,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_auto_reply() -> str:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='auto_reply'")
    row = c.fetchone()
    conn.close()
    return row['value'] if row else "ðŸŽ¬ VIP Ð³Ñ€ÑƒÐ¿Ð¿Ñ‚ ÑÐ»ÑÑÑ…Ð¸Ð¹Ð³ Ñ…Ò¯ÑÐ²ÑÐ» Ð±Ð¸Ð´ÑÐ½Ñ‚ÑÐ¹ Ñ…Ð¾Ð»Ð±Ð¾Ð³Ð´Ð¾Ð½Ð¾ ÑƒÑƒ."


def set_auto_reply(text: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_reply', ?)", (text,))
    conn.commit()
    conn.close()
