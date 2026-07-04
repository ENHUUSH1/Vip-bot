import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ChatMemberHandler, ChatJoinRequestHandler
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


async def forward_to_admins(context: ContextTypes.DEFAULT_TYPE, user, header_extra: str = ""):
    """Хэрэглэгчийн талаарх мэдээллийг бүх админд дамжуулна (start үед ашиглана)."""
    username_str = f"@{user.username}" if user.username else "username байхгүй"
    header = f"{user.first_name} ({username_str}) | ID: {user.id}{header_extra}"
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=header)
        except TelegramError as e:
            logger.error(f"Admin {admin_id} алдаа: {e}")


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

    # Шинэ хэрэглэгчийн талаар админд мэдэгдэнэ
    await forward_to_admins(context, user, header_extra="\n[/start дарсан]")


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

    # ── VIP хугацаа асуулт хариулах (bot_data дотор хадгалсан) ──
    pending = context.bot_data.get('pending_vip')
    if pending:
        duration = db.parse_duration(text)
        if duration is not None:
            target_user_id = pending['user_id']
            chat_id = pending['chat_id']
            chat_title = pending.get('chat_title', '')
            username = pending['username']
            expiry = db.add_vip(target_user_id, chat_id, duration, chat_title=chat_title)
            expiry_str = expiry.strftime('%Y-%m-%d %H:%M')
            await message.reply_text(
                f"✅ VIP нэмэгдлээ\n"
                f"👤 {username}\n"
                f"🆔 {target_user_id}\n"
                f"📺 {chat_title or chat_id}\n"
                f"📅 Дуусах: {expiry_str}"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 Таны VIP эрх идэвхжлээ!\n📅 Дуусах огноо: {expiry_str}"
                )
            except TelegramError:
                pass
            context.bot_data.pop('pending_vip', None)
            return
        # Формат таарахгүй бол доош нь үргэлжилнэ (өөр команд гэж үзнэ)

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

    # ── Reply хийсэн бол тэр хэрэглэгчид хариулна ──
    if message.reply_to_message:
        replied_msg_id = message.reply_to_message.message_id
        target_id = db.get_user_from_message(replied_msg_id, user.id)
        if target_id:
            try:
                await context.bot.send_message(chat_id=target_id, text=text)
            except TelegramError as e:
                await message.reply_text(f"❌ Алдаа: {e}")
            return

    # ── Сүүлд бичсэн хэрэглэгчид хариулна ──
    last_user = context.bot_data.get('last_user')
    if not last_user:
        await message.reply_text("❌ Хариулах хэрэглэгч байхгүй.")
        return

    try:
        await context.bot.send_message(chat_id=last_user, text=text)
    except TelegramError as e:
        await message.reply_text(f"❌ Алдаа: {e}")


# ─── VIP ГРУППТ ШИНЭ ГИШҮҮН (group-д л ажиллана) ──────────────────
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
            f"(Жишээ: 3d = 3 хоног, 12t = 12 цаг, 30m = 30 минут, эсвэл 1d12t)"
        )

        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=msg)
            except TelegramError as e:
                logger.error(f"Admin мэдэгдэл алдаа: {e}")

        context.bot_data['pending_vip'] = {
            'user_id': new_member.id,
            'chat_id': chat_id,
            'chat_title': chat_title,
            'username': f"{new_member.first_name} ({username_str})"
        }


