import logging
from telegram import Update, ChatMemberUpdated
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ChatMemberHandler
)
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import database as db
import config

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

# ─── ХЭРЭГЛЭГЧИЙН МЕССЕЖ ─────────────────────────────────────────
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    if not message or not user:
        return
    if is_admin(user.id):
        return

    # Бүртгэл
    is_new = db.register_user(user.id, user.username, user.first_name)
    should_greet = db.should_send_greeting(user.id, is_new)
    if should_greet:
        welcome = db.get_auto_reply()
        try:
            await message.reply_text(welcome)
            db.mark_greeted(user.id)
        except TelegramError as e:
            logger.error(f"Welcome алдаа: {e}")

    # Сүүлд бичсэн хэрэглэгчийг хадгална
    context.bot_data['last_user'] = user.id

    # Мессежийг админуудад дамжуулна — зөвхөн текст
    if message.text:
        forward_text = f"{user.first_name}: {message.text}"
    elif message.photo:
        forward_text = f"{user.first_name}: [Зураг]"
    elif message.video:
        forward_text = f"{user.first_name}: [Видео]"
    elif message.voice:
        forward_text = f"{user.first_name}: [Дуу]"
    elif message.document:
        forward_text = f"{user.first_name}: [Файл]"
    elif message.sticker:
        forward_text = f"{user.first_name}: [Стикер]"
    else:
        forward_text = f"{user.first_name}: [Медиа]"

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=forward_text)
            if message.photo:
                await context.bot.send_photo(chat_id=admin_id, photo=message.photo[-1].file_id)
            elif message.video:
                await context.bot.send_video(chat_id=admin_id, video=message.video.file_id)
            elif message.voice:
                await context.bot.send_voice(chat_id=admin_id, voice=message.voice.file_id)
            elif message.document:
                await context.bot.send_document(chat_id=admin_id, document=message.document.file_id)
            elif message.sticker:
                await context.bot.send_sticker(chat_id=admin_id, sticker=message.sticker.file_id)
        except TelegramError as e:
            logger.error(f"Admin {admin_id} алдаа: {e}")

# ─── АДМИНЫ ХАРИУ ────────────────────────────────────────────────
async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    if not message or not user:
        return
    if not is_admin(user.id):
        return
    if not message.text:
        return

    text = message.text.strip()

    # /r ID текст — тодорхой хэрэглэгчид хариулах
    if text.startswith('/r '):
        parts = text.split(' ', 2)
        if len(parts) >= 3:
            try:
                target_id = int(parts[1])
                reply_text = parts[2]
                await context.bot.send_message(chat_id=target_id, text=reply_text)
                await message.reply_text(f"✅ {target_id}-д илгээгдлээ.")
            except Exception as e:
                await message.reply_text(f"❌ Алдаа: {e}")
        else:
            await message.reply_text("📌 Хэрэглээ: /r [user_id] [текст]")
        return

    # Команд биш бол сүүлд бичсэн хэрэглэгчид хариулна
    if text.startswith('/'):
        return

    last_user = context.bot_data.get('last_user')
    if not last_user:
        await message.reply_text("❌ Хариулах хэрэглэгч байхгүй байна.")
        return

    try:
        await context.bot.send_message(chat_id=last_user, text=text)
    except TelegramError as e:
        await message.reply_text(f"❌ Алдаа: {e}")

# ─── VIP ГРУППТ ШИНЭ ГИШҮҮН ──────────────────────────────────────
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    # Зөвхөн VIP группуудыг шалгана
    if result.chat.id not in config.VIP_GROUP_IDS:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    new_member = result.new_chat_member.user

    # Шинээр нэмэгдсэн бол
    if old_status in ['left', 'kicked'] and new_status == 'member':
        username_str = f"@{new_member.username}" if new_member.username else new_member.first_name
        msg = (
            f"👤 <b>{username_str}</b> VIP группт нэмэгдлээ!\n"
            f"🆔 ID: <code>{new_member.id}</code>\n\n"
            f"Хэдэн хоногоор VIP эрх өгөх вэ?\n"
            f"<i>/addvip {new_member.id} [хоног] гэж бичнэ үү</i>"
        )
        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode='HTML')
            except TelegramError as e:
                logger.error(f"Admin {admin_id} мэдэгдэл алдаа: {e}")

# ─── VIP КОМАНДУУД ────────────────────────────────────────────────
async def add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("📌 Хэрэглээ: /addvip [user_id] [хоног]")
        return
    try:
        user_id = int(args[0])
        days = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Буруу формат.")
        return
    expiry = db.add_vip(user_id, days)
    expiry_str = expiry.strftime('%Y-%m-%d')
    await update.message.reply_text(
        f"✅ VIP нэмэгдлээ\n🆔 {user_id}\n📅 Дуусах: {expiry_str}"
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=f"🎉 Таны VIP эрх идэвхжлээ!\n📅 Дуусах огноо: {expiry_str}")
    except:
        pass

