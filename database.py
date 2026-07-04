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
    """Серверийн систем ямар ч timezone-той байсан, үргэлж Монголын
    (Улаанбаатар, UTC+8) цагийг naive datetime хэлбэрээр буцаана."""
    return datetime.now(MN_TZ).replace(tzinfo=None)


_DURATION_PATTERN = re.compile(r'(\d+)([dhm])')


def parse_duration(text: str) -> Optional[timedelta]:
    """Хугацааны текстийг timedelta болгоно.
    d = хоног, h = цаг, m = минут. Жишээ: '3d', '12h', '30m', '1d12h30m'.
    Зөвхөн тоо өгвөл (жишээ '3') хуучин ёсоор хоног гэж тооцно."""
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
        return None  # текст дотор тодорхойгүй тэмдэгт үлдсэн бол буруу гэж үзнэ

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

    # Хэрэглэгчийн ерөнхий мэдээлэл
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            registered_at TEXT
        )
    ''')

    # Хэрэглэгч тус бүрийн channel тус бүрийн VIP бичлэг
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
        VALUES ('auto_reply', '🎬 VIP кино группт элсэх бол төлбөрөө төлөөд хүлээнэ үү.\n\nАсуух зүйл байвал энэ бот руу бичнэ үү, бид удахгүй хариулна.')
    ''')

    # Суваг тус бүрийн кино тоо (channel_post ирэх бүрт автоматаар нэмэгдэнэ)
    c.execute('''
        CREATE TABLE IF NOT EXISTS movie_counts (
            chat_id    INTEGER PRIMARY KEY,
            chat_title TEXT,
            count      INTEGER DEFAULT 0
        )
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


# ─── VIP MEMBERSHIPS (channel тус бүрээр тусдаа) ──────────────────

def add_vip(user_id: int, chat_id: int, duration: timedelta, chat_title: str = "",
            username=None, first_name=None) -> datetime:
    """Тухайн user-ийг тухайн chat_id-д VIP болгоно. Аль хэдийн идэвхтэй бол
    одоогийн дуусах хугацаанаас (эсвэл одооноос) duration-ийг нэмнэ."""
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
    """Тухайн user-ийн VIP хугацааг ОДООГООС эхлүүлж ШИНЭЭР тогтооно
    (хуучин дуусах хугацааг үл тооцно). Буруу оруулсан хугацааг засахад ашиглана."""
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
    """Тухайн user-ийг зөвхөн тухайн chat_id-ийн VIP-аас хасна (бусад channel-д хэвээр)."""
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
    """Хэрэглэгчийг БҮХ channel-аас хасна. Хасагдсан chat_id-уудыг буцаана."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT chat_id FROM vip_memberships WHERE user_id=?', (user_id,))
    chat_ids = [r['chat_id'] for r in c.fetchall()]
    c.execute('DELETE FROM vip_memberships WHERE user_id=?', (user_id,))
    conn.commit()
    conn.close()
    return chat_ids


def get_vip_memberships(user_id: int) -> List[Dict]:
    """Тухайн хэрэглэгчийн бүх идэвхтэй VIP бичлэгүүд."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM vip_memberships WHERE user_id=? ORDER BY vip_expiry ASC', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_vips() -> List[Dict]:
    """Бүх идэвхтэй VIP бичлэгүүд (бүх хэрэглэгч, бүх channel) хэрэглэгчийн нэртэй хамт."""
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
    """Хугацаа дууссан бичлэгүүд (бүх channel дотроос)."""
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
    return row['value'] if row else "🎬 VIP группт элсэхийг хүсвэл бидэнтэй холбогдоно уу."


def set_auto_reply(text: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_reply', ?)", (text,))
    conn.commit()
    conn.close()


# ─── КИНО ТОО (channel тус бүрээр) ─────────────────────────────────

def increment_movie_count(chat_id: int, chat_title: str = "", by: int = 1) -> int:
    """Сувагт шинэ кино (channel_post) ирэхэд дуудагдана. Шинэ тоог буцаана."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT count, chat_title FROM movie_counts WHERE chat_id=?', (chat_id,))
    row = c.fetchone()
    if row:
        new_count = row['count'] + by
        title_to_save = chat_title or row['chat_title']
        c.execute('UPDATE movie_counts SET count=?, chat_title=? WHERE chat_id=?',
                  (new_count, title_to_save, chat_id))
    else:
        new_count = by
        c.execute('INSERT INTO movie_counts (chat_id, chat_title, count) VALUES (?, ?, ?)',
                  (chat_id, chat_title, new_count))
    conn.commit()
    conn.close()
    return new_count


def set_movie_count(chat_id: int, count: int, chat_title: Optional[str] = None):
    """Админ гараар тоог засварлахад ашиглана (жишээ нь давхардал засах)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT chat_title FROM movie_counts WHERE chat_id=?', (chat_id,))
    row = c.fetchone()
    title_to_save = chat_title if chat_title is not None else (row['chat_title'] if row else "")
    c.execute('''
        INSERT INTO movie_counts (chat_id, chat_title, count) VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET count=excluded.count, chat_title=excluded.chat_title
    ''', (chat_id, title_to_save, count))
    conn.commit()
    conn.close()


def get_movie_counts() -> List[Dict]:
    """Бүх сувгийн кино тоог буцаана."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM movie_counts ORDER BY chat_title')
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


_TITLE_STOPWORDS = {'vip', 'кино', 'movie', 'zone', 'movizone', 'moviezone'}
_WORD_RE = re.compile(r'[a-zA-Zа-яА-ЯёЁүҮөӨ0-9]+', re.UNICODE)


def _keywords(text: str) -> List[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w and w not in _TITLE_STOPWORDS]


def find_movie_count_by_text(text: str) -> Optional[Dict]:
    """Хэрэглэгчийн бичсэн чөлөөт текст доторх суваг/категорийн нэрийг олж,
    хамгийн олон түлхүүр үг таарсан мөрийг буцаана. 'VIP', 'кино' зэрэг
    ерөнхий нэрийг тооцохгүй, ялгаатай үгсийг (жишээ: 'хүүхдийн', 'монгол') харна."""
    text_words = set(_WORD_RE.findall(text.lower()))
    best = None
    best_score = 0
    for ch in get_movie_counts():
        title_keywords = _keywords(ch['chat_title'] or '')
        if not title_keywords:
            continue
        if all(kw in text_words for kw in title_keywords):
            score = len(title_keywords)
            if score > best_score:
                best_score = score
                best = ch
    return best
