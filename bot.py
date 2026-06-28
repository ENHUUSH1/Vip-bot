import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import config
import database as db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ConversationHandler state
WAITING_REPLY_TEXT = 1

# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def forward_to_admins(context: ContextTypes.DEFAULT_TYPE, message, user):
    """Хэрэглэгчийн мессежийг хоёр админд дамжуулна."""
    text = (
        f"📨 <b>Хэрэглэгчийн мессеж</b>\n"
        f"👤 Нэр: {user.first_name or '-'}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📌 Username: @{user.username or 'байхгүй'}\n\n"
        f"💬 Мессеж:\n{message.text or '[медиа/файл]'}"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="HTML"
            )
            # Медиа байвал дамжуулна
            if message.photo:
                await context.bot.send_photo(chat_id=admin_id, photo=message.photo[-1].file_id,
                                             caption=f"[Фото | ID: {user.id}]")
            elif message.video:
                await context.bot.send_video(chat_id=admin_id, video=message.video.file_id,
                                             caption=f"[Видео | ID: {user.id}]")
            elif message.document:
                await context.bot.send_document(chat_id=admin_id, document=message.document.file_id,
                                                caption=f"[Файл | ID: {user.id}]")
            elif message.voice:
                await context.bot.send_voice(chat_id=admin_id, voice=message.voice.file_id,
                                             caption=f"[Дуу | ID: {user.id}]")
            elif message.sticker:
                await context.bot.send_sticker(chat_id=admin_id, sticker=message.sticker.file_id)
        except Exception as e:
            logger.error(f"Admin {admin_id}-д мессеж илгээхэд алдаа: {e}")


# ─────────────────────────────────────────────
# Хэрэглэгчийн мессеж боловсруулах
# ─────────────────────────────────────────────

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if not user or not message:
        return

    # Админ бол энэ handler ажиллахгүй
    if is_admin(user.id):
        return

    # DB-д бүртгэх
    is_new = db.register_user(user.id, user.username, user.first_name)

    # Анхны мессеж бол автомат хариулт илгээнэ
    if is_new:
        reply_text = db.get_auto_reply()
        try:
            await message.reply_text(reply_text)
        except Exception as e:
            logger.error(f"Автомат хариулт илгээхэд алдаа: {e}")

    # Бүх мессежийг админуудад дамжуулна
    await forward_to_admins(context, message, user)


# ─────────────────────────────────────────────
# Админ → Хэрэглэгч хариулах
# ─────────────────────────────────────────────

