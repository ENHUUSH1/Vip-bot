import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
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

WAITING_FOR_REPLY_TEXT = 1

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    if not message or not user:
        return
    if is_admin(user.id):
        return

    # Хэрэглэгчийг бүртгэж, анхны мессеж эсэхийг шалгана
    # register_user нь True буцаавал шинэ хэрэглэгч
    # False буцаавал байгаа хэрэглэгч
    is_new = db.register_user(user.id, user.username, user.first_name)
    
    # Шинэ хэрэглэгч эсвэл дахин эхлүүлсэн бол автомат хариу өгнө
    should_greet = db.should_send_greeting(user.id, is_new)
    
    if should_greet:
        welcome = db.get_auto_reply()
        try:
            await message.reply_text(welcome)
            db.mark_greeted(user.id)
        except TelegramError as e:
            logger.error(f"Welcome алдаа: {e}")

    if message.text:
        content = message.text
        content_type = "💬"
    elif message.photo:
        content = "[Зураг]"
        content_type = "🖼"
    elif message.video:
        content = "[Видео]"
        content_type = "🎬"
    elif message.voice:
        content = "[Дуу]"
        content_type = "🎙"
    elif message.document:
        content = f"[Файл: {message.document.file_name or 'файл'}]"
        content_type = "📎"
    elif message.sticker:
        content = "[Стикер]"
        content_type = "🎭"
    else:
        content = "[Медиа]"
        content_type = "📩"

    name = user.first_name or "Нэргүй"
    username_str = f" @{user.username}" if user.username else ""

    forward_text = (
        f"📨 <b>Шинэ мессеж</b>\n"
        f"👤 <b>Хэрэглэгч:</b> {name}{username_str}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{content_type} {content}"
    )

    keyboard = [[InlineKeyboardButton("↩️ Хариулах", callback_data=f"reply_{user.id}")]]
    markup = InlineKeyboardMarkup(keyboard)

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=forward_text, parse_mode='HTML', reply_markup=markup)
            if message.photo:
                await context.bot.send_photo(chat_id=admin_id, photo=message.photo[-1].file_id)
            elif message.video:
                await context.bot.send_video(chat_id=admin_id, video=message.video.file_id)
            elif message.voice:
                await context.bot.send_voice(chat_id=admin_id, voice=message.voice.file_id)
            elif message.document:
                await context.bot.send_document(chat_id=admin_id, document=message.document.file_id)
        except TelegramError as e:
            logger.error(f"Admin {admin_id} алдаа: {e}")

async def reply_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin = query.from_user
    if not is_admin(admin.id):
        await query.answer("⛔ Зөвхөн админ.", show_alert=True)
        return
    await query.answer()
    user_id = int(query.data.split("_")[1])
    context.user_data['reply_to_user'] = user_id
    await query.message.reply_text(
        f"✏️ Хэрэглэгч <code>{user_id}</code>-д хариулах мессежийг бичнэ үү:\n<i>(/cancel цуцлах)</i>",
        parse_mode='HTML'
    )
    return WAITING_FOR_REPLY_TEXT