# ─── VIP ГРУППТ JOIN REQUEST (channel-д ашиглана) ─────────────────
async def handle_join_request_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Хэрэглэгч join request-ээр орохыг хүсэхэд автоматаар зөвшөөрнө,
    дараа нь VIP хугацаа асууна."""
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
    chat_title = request.chat.title or str(chat_id)

    msg = (
        f"🔔 Шинэ гишүүн нэмэгдлээ\n\n"
        f"👤 Нэр: {user.first_name} ({username_str})\n"
        f"🆔 ID: {user.id}\n"
        f"📺 Суваг: {chat_title}\n\n"
        f"Энэ хүн хэдэн хоногоор VIP эрхтэй вэ?\n"
        f"(Жишээ: 3d = 3 хоног, 12t = 12 цаг, 30m = 30 минут, эсвэл 1d12t)"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=msg)
        except TelegramError as e:
            logger.error(f"Admin мэдэгдэл алдаа: {e}")

    context.bot_data['pending_vip'] = {
        'user_id': user.id,
        'chat_id': chat_id,
        'chat_title': chat_title,
        'username': f"{user.first_name} ({username_str})"
    }


# ─── VIP КОМАНДУУД ────────────────────────────────────────────────
async def cmd_add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(
            "📌 Хэрэглээ: /addvip [user_id] [chat_id] [хугацаа]\n"
            "Хугацаа: 3d (хоног), 12t (цаг), 30m (минут), эсвэл хослуулж 1d12t"
        )
        return
    try:
        user_id = int(args[0])
        chat_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id/chat_id буруу формат.")
        return
    duration = db.parse_duration(args[2])
    if duration is None:
        await update.message.reply_text("❌ Хугацааны формат буруу. Жишээ: 3d, 12t, 30m, 1d12t")
        return

    chat_title = ""
    try:
        chat = await context.bot.get_chat(chat_id)
        chat_title = chat.title or ""
    except TelegramError:
        pass

    expiry = db.add_vip(user_id, chat_id, duration, chat_title=chat_title)
    expiry_str = expiry.strftime('%Y-%m-%d %H:%M')
    user_info = db.get_user_info(user_id)
    name = user_info['first_name'] if user_info and user_info['first_name'] else str(user_id)
    username = f"@{user_info['username']}" if user_info and user_info['username'] else "—"

    await update.message.reply_text(
        f"✅ VIP нэмэгдлээ\n👤 {name} ({username})\n🆔 {user_id}\n"
        f"📺 {chat_title or chat_id}\n📅 Дуусах: {expiry_str}"
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 Таны VIP эрх идэвхжлээ!\n📅 Дуусах огноо: {expiry_str}"
        )
    except TelegramError:
        pass


async def cmd_extend_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text(
            "📌 Хэрэглээ: /extendvip [user_id] [chat_id] [хугацаа]\n"
            "Хугацаа: 3d (хоног), 12t (цаг), 30m (минут), эсвэл хослуулж 1d12t"
        )
        return
    try:
        user_id = int(args[0])
        chat_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id/chat_id буруу формат.")
        return
    duration = db.parse_duration(args[2])
    if duration is None:
        await update.message.reply_text("❌ Хугацааны формат буруу. Жишээ: 3d, 12t, 30m, 1d12t")
        return
    result = db.extend_vip(user_id, chat_id, duration)
    if result:
        expiry_str = result.strftime('%Y-%m-%d %H:%M')
        await update.message.reply_text(f"✅ VIP сунгагдлаа\n📅 Шинэ дуусах: {expiry_str}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 VIP сунгагдлаа!\n📅 Шинэ дуусах огноо: {expiry_str}"
            )
        except TelegramError:
            pass
    else:
        await update.message.reply_text("❌ Энэ хэрэглэгч тухайн channel дээр VIP биш байна.")


async def cmd_remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) not in (1, 2):
        await update.message.reply_text("📌 Хэрэглээ: /removevip [user_id] [chat_id]\n(chat_id өгөхгүй бол БҮХ channel-аас хасна)")
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Буруу формат.")
        return

    if len(args) == 2:
        try:
            chat_id = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Буруу формат.")
            return
        success = db.remove_vip(user_id, chat_id)
        chat_ids = [chat_id] if success else []
        if not success:
            await update.message.reply_text("❌ Хэрэглэгч энэ channel дээр VIP биш байна.")
            return
    else:
        chat_ids = db.remove_vip_all(user_id)
        if not chat_ids:
            await update.message.reply_text("❌ Хэрэглэгч VIP биш байна.")
            return

    await update.message.reply_text(f"✅ {user_id}-ийн VIP цуцлагдлаа.")
    for gid in chat_ids:
        try:
            await context.bot.ban_chat_member(gid, user_id)
            await context.bot.unban_chat_member(gid, user_id)
        except TelegramError:
            pass
    try:
        await context.bot.send_message(chat_id=user_id, text="❌ Таны VIP эрх цуцлагдлаа.")
    except TelegramError:
        pass


async def cmd_vip_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        expiry = v['vip_expiry'][:16].replace('T', ' ') if v['vip_expiry'] else "—"
        chat_title = v['chat_title'] or str(v['chat_id'])
        lines.append(f"{name} ({username}) | {v['user_id']} | {chat_title} | {expiry}")
    await update.message.reply_text("\n".join(lines))


async def cmd_vip_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    lines = [
        f"ID: {user['user_id']}",
        f"Нэр: {user['first_name'] or '—'}",
        f"Username: {username_str}",
    ]
    if not memberships:
        lines.append("VIP: Идэвхгүй (ямар ч channel дээр байхгүй)")
    else:
        lines.append("VIP channel-ууд:")
        for m in memberships:
            chat_title = m['chat_title'] or str(m['chat_id'])
            expiry = m['vip_expiry'][:16].replace('T', ' ') if m['vip_expiry'] else "—"
            lines.append(f"  • {chat_title}: {expiry}")
    await update.message.reply_text("\n".join(lines))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = db.get_stats()
    await update.message.reply_text(
        f"Нийт хэрэглэгч: {s['total_users']}\n"
        f"Идэвхтэй VIP бичлэг: {s['total_vip']}\n"
        f"Идэвхтэй VIP хэрэглэгч: {s['total_vip_users']}"
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
        except TelegramError:
            pass

    for user in db.get_expiring_soon(2):
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text="⚠️ Таны VIP эрх 2 хоногийн дотор дуусна!\nСунгуулахыг хүсвэл яараарай."
            )
        except TelegramError:
            pass

    for user in db.get_expired_vips():
        uid = user['user_id']
        gid = user['chat_id']
        name = user.get('first_name') or str(uid)
        username = f"@{user['username']}" if user.get('username') else "—"
        chat_title = user.get('chat_title') or str(gid)

        db.remove_vip(uid, gid)

        try:
            await bot.ban_chat_member(gid, uid)
            await bot.unban_chat_member(gid, uid)
        except TelegramError:
            pass

        try:
            await bot.send_message(
                chat_id=uid,
                text=f"❌ {chat_title} дээрх таны VIP эрхийн хугацаа дууслаа.\nСунгуулахыг хүсвэл бидэнтэй холбогдоно уу."
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

    # Админы мессеж — командуудын дараа бүртгэгдэх ёстой, гэхдээ
    # filters-аар л админыг ялгадаг тул дараалал хамаагүй; group=1-ээр доош тавья
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.User(config.ADMIN_IDS) & filters.TEXT,
            handle_admin_message
        ),
        group=1
    )

    app.add_handler(CommandHandler('addvip', cmd_add_vip))
    app.add_handler(CommandHandler('extendvip', cmd_extend_vip))
    app.add_handler(CommandHandler('removevip', cmd_remove_vip))
    app.add_handler(CommandHandler('viplist', cmd_vip_list))
    app.add_handler(CommandHandler('vipinfo', cmd_vip_info))
    app.add_handler(CommandHandler('stats', cmd_stats))
    app.add_handler(CommandHandler('setreply', set_reply))
    app.add_handler(CommandHandler('viewreply', view_reply))

    app.add_handler(
        MessageHandler(~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_message),
        group=1
    )

    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatJoinRequestHandler(handle_join_request_approved))

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