async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ /reply user_id текст ашиглан хэрэглэгчид хариулна."""
    user = update.effective_user
    if not is_admin(user.id):
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Хэрэглэх заавар:\n/reply <user_id> <хариулах текст>"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id буруу байна.")
        return

    reply_text = " ".join(context.args[1:])

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"💬 {reply_text}"
        )
        await update.message.reply_text(f"✅ Хэрэглэгч {target_id}-д хариулт илгээлээ.")
    except Exception as e:
        await update.message.reply_text(f"❌ Алдаа гарлаа: {e}")


# ─────────────────────────────────────────────
# Автомат хариулт тохиргоо
# ─────────────────────────────────────────────

async def set_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    await update.message.reply_text(
        "✏️ Шинэ автомат хариулт текстийг бичнэ үү:\n\n"
        "(Цуцлах бол /cancel бичнэ үү)"
    )
    return WAITING_REPLY_TEXT


async def set_reply_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    new_text = update.message.text.strip()
    if not new_text:
        await update.message.reply_text("❌ Хоосон текст хадгалах боломжгүй.")
        return WAITING_REPLY_TEXT

    db.set_auto_reply(new_text)
    await update.message.reply_text(
        f"✅ Автомат хариулт амжилттай хадгалагдлаа!\n\n"
        f"📝 Шинэ текст:\n{new_text}"
    )
    return ConversationHandler.END


async def cancel_setreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Цуцлагдлаа.")
    return ConversationHandler.END


async def view_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    current = db.get_auto_reply()
    await update.message.reply_text(
        f"📋 Одоогийн автомат хариулт:\n\n{current}"
    )


# ─────────────────────────────────────────────
# VIP командууд
# ─────────────────────────────────────────────

async def add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    if len(context.args) != 2:
        await update.message.reply_text("❌ Хэрэглэх заавар:\n/addvip <user_id> <хоног>")
        return

    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id эсвэл хоног буруу байна.")
        return

    result = db.add_vip(target_id, days)
    if result:
        expiry = db.get_vip_expiry(target_id)
        await update.message.reply_text(
            f"✅ VIP нэмэгдлээ!\n"
            f"👤 ID: {target_id}\n"
            f"📅 Дуусах огноо: {expiry}"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🌟 Таны VIP эрх идэвхжлээ!\n📅 Дуусах огноо: {expiry}"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Хэрэглэгч олдсонгүй эсвэл алдаа гарлаа.")


async def extend_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    if len(context.args) != 2:
        await update.message.reply_text("❌ Хэрэглэх заавар:\n/extendvip <user_id> <хоног>")
        return

    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id эсвэл хоног буруу байна.")
        return

    result = db.extend_vip(target_id, days)
    if result:
        expiry = db.get_vip_expiry(target_id)
        await update.message.reply_text(
            f"✅ VIP сунгагдлаа!\n"
            f"👤 ID: {target_id}\n"
            f"📅 Шинэ дуусах огноо: {expiry}"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"🌟 Таны VIP хугацаа сунгагдлаа!\n📅 Шинэ дуусах огноо: {expiry}"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Хэрэглэгч олдсонгүй эсвэл VIP эрхгүй байна.")


async def remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ Хэрэглэх заавар:\n/removevip <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id буруу байна.")
        return

    result = db.remove_vip(target_id)
    if result:
        await update.message.reply_text(f"✅ {target_id}-н VIP эрх цуцлагдлаа.")
        # Группаас хасах
        await kick_from_vip_group(context, target_id, "Админ гараар цуцаллаа")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ Таны VIP эрх цуцлагдлаа."
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Хэрэглэгч олдсонгүй эсвэл VIP эрхгүй байна.")


async def vip_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    vips = db.get_all_vips()
    if not vips:
        await update.message.reply_text("📋 Идэвхтэй VIP хэрэглэгч байхгүй байна.")
        return

    text = "🌟 <b>Идэвхтэй VIP хэрэглэгчид:</b>\n\n"
    for v in vips:
        text += (
            f"👤 {v['first_name'] or '-'} (@{v['username'] or 'байхгүй'})\n"
            f"   🆔 ID: <code>{v['user_id']}</code>\n"
            f"   📅 Дуусах: {v['vip_expires']}\n\n"
        )
    await update.message.reply_text(text, parse_mode="HTML")


async def vip_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ Хэрэглэх заавар:\n/vipinfo <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id буруу байна.")
        return

    info = db.get_user_info(target_id)
    if not info:
        await update.message.reply_text("❌ Хэрэглэгч олдсонгүй.")
        return

    vip_status = "✅ Идэвхтэй" if info['is_vip'] else "❌ VIP эрхгүй"
    text = (
        f"👤 <b>Хэрэглэгчийн мэдээлэл</b>\n\n"
        f"🆔 ID: <code>{info['user_id']}</code>\n"
        f"📌 Username: @{info['username'] or 'байхгүй'}\n"
        f"🏷 Нэр: {info['first_name'] or '-'}\n"
        f"📅 Бүртгүүлсэн: {info['registered_at']}\n"
        f"🌟 VIP статус: {vip_status}\n"
    )
    if info['is_vip']:
        text += (
            f"📆 VIP эхэлсэн: {info['vip_started']}\n"
            f"📅 VIP дуусах: {info['vip_expires']}\n"
        )
    await update.message.reply_text(text, parse_mode="HTML")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    s = db.get_stats()
    text = (
        f"📊 <b>Статистик</b>\n\n"
        f"👥 Нийт хэрэглэгч: {s['total_users']}\n"
        f"🌟 Нийт VIP: {s['total_vip']}\n"
        f"❌ Дууссан VIP: {s['expired_vip']}\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ─────────────────────────────────────────────
# VIP хугацаа шалгах (scheduler)
# ─────────────────────────────────────────────

async def kick_from_vip_group(context: ContextTypes.DEFAULT_TYPE, user_id: int, reason: str = ""):
    """VIP группаас хэрэглэгчийг хасна."""
    if not config.VIP_GROUP_ID:
        return
    try:
        await context.bot.ban_chat_member(chat_id=config.VIP_GROUP_ID, user_id=user_id)
        await context.bot.unban_chat_member(chat_id=config.VIP_GROUP_ID, user_id=user_id)
        logger.info(f"Хэрэглэгч {user_id} VIP группаас хасагдлаа. {reason}")
    except Exception as e:
        logger.error(f"Группаас хасахад алдаа ({user_id}): {e}")


async def check_vip_expiry(context: ContextTypes.DEFAULT_TYPE):
    """Өдөр бүр ажиллах: хугацаа дуусвал хасна, сануулга илгээнэ."""
    logger.info("VIP хугацаа шалгаж байна...")

    # Хугацаа дуусчихсан
    expired = db.get_expired_vips()
    for u in expired:
        uid = u['user_id']
        name = u['first_name'] or str(uid)

        # Группаас хасах
        await kick_from_vip_group(context, uid, "Хугацаа дууссан")

        # DB шинэчлэх
        db.deactivate_vip(uid)

        # Хэрэглэгчид мэдэгдэл
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    "❌ Таны VIP хугацаа дууслаа.\n"
                    "VIP үргэлжлүүлэх бол бидэнтэй холбогдоно уу."
                )
            )
        except Exception:
            pass

        # Админуудад мэдэгдэл
        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"⚠️ <b>VIP дууссан</b>\n"
                        f"👤 {name} (<code>{uid}</code>) VIP группаас хасагдлаа."
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

    # 3 хоногийн сануулга
    remind_3 = db.get_vips_expiring_in_days(3)
    for u in remind_3:
        uid = u['user_id']
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    "⏰ Таны VIP хугацаа <b>3 хоног</b> дараа дуусна.\n"
                    "Сунгуулах бол бидэнтэй холбогдоно уу."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    # 1 хоногийн сануулга
    remind_1 = db.get_vips_expiring_in_days(1)
    for u in remind_1:
        uid = u['user_id']
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    "🚨 Таны VIP хугацаа <b>маргааш</b> дуусна!\n"
                    "Яаралтай сунгуулах бол бидэнтэй холбогдоно уу."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

    logger.info(f"Шалгалт дууслаа: {len(expired)} дууссан, "
                f"{len(remind_3)} 3 хоногт, {len(remind_1)} 1 хоногт.")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    db.init_db()

    app = Application.builder().token(config.BOT_TOKEN).build()

    # /setreply ConversationHandler
    set_reply_conv = ConversationHandler(
        entry_points=[CommandHandler("setreply", set_reply_start)],
        states={
            WAITING_REPLY_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_reply_receive)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_setreply)],
    )

    # Командууд бүртгэх
    app.add_handler(set_reply_conv)
    app.add_handler(CommandHandler("viewreply", view_reply))
    app.add_handler(CommandHandler("reply", admin_reply))
    app.add_handler(CommandHandler("addvip", add_vip))
    app.add_handler(CommandHandler("extendvip", extend_vip))
    app.add_handler(CommandHandler("removevip", remove_vip))
    app.add_handler(CommandHandler("viplist", vip_list))
    app.add_handler(CommandHandler("vipinfo", vip_info))
    app.add_handler(CommandHandler("stats", stats))

    # Хэрэглэгчийн мессеж (бүх текст, медиа)
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO |
         filters.Document.ALL | filters.VOICE | filters.Sticker.ALL)
        & ~filters.COMMAND,
        handle_user_message
    ))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_vip_expiry,
        trigger="cron",
        hour=9,
        minute=0,
        args=[app],
        id="vip_check"
    )
    scheduler.start()

    logger.info("Бот эхэллээ...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
