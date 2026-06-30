                        import logging
from datetime import datetime, timedelta
from telegram import Update
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

# ─── START ────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(user.id):
        return
    db.register_user(user.id, user.username, user.first_name)
    context.user_data['last_message_time'] = datetime.now()
    welcome = db.get_auto_reply()
    await update.message.reply_text(welcome)

# ─── ХЭРЭГЛЭГЧИЙН МЕССЕЖ ─────────────────────────────────────────
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    if not message or not user:
        return
    if is_admin(user.id):
        return

    now = datetime.now()
    last_time = context.user_data.get('last_message_time')
    should_greet = last_time is None or (now - last_time).total_seconds() > 1800
    context.user_data['last_message_time'] = now

    db.register_user(user.id, user.username, user.first_name)

    if should_greet:
        welcome = db.get_auto_reply()
        try:
            await message.reply_text(welcome)
        except TelegramError as e:
            logger.error(f"Welcome алдаа: {e}")

    context.bot_data['last_user'] = user.id

    username_str = f"@{user.username}" if user.username else "username байхгүй"
    header = f"{user.first_name} ({username_str}) | ID: {user.id}"

    if message.text:
        forward_text = f"{header}\n{message.text}"
    elif message.photo:
        forward_text = f"{header}\n[Зураг]"
    elif message.video:
        forward_text = f"{header}\n[Видео]"
    elif message.voice:
        forward_text = f"{header}\n[Дуу]"
    elif message.document:
        forward_text = f"{header}\n[Файл]"
    elif message.sticker:
        forward_text = f"{header}\n[Стикер]"
    else:
        forward_text = f"{header}\n[Медиа]"

    for admin_id in config.ADMIN_IDS:
        try:
            sent = await context.bot.send_message(chat_id=admin_id, text=forward_text)
            # Reply хийхэд хэрэглэгчийн ID мэдэхийн тулд message_id хадгална
            db.save_message_map(sent.message_id, user.id, admin_id)
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

    # VIP хугацаа асуулт хариулах
    pending = context.user_data.get('pending_vip')
    if pending and not text.startswith('/'):
        try:
            days = int(text)
            user_id = pending['user_id']
            chat_id = pending['chat_id']
            username = pending['username']
            expiry = db.add_vip(user_id, days)
            expiry_str = expiry.strftime('%Y-%m-%d')
            await message.reply_text(
                f"✅ VIP нэмэгдлээ\n"
                f"👤 {username}\n"
                f"🆔 {user_id}\n"
                f"📅 Дуусах: {expiry_str}"
            )
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 Таны VIP эрх идэвхжлээ!\n📅 Дуусах огноо: {expiry_str}"
                )
            except:
                pass
            context.user_data.pop('pending_vip', None)
            return
        except ValueError:
            await message.reply_text("❌ Тоо оруулна уу. Жишээ: 30")
            return

    # /r ID текст
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

    if text.startswith('/'):
        return

    # Reply хийсэн бол тэр хэрэглэгчид хариулна
    if message.reply_to_message:
        replied_msg_id = message.reply_to_message.message_id
        target_id = db.get_user_from_message(replied_msg_id, user.id)
        if target_id:
            try:
                await context.bot.send_message(chat_id=target_id, text=text)
            except TelegramError as e:
                await message.reply_text(f"❌ Алдаа: {e}")
            return

    # Сүүлд бичсэн хэрэглэгчид хариулна
    last_user = context.bot_data.get('last_user')
    if not last_user:
        await message.reply_text("❌ Хариулах хэрэглэгч байхгүй.")
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

    chat_id = result.chat.id
    if chat_id not in config.VIP_GROUP_IDS:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    new_member = result.new_chat_member.user

    if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
        username_str = f"@{new_member.username}" if new_member.username else "—"
        chat_title = result.chat.title or str(chat_id)

        msg = (
            f"🔔 Шинэ гишүүн нэмэгдлээ\n\n"
            f"👤 Нэр: {new_member.first_name} ({username_str})\n"
            f"🆔 ID: {new_member.id}\n"
            f"📺 Суваг: {chat_title}\n\n"
            f"Энэ хүн хэдэн хоногоор VIP эрхтэй вэ?\n"
            f"(Тоо бичнэ үү)"
        )

        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=msg)
                # Хүлээгдэж буй VIP хадгална
                context.dispatcher.user_data[admin_id] = context.dispatcher.user_data.get(admin_id, {})
            except TelegramError as e:
                logger.error(f"Admin мэдэгдэл алдаа: {e}")

        # bot_data-д хадгална
        context.bot_data['pending_vip'] = {
            'user_id': new_member.id,
            'chat_id': chat_id,
            'username': username_str
        }

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
    user_info = db.get_user_info(user_id)
    name = user_info['first_name'] if user_info and user_info['first_name'] else str(user_id)
    username = f"@{user_info['username']}" if user_info and user_info['username'] else "—"

    await update.message.reply_text(
        f"✅ VIP нэмэгдлээ\n👤 {name} ({username})\n🆔 {user_id}\n📅 Дуусах: {expiry_str}"
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 Таны VIP эрх идэвхжлээ!\n📅 Дуусах огноо: {expiry_str}"
        )
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
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 VIP сунгагдлаа!\n📅 Шинэ дуусах огноо: {expiry_str}"
            )
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
        f"ID: {user['user_id']}\nНэр: {user['first_name'] or '—'}\n"
        f"Username: {username_str}\nVIP: {vip_status}\nДуусах: {expiry}"
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