async def send_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    target_id = context.user_data.get('reply_to_user')
    if not target_id:
        await update.message.reply_text("❌ Хариулах хэрэглэгч олдсонгүй.")
        return ConversationHandler.END
    try:
        await context.bot.send_message(chat_id=target_id, text=f"💬 {update.message.text}")
        await update.message.reply_text(f"✅ Илгээгдлээ → <code>{target_id}</code>", parse_mode='HTML')
    except TelegramError as e:
        await update.message.reply_text(f"❌ Алдаа: {e}")
    context.user_data.pop('reply_to_user', None)
    return ConversationHandler.END

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
        f"✅ <b>VIP нэмэгдлээ</b>\n🆔 <code>{user_id}</code>\n📅 Дуусах: <b>{expiry_str}</b>",
        parse_mode='HTML'
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
        await update.message.reply_text(
            f"✅ <b>VIP сунгагдлаа</b>\n🆔 <code>{user_id}</code>\n📅 Шинэ дуусах: <b>{expiry_str}</b>",
            parse_mode='HTML'
        )
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
        await update.message.reply_text(f"✅ <code>{user_id}</code>-ийн VIP цуцлагдлаа.", parse_mode='HTML')
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
        await update.message.reply_text("📋 Идэвхтэй VIP байхгүй.")
        return
    lines = ["🌟 <b>Идэвхтэй VIP хэрэглэгчид</b>\n━━━━━━━━━━━━━━━"]
    for v in vips:
        name = v['first_name'] or '—'
        username = f"@{v['username']}" if v['username'] else "—"
        expiry = v['vip_expiry'][:10] if v['vip_expiry'] else "—"
        lines.append(f"👤 {name} ({username})\n🆔 <code>{v['user_id']}</code> | 📅 {expiry}")
    await update.message.reply_text("\n\n".join(lines), parse_mode='HTML')

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
    vip_status = "✅ Идэвхтэй" if user['is_vip'] else "❌ Идэвхгүй"
    expiry = user['vip_expiry'][:10] if user['vip_expiry'] else "—"
    registered = user['registered_at'][:10] if user['registered_at'] else "—"
    username_str = f"@{user['username']}" if user['username'] else "—"
    await update.message.reply_text(
        f"👤 <b>Хэрэглэгчийн мэдээлэл</b>\n━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"📛 Нэр: {user['first_name'] or '—'}\n"
        f"🔖 Username: {username_str}\n"
        f"📅 Бүртгүүлсэн: {registered}\n"
        f"⭐ VIP: {vip_status}\n"
        f"📅 Дуусах: {expiry}",
        parse_mode='HTML'
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = db.get_stats()
    await update.message.reply_text(
        f"📊 <b>Статистик</b>\n━━━━━━━━━━━━━━━\n"
        f"👥 Нийт хэрэглэгч: <b>{s['total_users']}</b>\n"
        f"⭐ Идэвхтэй VIP: <b>{s['total_vip']}</b>\n"
        f"❌ Дууссан VIP: <b>{s['expired_vip']}</b>",
        parse_mode='HTML'
    )

async def set_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(
        f"✏️ <b>Автомат хариулт өөрчлөх</b>\n\nОдоогийн текст:\n<blockquote>{current}</blockquote>\n\nШинэ текстийг бичнэ үү:",
        parse_mode='HTML'
    )
    return WAITING_FOR_REPLY_TEXT

async def save_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    new_text = update.message.text
    db.set_auto_reply(new_text)
    # Бүх хэрэглэгчдийн greeting reset хийнэ
    db.reset_all_greetings()
    await update.message.reply_text(
        f"✅ <b>Шинэчлэгдлээ!</b>\n\n<blockquote>{new_text}</blockquote>",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def view_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(
        f"📋 <b>Одоогийн автомат хариулт:</b>\n\n<blockquote>{current}</blockquote>",
        parse_mode='HTML'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('reply_to_user', None)
    await update.message.reply_text("❌ Цуцлагдлаа.")
    return ConversationHandler.END

async def check_vip_expirations(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    for user in db.get_expiring_soon(3):
        try:
            await bot.send_message(chat_id=user['user_id'], text="⚠️ Таны VIP <b>3 хоногийн дотор</b> дуусна!", parse_mode='HTML')
        except: pass
    for user in db.get_expiring_soon(1):
        try:
            await bot.send_message(chat_id=user['user_id'], text="⚠️ Таны VIP <b>маргааш дуусна!</b>", parse_mode='HTML')
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
            await bot.send_message(chat_id=uid, text="❌ Таны VIP дууслаа. Группаас гарсан байна.")
        except: pass
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=f"🔔 <code>{uid}</code> хэрэглэгчийн VIP дууссан.", parse_mode='HTML')
            except: pass

def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    set_reply_conv = ConversationHandler(
        entry_points=[CommandHandler('setreply', set_reply_start)],
        states={WAITING_FOR_REPLY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reply_text)]},
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(reply_button_callback, pattern=r'^reply_\d+$')],
        states={WAITING_FOR_REPLY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_reply_to_user)]},
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(set_reply_conv)
    app.add_handler(reply_conv)
    app.add_handler(CommandHandler('addvip', add_vip))
    app.add_handler(CommandHandler('extendvip', extend_vip))
    app.add_handler(CommandHandler('removevip', remove_vip))
    app.add_handler(CommandHandler('viplist', vip_list))
    app.add_handler(CommandHandler('vipinfo', vip_info))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('viewreply', view_reply))
    app.add_handler(MessageHandler(~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_message))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_vip_expirations, trigger='cron', hour=9, minute=0, kwargs={'context': app})
    scheduler.start()

    logger.info("✅ VIP Cinema Bot ажиллаж байна...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
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

WAITING_FOR_REPLY_TEXT = 1

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    if not message or not user:
        return
    if is_admin(user.id):
        return

    # Хэрэглэгчийг бүртгэж, анхны мессеж эсэхийг шалгана
    # register_user нь True буцаавал шинэ хэрэглэгч
    # False буцаавал байгаа хэрэглэгч
    is_new = db.register_user(user.id, user.username, user.first_name)
    
    # Шинэ хэрэглэгч эсвэл дахин эхлүүлсэн бол автомат хариу өгнө
    should_greet = db.should_send_greeting(user.id, is_new)
    
    if should_greet:
        welcome = db.get_auto_reply()
        try:
            await message.reply_text(welcome)
            db.mark_greeted(user.id)
        except TelegramError as e:
            logger.error(f"Welcome алдаа: {e}")

    if message.text:
        content = message.text
        content_type = "💬"
    elif message.photo:
        content = "[Зураг]"
        content_type = "🖼"
    elif message.video:
        content = "[Видео]"
        content_type = "🎬"
    elif message.voice:
        content = "[Дуу]"
        content_type = "🎙"
    elif message.document:
        content = f"[Файл: {message.document.file_name or 'файл'}]"
        content_type = "📎"
    elif message.sticker:
        content = "[Стикер]"
        content_type = "🎭"
    else:
        content = "[Медиа]"
        content_type = "📩"

    name = user.first_name or "Нэргүй"
    username_str = f" @{user.username}" if user.username else ""

    forward_text = (
        f"📨 <b>Шинэ мессеж</b>\n"
        f"👤 <b>Хэрэглэгч:</b> {name}{username_str}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{content_type} {content}"
    )

    keyboard = [[InlineKeyboardButton("↩️ Хариулах", callback_data=f"reply_{user.id}")]]
    markup = InlineKeyboardMarkup(keyboard)

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=forward_text, parse_mode='HTML', reply_markup=markup)
            if message.photo:
                await context.bot.send_photo(chat_id=admin_id, photo=message.photo[-1].file_id)
            elif message.video:
                await context.bot.send_video(chat_id=admin_id, video=message.video.file_id)
            elif message.voice:
                await context.bot.send_voice(chat_id=admin_id, voice=message.voice.file_id)
            elif message.document:
                await context.bot.send_document(chat_id=admin_id, document=message.document.file_id)
        except TelegramError as e:
            logger.error(f"Admin {admin_id} алдаа: {e}")

