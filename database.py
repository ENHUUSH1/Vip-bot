import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)
DB_PATH = 'vip_bot.db'

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            registered_at TEXT,
            is_vip      INTEGER DEFAULT 0,
            vip_started TEXT,
            vip_expiry  TEXT,
            warned_3day INTEGER DEFAULT 0,
            warned_1day INTEGER DEFAULT 0,
            greeted     INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Default auto-reply — зөвхөн анхны удаа оруулна, override хийхгүй
    c.execute('''
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('auto_reply', '🎬 VIP кино группт элсэх бол төлбөрөө төлөөд хүлээнэ үү.

Асуух зүйл байвал энэ бот руу бичнэ үү, бид удахгүй хариулна.')
    ''')

    conn.commit()
    conn.close()
    logger.info("Database initialized")

def register_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> bool:
    """Returns True if new user, False if existing."""
    conn = get_conn()
    c = conn.cursor()

    c.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    existing = c.fetchone()

    if existing:
        # Username/first_name шинэчлэнэ (өөрчлөгдсөн байж болно)
        c.execute('''
            UPDATE users SET username=?, first_name=?
            WHERE user_id=? AND (username IS NULL OR first_name IS NULL)
        ''', (username, first_name, user_id))
        conn.commit()
        conn.close()
        return False

    c.execute('''
        INSERT INTO users (user_id, username, first_name, registered_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, datetime.now().isoformat()))

    conn.commit()
    conn.close()
    return True

def ensure_user(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None):
    """Хэрэглэгч database-д байхгүй бол автоматаар нэмнэ."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, registered_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user_info(user_id: int) -> Optional[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def add_vip(user_id: int, days: int,
            username: Optional[str] = None,
            first_name: Optional[str] = None) -> datetime:
    """
    VIP эрх нэмнэ. Хэрэглэгч database-д байхгүй байсан ч
    автоматаар бүртгэж VIP нэмнэ. Үргэлж expiry datetime буцаана.
    """
    ensure_user(user_id, username, first_name)

    conn = get_conn()
    c = conn.cursor()

    start = datetime.now()
    expiry = start + timedelta(days=days)

    c.execute('''
        UPDATE users
        SET is_vip=1, vip_started=?, vip_expiry=?,
            warned_3day=0, warned_1day=0
        WHERE user_id=?
    ''', (start.isoformat(), expiry.isoformat(), user_id))

    conn.commit()
    conn.close()
    return expiry

def extend_vip(user_id: int, days: int) -> Optional[datetime]:
    conn = get_conn()
    c = conn.cursor()

    c.execute('SELECT vip_expiry, is_vip FROM users WHERE user_id=?', (user_id,))
    row = c.fetchone()

    if not row or not row['is_vip']:
        conn.close()
        return None

    current_expiry = (datetime.fromisoformat(row['vip_expiry'])
                      if row['vip_expiry'] else datetime.now())
    new_expiry = current_expiry + timedelta(days=days)

    c.execute('''
        UPDATE users SET vip_expiry=?, warned_3day=0, warned_1day=0
        WHERE user_id=?
    ''', (new_expiry.isoformat(), user_id))

    conn.commit()
    conn.close()
    return new_expiry

def remove_vip(user_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()

    c.execute('SELECT user_id FROM users WHERE user_id=?', (user_id,))
    if not c.fetchone():
        conn.close()
        return False

    c.execute('''
        UPDATE users SET is_vip=0, vip_expiry=NULL, vip_started=NULL
        WHERE user_id=?
    ''', (user_id,))

    conn.commit()
    conn.close()
    return True

def get_all_vips() -> List[Dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE is_vip=1 ORDER BY vip_expiry ASC')
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_stats() -> Dict:
    conn = get_conn()
    c = conn.cursor()

    c.execute('SELECT COUNT(*) as cnt FROM users')
    total_users = c.fetchone()['cnt']

    c.execute('SELECT COUNT(*) as cnt FROM users WHERE is_vip=1')
    total_vip = c.fetchone()['cnt']

    now = datetime.now().isoformat()
    c.execute('''
        SELECT COUNT(*) as cnt FROM users
        WHERE is_vip=0 AND vip_expiry IS NOT NULL AND vip_expiry < ?
    ''', (now,))
    expired_vip = c.fetchone()['cnt']

    conn.close()
    return {
        'total_users': total_users,
        'total_vip': total_vip,
        'expired_vip': expired_vip
    }

def get_expiring_soon(days: int) -> List[Dict]:
    """days хоногийн дараа дуусах VIP-уудыг буцаана (сануулга илгээгдээгүй)."""
    conn = get_conn()
    c = conn.cursor()

    target = datetime.now() + timedelta(days=days)
    date_str = target.strftime('%Y-%m-%d')
    warn_col = 'warned_3day' if days == 3 else 'warned_1day'

    c.execute(f'''
        SELECT * FROM users
        WHERE is_vip=1
          AND vip_expiry LIKE ?
          AND {warn_col}=0
    ''', (f'{date_str}%',))

    rows = c.fetchall()
    result = [dict(r) for r in rows]

    for r in result:
        c.execute(f'UPDATE users SET {warn_col}=1 WHERE user_id=?', (r['user_id'],))

    conn.commit()
    conn.close()
    return result

def get_expired_vips() -> List[Dict]:
    """Хугацаа нь өнгөрсөн VIP-уудыг буцаана."""
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('SELECT * FROM users WHERE is_vip=1 AND vip_expiry < ?', (now,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_auto_reply() -> str:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='auto_reply'")
    row = c.fetchone()
    conn.close()
    return row['value'] if row else "🎬 VIP группт элсэхийг хүсвэл бидэнтэй холбогдоно уу."

def set_auto_reply(text: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_reply', ?)", (text,))
    conn.commit()
    conn.close()

def should_send_greeting(user_id: int, is_new: bool) -> bool:
    """Хэрэглэгчид автомат хариу илгээх эсэхийг шалгана."""
    if is_new:
        return True
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT greeted FROM users WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row['greeted'] == 0:
        return True
    return False

def mark_greeted(user_id: int):
    """Хэрэглэгчид мэндчилгээ илгээсэн гэж тэмдэглэнэ."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET greeted=1 WHERE user_id=?', (user_id,))
    conn.commit()
    conn.close()

def reset_all_greetings():
    """/setreply хийхэд бүх хэрэглэгчийн greeted-г 0 болгоно."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET greeted=0')
    conn.commit()
    conn.close()
