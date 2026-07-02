import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ChatMemberHandler, ChatJoinRequestHandler,
    CallbackQueryHandler
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
    context.bot_data['last_user'] = user.id
    welcome = db.get_auto_reply()
    await update.message.reply_text(welcome)

    username_str = f"@{user.username}" if user.username else "username байхгүй"
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"{user.first_name} ({username_str}) | ID: {user.id}\n[/start дарсан]"
            )
        except TelegramError:
            pass


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

    # Хариулах товч нэмнэ — ийм байдлаар ялгаж харилцана
    keyboard = [[InlineKeyboardButton(
        f"↩️ {user.first_name}-д хариулах",
        callback_data=f"reply_{user.id}"
    )]]
    markup = InlineKeyboardMarkup(keyboard)

    for admin_id in config.ADMIN_IDS:
        try:
            sent = await context.bot.send_message(
                chat_id=admin_id,
                text=forward_text,
                reply_markup=markup
            )
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


# ─── ХАРИУЛАХ ТОВЧ ───────────────────────────────────────────────
async def reply_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin = query.from_user
    if not is_admin(admin.id):
        await query.answer("⛔ Зөвхөн админ.", show_alert=True)
        return

    await query.answer()
    user_id = int(query.data.split("_")[1])
    context.user_data['reply_to'] = user_id

    user_info = db.get_user_info(user_id)
    name = user_info['first_name'] if user_info and user_info['first_name'] else str(user_id)

    await query.message.reply_text(
        f"✏️ {name}-д хариулах мессежийг бичнэ үү:"
    )


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

    # ── VIP хугацаа хариулах ──
    pending = context.bot_data.get('pending_vip')
    if pending and text.lstrip('-').isdigit() and not text.startswith('/'):
        try:
            days = int(text)
            target_user_id = pending['user_id']
            chat_id = pending['chat_id']
            chat_title = pending['chat_title']
            username = pending['username']

            expiry = db.add_vip(target_user_id, chat_id, days, chat_title=chat_title)
            expiry_str = expiry.strftime('%Y-%m-%d')

            await message.reply_text(
                f"✅ VIP нэмэгдлээ\n"
                f"👤 {username}\n"
                f"🆔 {target_user_id}\n"
                f"📺 {chat_title}\n"
                f"📅 Дуусах: {expiry_str}"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 Таны VIP эрх идэвхжлээ!\n📺 {chat_title}\n📅 Дуусах огноо: {expiry_str}"
                )
            except TelegramError:
                pass
            context.bot_data.pop('pending_vip', None)
            return
        except ValueError:
            pass

    # ── Товч дарсны дараа хариулах ──
    reply_to = context.user_data.get('reply_to')
    if reply_to and not text.startswith('/'):
        try:
            await context.bot.send_message(chat_id=reply_to, text=text)
            context.user_data.pop('reply_to', None)
        except TelegramError as e:
            await message.reply_text(f"❌ Алдаа: {e}")
        return

    # ── /r ID текст ──
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

    # ── Reply хийсэн бол тэр хэрэглэгчид ──
    if message.reply_to_message:
        replied_msg_id = message.reply_to_message.message_id
        target_id = db.get_user_from_message(replied_msg_id, user.id)
        if target_id:
            try:
                await context.bot.send_message(chat_id=target_id, text=text)
            except TelegramError as e:
                await message.reply_text(f"❌ Алдаа: {e}")
            return

    # ── Сүүлд бичсэн хэрэглэгчид ──
    last_user = context.bot_data.get('last_user')
    if not last_user:
        await message.reply_text("❌ Хариулах хэрэглэгч байхгүй.")
        return

    try:
        await context.bot.send_message(chat_id=last_user, text=text)
    except TelegramError as e:
        await message.reply_text(f"❌ Алдаа: {e}")


# ─── VIP МЭДЭГДЭЛ ДАМЖУУЛАХ ──────────────────────────────────────
async def notify_new_vip_member(context, user_id, username_str, first_name, chat_id, chat_title):
    """Шинэ VIP гишүүний талаар бүх админд мэдэгдэнэ."""
    msg = (
        f"🔔 Шинэ гишүүн нэмэгдлээ\n\n"
        f"👤 Нэр: {first_name} ({username_str})\n"
        f"🆔 ID: {user_id}\n"
        f"📺 Суваг: {chat_title}\n\n"
        f"Энэ хүн хэдэн хоногоор VIP эрхтэй вэ?\n"
        f"(Тоо бичнэ үү)"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=msg)
        except TelegramError as e:
            logger.error(f"Admin мэдэгдэл алдаа: {e}")

    context.bot_data['pending_vip'] = {
        'user_id': user_id,
        'chat_id': chat_id,
        'chat_title': chat_title,
        'username': f"{first_name} ({username_str})"
    }


