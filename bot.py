import logging
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
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
    try:
        await update.message.reply_text(welcome, parse_mode=ParseMode.HTML)
    except TelegramError as e:
        # HTML parse алдаа гарвал (жишээ нь хадгалсан текст эвдэрсэн бол)
        # энгийн текстээр дор хаяж илгээгээд өнгөрнө.
        logger.error(f"Welcome HTML алдаа: {e}")
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
            await message.reply_text(welcome, parse_mode=ParseMode.HTML)
        except TelegramError as e:
            logger.error(f"Welcome HTML алдаа: {e}")
            try:
                await message.reply_text(welcome)
            except TelegramError as e2:
                logger.error(f"Welcome алдаа: {e2}")

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

            if pending.get('answered'):
                # Админ өмнө нь хариулсан ч буруу бичсэн гэж дахин илгээж байна —
                # хугацааг ОДООГООС шинээр тогтооно (нэмэхгүй, орлуулна).
                expiry = db.set_vip(target_user_id, chat_id, duration, chat_title=chat_title)
                expiry_str = expiry.strftime('%Y-%m-%d %H:%M')
                await message.reply_text(
                    f"🔄 Хугацаа засварлагдлаа\n"
                    f"👤 {username}\n"
                    f"🆔 {target_user_id}\n"
                    f"📺 {chat_title or chat_id}\n"
                    f"📅 Шинэ дуусах: {expiry_str}"
                )
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"ℹ️ Таны VIP дуусах хугацаа шинэчлэгдлээ.\n📺 {chat_title or chat_id}\n📅 Шинэ дуусах огноо: {expiry_str}"
                    )
                except TelegramError:
                    pass
            else:
                expiry = db.add_vip(target_user_id, chat_id, duration, chat_title=chat_title)
                expiry_str = expiry.strftime('%Y-%m-%d %H:%M')
                await message.reply_text(
                    f"✅ VIP нэмэгдлээ\n"
                    f"👤 {username}\n"
                    f"🆔 {target_user_id}\n"
                    f"📺 {chat_title or chat_id}\n"
                    f"📅 Дуусах: {expiry_str}\n\n"
                    f"⚠️ Хугацаа буруу бол дахин зөв хугацаа бичихэд шууд засна."
                )
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"🎉 Таны VIP эрх идэвхжлээ!\n📺 {chat_title or chat_id}\n📅 Дуусах огноо: {expiry_str}"
                    )
                except TelegramError:
                    pass
                pending['answered'] = True
                context.bot_data['pending_vip'] = pending
            return
        # Формат таарахгүй бол доош нь үргэлжилнэ (өөр команд гэж үзнэ)

    if text == '/done' and pending:
        context.bot_data.pop('pending_vip', None)
        await message.reply_text("✅ Дууслаа. Хугацаа засах горим хаагдлаа.")
        return

    # ── /r ID текст ──
    if text.startswith('/r '):
        parts = text.split(' ', 2)
        if len(parts) >= 3:
            try:
                target_id = int(parts[1])
                reply_text = parts[2]
                sent = await context.bot.send_message(chat_id=target_id, text=reply_text)
                context.bot_data['last_sent'] = {'chat_id': target_id, 'message_id': sent.message_id}
                await message.reply_text(f"✅ {target_id}-д илгээгдлээ. (Устгах бол /delete)")
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
                sent = await context.bot.send_message(chat_id=target_id, text=text)
                context.bot_data['last_sent'] = {'chat_id': target_id, 'message_id': sent.message_id}
            except TelegramError as e:
                await message.reply_text(f"❌ Алдаа: {e}")
            return

    # ── Сүүлд бичсэн хэрэглэгчид хариулна ──
    last_user = context.bot_data.get('last_user')
    if not last_user:
        await message.reply_text("❌ Хариулах хэрэглэгч байхгүй.")
        return

    try:
        sent = await context.bot.send_message(chat_id=last_user, text=text)
        context.bot_data['last_sent'] = {'chat_id': last_user, 'message_id': sent.message_id}
    except TelegramError as e:
        await message.reply_text(f"❌ Алдаа: {e}")