async def extend_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("📌 Хэрэглээ: /extendvip [user_id] [хоног]")
        return
    try:
        user_id = int(args[0])
        days = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Буруу формат.")
        return
    result = db.extend_vip(user_id, days)
    if result:
        expiry_str = result.strftime('%Y-%m-%d')
        await update.message.reply_text(f"✅ VIP сунгагдлаа\n📅 Шинэ дуусах: {expiry_str}")
        try:
            await context.bot.send_message(chat_id=user_id, text=f"🎉 VIP сунгагдлаа!\n📅 Шинэ дуусах огноо: {expiry_str}")
        except:
            pass
    else:
        await update.message.reply_text("❌ VIP хэрэглэгч олдсонгүй.")

async def remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("📌 Хэрэглээ: /removevip [user_id]")
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Буруу формат.")
        return
    success = db.remove_vip(user_id)
    if success:
        await update.message.reply_text(f"✅ {user_id}-ийн VIP цуцлагдлаа.")
        for gid in config.VIP_GROUP_IDS:
            try:
                await context.bot.ban_chat_member(gid, user_id)
                await context.bot.unban_chat_member(gid, user_id)
            except:
                pass
        try:
            await context.bot.send_message(chat_id=user_id, text="❌ Таны VIP эрх цуцлагдлаа.")
        except:
            pass
    else:
        await update.message.reply_text("❌ Хэрэглэгч олдсонгүй.")

async def vip_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    vips = db.get_all_vips()
    if not vips:
        await update.message.reply_text("Идэвхтэй VIP байхгүй.")
        return
    lines = ["VIP хэрэглэгчид:"]
    for v in vips:
        name = v['first_name'] or '—'
        username = f"@{v['username']}" if v['username'] else "—"
        expiry = v['vip_expiry'][:10] if v['vip_expiry'] else "—"
        lines.append(f"{name} ({username}) | {v['user_id']} | {expiry}")
    await update.message.reply_text("\n".join(lines))

async def vip_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("📌 Хэрэглээ: /vipinfo [user_id]")
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Буруу формат.")
        return
    user = db.get_user_info(user_id)
    if not user:
        await update.message.reply_text("❌ Хэрэглэгч олдсонгүй.")
        return
    vip_status = "Идэвхтэй" if user['is_vip'] else "Идэвхгүй"
    expiry = user['vip_expiry'][:10] if user['vip_expiry'] else "—"
    username_str = f"@{user['username']}" if user['username'] else "—"
    await update.message.reply_text(
        f"ID: {user['user_id']}\n"
        f"Нэр: {user['first_name'] or '—'}\n"
        f"Username: {username_str}\n"
        f"VIP: {vip_status}\n"
        f"Дуусах: {expiry}"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = db.get_stats()
    await update.message.reply_text(
        f"Нийт хэрэглэгч: {s['total_users']}\n"
        f"Идэвхтэй VIP: {s['total_vip']}\n"
        f"Дууссан VIP: {s['expired_vip']}"
    )

async def set_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(f"Одоогийн автомат хариулт:\n{current}\n\nШинэ текстийг бичнэ үү:")
    context.user_data['setting_reply'] = True

async def view_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(f"Автомат хариулт:\n{current}")

# ─── SCHEDULER ────────────────────────────────────────────────────
async def check_vip_expirations(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    for user in db.get_expiring_soon(3):
        try:
            await bot.send_message(chat_id=user['user_id'], text="Таны VIP 3 хоногийн дотор дуусна!")
        except: pass
    for user in db.get_expiring_soon(1):
        try:
            await bot.send_message(chat_id=user['user_id'], text="Таны VIP маргааш дуусна!")
        except: pass
    for user in db.get_expired_vips():
        uid = user['user_id']
        db.remove_vip(uid)
        for gid in config.VIP_GROUP_IDS:
            try:
                await bot.ban_chat_member(gid, uid)
                await bot.unban_chat_member(gid, uid)
            except: pass
        try:
            await bot.send_message(chat_id=uid, text="Таны VIP дууслаа. Группаас гарсан байна.")
        except: pass
        name = user.get('first_name') or str(uid)
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=f"{name} ({uid}) хэрэглэгчийн VIP дууссан.")
            except: pass

# ─── MAIN ─────────────────────────────────────────────────────────
def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Админы мессеж
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.User(config.ADMIN_IDS) & filters.TEXT,
        handle_admin_message
    ))

    # VIP командууд
    app.add_handler(CommandHandler('addvip', add_vip))
    app.add_handler(CommandHandler('extendvip', extend_vip))
    app.add_handler(CommandHandler('removevip', remove_vip))
    app.add_handler(CommandHandler('viplist', vip_list))
    app.add_handler(CommandHandler('vipinfo', vip_info))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('setreply', set_reply_start))
    app.add_handler(CommandHandler('viewreply', view_reply))

    # Хэрэглэгчийн мессеж
    app.add_handler(MessageHandler(
        ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_user_message
    ))

    # VIP группт шинэ гишүүн
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_vip_expirations, trigger='cron', hour=9, minute=0, kwargs={'context': app})
    scheduler.start()

    logger.info("✅ Bot ажиллаж байна...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()


