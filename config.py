import os

# ─────────────────────────────────────────────
# Заавал тохируулах тохиргоо
# ─────────────────────────────────────────────

# Ботын токен (@BotFather-аас авна)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Хоёр админы Telegram ID (тоо)
ADMIN_IDS: list[int] = [
    int(os.getenv("ADMIN_ID_1", "111111111")),   # ← 1-р админы ID
    int(os.getenv("ADMIN_ID_2", "222222222")),   # ← 2-р админы ID
]

# VIP группийн ID (Group/Supergroup ID, жишээ: -1001234567890)
# Группийн ID олохын тулд: @userinfobot-д группийг нэмэх эсвэл
# @RawDataBot ашиглах
VIP_GROUP_ID: int = int(os.getenv("VIP_GROUP_ID", "0"))  # ← Группийн ID