# ─── GROUP-Д ШИНЭ ГИШҮҮН ─────────────────────────────────────────
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    chat_id = result.chat.id
    if chat_id not in config.VIP_GROUP_IDS:
        return

    # Зөвхөн GROUP-д л ажиллана (channel-д chat_join_request ашиглана)
    if result.chat.type not in ['group', 'supergroup']:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    new_member = result.new_chat_member.user

    if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
        username_str = f"@{new_member.username}" if new_member.username else "—"
        await notify_new_vip_member(
            context, new_member.id, username_str, new_member.first_name,
            chat_id, result.chat.title or str(chat_id)
        )


# ─── CHANNEL-Д JOIN REQUEST ───────────────────────────────────────
async def handle_join_request_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    if not request:
        return

    chat_id = request.chat.id
    if chat_id not in config.VIP_GROUP_IDS:
        return

    user = request.from_user

    try:
        await context.bot.approve_chat_join_request(chat_id, user.id)
    except TelegramError as e:
        logger.error(f"Join request зөвшөөрөхөд алдаа: {e}")
        return

    username_str = f"@{user.username}" if user.username else "—"
    await notify_new_vip_member(
        context, user.id, username_str, user.first_name,
        chat_id, request.chat.title or str(chat_id)
    )


# ─── VIP КОМАНДУУД ────────────────────────────────────────────────
async def add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📌 Хэрэглээ: /addvip [user_id] [хоног] [chat_id]")
        return
    try:
        user_id = int(args[0])
        days = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Буруу формат.")
        return

    if len(args) >= 3:
        try:
            chat_id = int(args[2])
        except ValueError:
            await update.message.reply_text("❌ chat_id буруу.")
            return
        chat_title = str(chat_id)
    else:
        if not config.VIP_GROUP_IDS:
            await update.message.reply_text("❌ VIP_GROUP_IDS тохируулаагүй.")
            return
        chat_id = config.VIP_GROUP_IDS[0]
        chat_title = str(chat_id)

    expiry = db.add_vip(user_id, chat_id, days, chat_title=chat_title)
    expiry_str = expiry.strftime('%Y-%m-%d')
    user_info = db.get_user_info(user_id)
    name = user_info['first_name'] if user_info and user_info['first_name'] else str(user_id)
    username = f"@{user_info['username']}" if user_info and user_info['username'] else "—"

    await update.message.reply_text(
        f"✅ VIP нэмэгдлээ\n👤 {name} ({username})\n🆔 {user_id}\n📺 {chat_title}\n📅 Дуусах: {expiry_str}"
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 Таны VIP эрх идэвхжлээ!\n📅 Дуусах огноо: {expiry_str}"
        )
    except TelegramError:
        pass


async def extend_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📌 Хэрэглээ: /extendvip [user_id] [хоног] [chat_id]")
        return
    try:
        user_id = int(args[0])
        days = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Буруу формат.")
        return

    if len(args) >= 3:
        try:
            chat_id = int(args[2])
        except ValueError:
            await update.message.reply_text("❌ chat_id буруу.")
            return
    else:
        memberships = db.get_vip_memberships(user_id)
        if not memberships:
            await update.message.reply_text("❌ Энэ хэрэглэгч VIP биш байна.")
            return
        if len(memberships) > 1:
            lines = ["⚠️ Хэд хэдэн VIP байна. chat_id зааж өгнө үү:"]
            for m in memberships:
                lines.append(f"  {m['chat_id']} — {m['chat_title']}")
            await update.message.reply_text("\n".join(lines))
            return
        chat_id = memberships[0]['chat_id']

    result = db.extend_vip(user_id, chat_id, days)
    if result:
        expiry_str = result.strftime('%Y-%m-%d')
        await update.message.reply_text(f"✅ VIP сунгагдлаа\n📅 Шинэ дуусах: {expiry_str}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 VIP сунгагдлаа!\n📅 Шинэ дуусах огноо: {expiry_str}"
            )
        except TelegramError:
            pass
    else:
        await update.message.reply_text("❌ VIP бичлэг олдсонгүй.")