async def set_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        current = db.get_auto_reply()
        await update.message.reply_text(
            f"Одоогийн автомат хариулт:\n{current}\n\nӨөрчлөхдөө:\n/setreply [шинэ текст]"
        )
        return
    new_text = ' '.join(context.args)
    db.set_auto_reply(new_text)
    await update.message.reply_text(f"✅ Автомат хариулт шинэчлэгдлээ:\n{new_text}")

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
            await bot.send_message(
                chat_id=user['user_id'],
                text="⚠️ Таны VIP эрх 3 хоногийн дотор дуусна!\nСунгуулахыг хүсвэл бидэнтэй холбогдоно уу."
            )
        except: pass

    for user in db.get_expiring_soon(2):
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text="⚠️ Таны VIP эрх 2 хоногийн дотор дуусна!\nСунгуулахыг хүсвэл яараарай."
            )
        except: pass

    for user in db.get_expired_vips():
        uid = user['user_id']
        name = user.get('first_name') or str(uid)
        username = f"@{user['username']}" if user.get('username') else "—"

        db.remove_vip(uid)

        for gid in config.VIP_GROUP_IDS:
            try:
                await bot.ban_chat_member(gid, uid)
                await bot.unban_chat_member(gid, uid)
            except: pass

        try:
            await bot.send_message(
                chat_id=uid,
                text="❌ Таны VIP эрхийн хугацаа дууслаа.\nСунгуулахыг хүсвэл бидэнтэй холбогдоно уу."
            )
        except: pass

        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"🔔 VIP дууссан\n👤 {name} ({username})\n🆔 {uid}\nБүх VIP-аас хасагдлаа."
                )
            except: pass

# ─── MAIN ─────────────────────────────────────────────────────────
def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Start
    app.add_handler(CommandHandler('start', start))

    # Админы мессеж
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.User(config.ADMIN_IDS) & filters.TEXT & ~filters.COMMAND,
        handle_admin_message
    ))

    # Командууд
    app.add_handler(CommandHandler('addvip', add_vip))
    app.add_handler(CommandHandler('extendvip', extend_vip))
    app.add_handler(CommandHandler('removevip', remove_vip))
    app.add_handler(CommandHandler('viplist', vip_list))
    app.add_handler(CommandHandler('vipinfo', vip_info))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('setreply', set_reply))
    app.add_handler(CommandHandler('viewreply', view_reply))

    # Хэрэглэгчийн мессеж
    app.add_handler(MessageHandler(
        ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_user_message
    ))

    # VIP группт шинэ гишүүн (group болон channel)
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_vip_expirations,
        trigger='cron',
        hour=9,
        minute=0,
        kwargs={'context': app}
    )
    scheduler.start()

    logger.info("✅ Bot ажиллаж байна...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=[
            "message", "edited_message", "channel_post", "edited_channel_post",
            "callback_query", "chat_member", "my_chat_member", "chat_join_request"
        ]
    )

if __name__ == '__main__':
    main()