async def reply_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin = query.from_user
    if not is_admin(admin.id):
        await query.answer("⛔ Зөвхөн админ.", show_alert=True)
        return
    await query.answer()
    user_id = int(query.data.split("_")[1])
    context.user_data['reply_to_user'] = user_id
    await query.message.reply_text(
        f"✏️ Хэрэглэгч <code>{user_id}</code>-д хариулах мессежийг бичнэ үү:\n<i>(/cancel цуцлах)</i>",
        parse_mode='HTML'
    )
    return WAITING_FOR_REPLY_TEXT

async def send_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    target_id = context.user_data.get('reply_to_user')
    if not target_id:
        await update.message.reply_text("❌ Хариулах хэрэглэгч олдсонгүй.")
        return ConversationHandler.END
    try:
        await context.bot.send_message(chat_id=target_id, text=f"💬 {update.message.text}")
        await update.message.reply_text(f"✅ Илгээгдлээ → <code>{target_id}</code>", parse_mode='HTML')
    except TelegramError as e:
        await update.message.reply_text(f"❌ Алдаа: {e}")
    context.user_data.pop('reply_to_user', None)
    return ConversationHandler.END

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
        f"✅ <b>VIP нэмэгдлээ</b>\n🆔 <code>{user_id}</code>\n📅 Дуусах: <b>{expiry_str}</b>",
        parse_mode='HTML'
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
        await update.message.reply_text(
            f"✅ <b>VIP сунгагдлаа</b>\n🆔 <code>{user_id}</code>\n📅 Шинэ дуусах: <b>{expiry_str}</b>",
            parse_mode='HTML'
        )
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
        await update.message.reply_text(f"✅ <code>{user_id}</code>-ийн VIP цуцлагдлаа.", parse_mode='HTML')
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
        await update.message.reply_text("📋 Идэвхтэй VIP байхгүй.")
        return
    lines = ["🌟 <b>Идэвхтэй VIP хэрэглэгчид</b>\n━━━━━━━━━━━━━━━"]
    for v in vips:
        name = v['first_name'] or '—'
        username = f"@{v['username']}" if v['username'] else "—"
        expiry = v['vip_expiry'][:10] if v['vip_expiry'] else "—"
        lines.append(f"👤 {name} ({username})\n🆔 <code>{v['user_id']}</code> | 📅 {expiry}")
    await update.message.reply_text("\n\n".join(lines), parse_mode='HTML')

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
    vip_status = "✅ Идэвхтэй" if user['is_vip'] else "❌ Идэвхгүй"
    expiry = user['vip_expiry'][:10] if user['vip_expiry'] else "—"
    registered = user['registered_at'][:10] if user['registered_at'] else "—"
    username_str = f"@{user['username']}" if user['username'] else "—"
    await update.message.reply_text(
        f"👤 <b>Хэрэглэгчийн мэдээлэл</b>\n━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"📛 Нэр: {user['first_name'] or '—'}\n"
        f"🔖 Username: {username_str}\n"
        f"📅 Бүртгүүлсэн: {registered}\n"
        f"⭐ VIP: {vip_status}\n"
        f"📅 Дуусах: {expiry}",
        parse_mode='HTML'
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = db.get_stats()
    await update.message.reply_text(
        f"📊 <b>Статистик</b>\n━━━━━━━━━━━━━━━\n"
        f"👥 Нийт хэрэглэгч: <b>{s['total_users']}</b>\n"
        f"⭐ Идэвхтэй VIP: <b>{s['total_vip']}</b>\n"
        f"❌ Дууссан VIP: <b>{s['expired_vip']}</b>",
        parse_mode='HTML'
    )

async def set_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(
        f"✏️ <b>Автомат хариулт өөрчлөх</b>\n\nОдоогийн текст:\n<blockquote>{current}</blockquote>\n\nШинэ текстийг бичнэ үү:",
        parse_mode='HTML'
    )
    return WAITING_FOR_REPLY_TEXT

async def save_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    new_text = update.message.text
    db.set_auto_reply(new_text)
    # Бүх хэрэглэгчдийн greeting reset хийнэ
    db.reset_all_greetings()
    await update.message.reply_text(
        f"✅ <b>Шинэчлэгдлээ!</b>\n\n<blockquote>{new_text}</blockquote>",
        parse_mode='HTML'
    )
    return ConversationHandler.END

async def view_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(
        f"📋 <b>Одоогийн автомат хариулт:</b>\n\n<blockquote>{current}</blockquote>",
        parse_mode='HTML'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('reply_to_user', None)
    await update.message.reply_text("❌ Цуцлагдлаа.")
    return ConversationHandler.END

async def check_vip_expirations(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    for user in db.get_expiring_soon(3):
        try:
            await bot.send_message(chat_id=user['user_id'], text="⚠️ Таны VIP <b>3 хоногийн дотор</b> дуусна!", parse_mode='HTML')
        except: pass
    for user in db.get_expiring_soon(1):
        try:
            await bot.send_message(chat_id=user['user_id'], text="⚠️ Таны VIP <b>маргааш дуусна!</b>", parse_mode='HTML')
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
            await bot.send_message(chat_id=uid, text="❌ Таны VIP дууслаа. Группаас гарсан байна.")
        except: pass
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=f"🔔 <code>{uid}</code> хэрэглэгчийн VIP дууссан.", parse_mode='HTML')
            except: pass

def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    set_reply_conv = ConversationHandler(
        entry_points=[CommandHandler('setreply', set_reply_start)],
        states={WAITING_FOR_REPLY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_reply_text)]},
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(reply_button_callback, pattern=r'^reply_\d+$')],
        states={WAITING_FOR_REPLY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_reply_to_user)]},
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(set_reply_conv)
    app.add_handler(reply_conv)
    app.add_handler(CommandHandler('addvip', add_vip))
    app.add_handler(CommandHandler('extendvip', extend_vip))
    app.add_handler(CommandHandler('removevip', remove_vip))
    app.add_handler(CommandHandler('viplist', vip_list))
    app.add_handler(CommandHandler('vipinfo', vip_info))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('viewreply', view_reply))
    app.add_handler(MessageHandler(~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_message))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_vip_expirations, trigger='cron', hour=9, minute=0, kwargs={'context': app})
    scheduler.start()

    logger.info("✅ VIP Cinema Bot ажиллаж байна...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