# ─── СҮҮЛД ИЛГЭЭСЭН ХАРИУГ УСТГАХ ────────────────────────────────
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    last_sent = context.bot_data.get('last_sent')
    if not last_sent:
        await update.message.reply_text("❌ Устгах мессеж алга (сүүлд юу ч илгээгээгүй байна).")
        return
    try:
        await context.bot.delete_message(
            chat_id=last_sent['chat_id'],
            message_id=last_sent['message_id']
        )
        context.bot_data.pop('last_sent', None)
        await update.message.reply_text("🗑 Хэрэглэгчийн талд байгаа мессеж устгагдлаа.")
    except TelegramError as e:
        await update.message.reply_text(
            f"❌ Устгаж чадсангүй: {e}\n"
            f"(Telegram 48 цагаас хойш илгээсэн мессежийг устгуулахгүй байж болно.)"
        )


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
        # Хэрэв энэ хэрэглэгчийг сая handle_join_request_approved (channel-ийн
        # "Approve new members" горим) аль хэдийн асуусан бол давхардуулж
        # дахин бичихгүй — Telegram join request зөвшөөрөгдөх үед мөн энэ
        # chat_member event-ийг автоматаар үүсгэдэг тул.
        pending = context.bot_data.get('pending_vip')
        if pending and pending.get('user_id') == new_member.id and pending.get('chat_id') == chat_id:
            return

        username_str = f"@{new_member.username}" if new_member.username else "—"
        chat_title = result.chat.title or str(chat_id)

        msg = (
            f"🔔 Шинэ гишүүн нэмэгдлээ\n\n"
            f"👤 Нэр: {new_member.first_name} ({username_str})\n"
            f"🆔 ID: {new_member.id}\n"
            f"📺 Суваг: {chat_title}\n\n"
            f"Энэ хүн хэдэн хоногоор VIP эрхтэй вэ?\n"
            f"(Жишээ: 3d = 3 хоног, 12h = 12 цаг, 30m = 30 минут, эсвэл 1d12h)"
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
        f"(Жишээ: 3d = 3 хоног, 12h = 12 цаг, 30m = 30 минут, эсвэл 1d12h)"
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
            "Хугацаа: 3d (хоног), 12h (цаг), 30m (минут), эсвэл хослуулж 1d12h"
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
        await update.message.reply_text("❌ Хугацааны формат буруу. Жишээ: 3d, 12h, 30m, 1d12h")
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
            text=f"🎉 Таны VIP эрх идэвхжлээ!\n📺 {chat_title or chat_id}\n📅 Дуусах огноо: {expiry_str}"
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
            "Хугацаа: 3d (хоног), 12h (цаг), 30m (минут), эсвэл хослуулж 1d12h"
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
        await update.message.reply_text("❌ Хугацааны формат буруу. Жишээ: 3d, 12h, 30m, 1d12h")
        return

    chat_title = ""
    try:
        chat = await context.bot.get_chat(chat_id)
        chat_title = chat.title or ""
    except TelegramError:
        pass

    result = db.extend_vip(user_id, chat_id, duration)
    if result:
        expiry_str = result.strftime('%Y-%m-%d %H:%M')
        await update.message.reply_text(f"✅ VIP сунгагдлаа\n📺 {chat_title or chat_id}\n📅 Шинэ дуусах: {expiry_str}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 VIP сунгагдлаа!\n📺 {chat_title or chat_id}\n📅 Шинэ дуусах огноо: {expiry_str}"
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
    message = update.message
    raw_text = message.text or ""
    raw_html = message.text_html or ""
    # context.args ашиглавал бүх мөр таслалт (newline) зайгаар солигдож,
    # хэрэглэгчийн бичсэн форматыг гээдэг тул raw текстээс шууд авна.
    # Зөвхөн ЭХНИЙ зай/мөр таслалтаар л таслаж, үлдсэнийг бүхэлд нь хэвээр үлдээнэ.
    parts = raw_text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        current = db.get_auto_reply()
        await message.reply_text(
            f"Одоогийн автомат хариулт:\n{current}\n\nӨөрчлөхдөө:\n/setreply [шинэ текст]",
            parse_mode=ParseMode.HTML,
        )
        return

    # /setreply-ийн дараах бодит текстийг HTML хэлбэрээр авна.
    # "/setreply " (команд + эхний зай) яг pure ASCII тул урт нь
    # Python str индекс болон Telegram-ийн UTF-16 offset дээр адилхан
    # тохирдог — тиймээс HTML tag-уудыг (animated/custom emoji зэргийг)
    # алдалгүй яг зөв тасалж чадна.
    prefix_len = len(raw_text) - len(parts[1])
    new_html = raw_html[prefix_len:]

    db.set_auto_reply(new_html)
    await message.reply_text(
        f"✅ Автомат хариулт шинэчлэгдлээ:\n{new_html}",
        parse_mode=ParseMode.HTML,
    )


async def view_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(f"Автомат хариулт:\n{current}", parse_mode=ParseMode.HTML)


# ─── SCHEDULER ────────────────────────────────────────────────────
async def check_expiry_warnings(context: ContextTypes.DEFAULT_TYPE):
    """Өдөрт 1 удаа (09:00) ажиллаж, 3 болон 2 хоногийн дотор дуусах
    хэрэглэгчдэд сануулга илгээнэ."""
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


async def check_expired_vips(context: ContextTypes.DEFAULT_TYPE):
    """Байнга (минут тутам) ажиллаж, хугацаа дууссан VIP-үүдийг шууд хасна."""
    bot = context.bot

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

    # 1) Энгийн хэрэглэгчид зориулсан командууд
    app.add_handler(CommandHandler('start', start))

    # 2) VIP гишүүнчлэлийн удирдлагын командууд (админ)
    app.add_handler(CommandHandler('addvip', cmd_add_vip))
    app.add_handler(CommandHandler('extendvip', cmd_extend_vip))
    app.add_handler(CommandHandler('removevip', cmd_remove_vip))
    app.add_handler(CommandHandler('viplist', cmd_vip_list))
    app.add_handler(CommandHandler('vipinfo', cmd_vip_info))

    # 3) Автомат хариултын тохиргоо (админ)
    app.add_handler(CommandHandler('setreply', set_reply))
    app.add_handler(CommandHandler('viewreply', view_reply))

    # 4) Ерөнхий статистик (админ)
    app.add_handler(CommandHandler('stats', cmd_stats))

    # 4.1) Сүүлд илгээсэн хариуг устгах (админ)
    app.add_handler(CommandHandler('delete', cmd_delete))

    # 5) Чөлөөт мессежийн handler-ууд (командын дараа, group=1)
    #    - Админ бичихэд: VIP хугацаа асуулт, /r, reply, сүүлд бичсэн хэрэглэгчид хариулах
    #    - Энгийн хэрэглэгч бичихэд: админд дамжуулах + автомат хариулт
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.User(config.ADMIN_IDS) & filters.TEXT,
            handle_admin_message
        ),
        group=1
    )
    app.add_handler(
        MessageHandler(~filters.COMMAND & filters.ChatType.PRIVATE, handle_user_message),
        group=1
    )

    # 6) Групп/суваг дахь гишүүнчлэлийн event-үүд
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatJoinRequestHandler(handle_join_request_approved))

    # 7) Автомат шалгалтууд (сануулга, хугацаа дуусах)
    scheduler = AsyncIOScheduler(timezone=db.MN_TZ)
    scheduler.add_job(
        check_expired_vips,
        trigger='interval',
        minutes=1,
        kwargs={'context': app}
    )
    scheduler.add_job(
        check_expiry_warnings,
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