async def remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text(
            "📌 Хэрэглээ:\n/removevip [user_id] — бүх VIP-аас хасна\n/removevip [user_id] [chat_id] — нэг сувгаас хасна"
        )
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Буруу формат.")
        return

    if len(args) >= 2:
        try:
            chat_id = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ chat_id буруу.")
            return
        success = db.remove_vip(user_id, chat_id)
        if success:
            await update.message.reply_text(f"✅ {user_id}-ийг {chat_id}-аас хаслаа.")
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
            except TelegramError:
                pass
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ Таны VIP нэг сувгаас цуцлагдлаа.")
            except TelegramError:
                pass
        else:
            await update.message.reply_text("❌ VIP бичлэг олдсонгүй.")
    else:
        chat_ids = db.remove_vip_all(user_id)
        if chat_ids:
            await update.message.reply_text(f"✅ {user_id}-ийг {len(chat_ids)} сувгаас бүгдээс хаслаа.")
            for gid in chat_ids:
                try:
                    await context.bot.ban_chat_member(gid, user_id)
                    await context.bot.unban_chat_member(gid, user_id)
                except TelegramError:
                    pass
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ Таны VIP бүх сувгаас цуцлагдлаа.")
            except TelegramError:
                pass
        else:
            await update.message.reply_text("❌ Хэрэглэгч VIP биш байна.")


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
        lines.append(f"{name} ({username}) | {v['user_id']} | {v['chat_title']} | {expiry}")
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
    username_str = f"@{user['username']}" if user['username'] else "—"
    memberships = db.get_vip_memberships(user_id)
    lines = [f"ID: {user['user_id']}", f"Нэр: {user['first_name'] or '—'}", f"Username: {username_str}", ""]
    if memberships:
        lines.append("VIP сувгууд:")
        for m in memberships:
            expiry = m['vip_expiry'][:10] if m['vip_expiry'] else "—"
            lines.append(f"  📺 {m['chat_title']} — дуусах: {expiry}")
    else:
        lines.append("VIP биш байна.")
    await update.message.reply_text("\n".join(lines))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = db.get_stats()
    await update.message.reply_text(
        f"Нийт хэрэглэгч: {s['total_users']}\n"
        f"Нийт VIP бичлэг: {s['total_vip']}\n"
        f"VIP хэрэглэгч: {s['total_vip_users']}"
    )


async def set_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        current = db.get_auto_reply()
        await update.message.reply_text(f"Одоогийн автомат хариулт:\n{current}\n\nӨөрчлөхдөө:\n/setreply [текст]")
        return
    new_text = ' '.join(context.args)
    db.set_auto_reply(new_text)
    await update.message.reply_text(f"✅ Шинэчлэгдлээ:\n{new_text}")


async def view_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(f"Автомат хариулт:\n{current}")


# ─── SCHEDULER ────────────────────────────────────────────────────
async def check_vip_expirations(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot

    for m in db.get_expiring_soon(3):
        try:
            await bot.send_message(
                chat_id=m['user_id'],
                text=f"⚠️ Таны VIP ({m['chat_title']}) 3 хоногийн дотор дуусна!\nСунгуулахыг хүсвэл бидэнтэй холбогдоно уу."
            )
        except TelegramError:
            pass

    for m in db.get_expiring_soon(2):
        try:
            await bot.send_message(
                chat_id=m['user_id'],
                text=f"⚠️ Таны VIP ({m['chat_title']}) 2 хоногийн дотор дуусна!\nСунгуулахыг хүсвэл яараарай."
            )
        except TelegramError:
            pass

    for m in db.get_expired_vips():
        uid = m['user_id']
        chat_id = m['chat_id']
        chat_title = m['chat_title']
        name = m.get('first_name') or str(uid)
        username = f"@{m['username']}" if m.get('username') else "—"

        db.remove_vip(uid, chat_id)

        try:
            await bot.ban_chat_member(chat_id, uid)
            await bot.unban_chat_member(chat_id, uid)
        except TelegramError:
            pass

        try:
            await bot.send_message(
                chat_id=uid,
                text=f"❌ Таны VIP ({chat_title}) хугацаа дууслаа.\nСунгуулахыг хүсвэл бидэнтэй холбогдоно уу."
            )
        except TelegramError:
            pass

        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"🔔 VIP дууссан\n👤 {name} ({username})\n🆔 {uid}\n📺 {chat_title}"
                )
            except TelegramError:
                pass


# ─── MAIN ─────────────────────────────────────────────────────────
def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(reply_button_callback, pattern=r'^reply_\d+$'))

    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.User(config.ADMIN_IDS) & filters.TEXT,
        handle_admin_message
    ), group=1)

    app.add_handler(CommandHandler('addvip', add_vip))
    app.add_handler(CommandHandler('extendvip', extend_vip))
    app.add_handler(CommandHandler('removevip', remove_vip))
    app.add_handler(CommandHandler('viplist', vip_list))
    app.add_handler(CommandHandler('vipinfo', vip_info))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('setreply', set_reply))
    app.add_handler(CommandHandler('viewreply', view_reply))

    app.add_handler(MessageHandler(
        ~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_message
    ), group=1)

    # Group-д ChatMemberHandler, Channel-д ChatJoinRequestHandler
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatJoinRequestHandler(handle_join_request_approved))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_vip_expirations, trigger='cron', hour=9, minute=0, kwargs={'context': app})
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
