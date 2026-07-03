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
    """Ð¥ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð¹Ð½ Ñ‚Ð°Ð»Ð°Ð°Ñ€Ñ… Ð¼ÑÐ´ÑÑÐ»Ð»Ð¸Ð¹Ð³ Ð±Ò¯Ñ… Ð°Ð´Ð¼Ð¸Ð½Ð´ Ð´Ð°Ð¼Ð¶ÑƒÑƒÐ»Ð½Ð° (start Ò¯ÐµÐ´ Ð°ÑˆÐ¸Ð³Ð»Ð°Ð½Ð°)."""
    username_str = f"@{user.username}" if user.username else "username Ð±Ð°Ð¹Ñ…Ð³Ò¯Ð¹"
    header = f"{user.first_name} ({username_str}) | ID: {user.id}{header_extra}"
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=header)
        except TelegramError as e:
            logger.error(f"Admin {admin_id} Ð°Ð»Ð´Ð°Ð°: {e}")


# â”€â”€â”€ START â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(user.id):
        return

    db.register_user(user.id, user.username, user.first_name)
    context.user_data['last_message_time'] = datetime.now()
    context.bot_data['last_user'] = user.id

    welcome = db.get_auto_reply()
    await update.message.reply_text(welcome)

    # Ð¨Ð¸Ð½Ñ Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð¹Ð½ Ñ‚Ð°Ð»Ð°Ð°Ñ€ Ð°Ð´Ð¼Ð¸Ð½Ð´ Ð¼ÑÐ´ÑÐ³Ð´ÑÐ½Ñ
    await forward_to_admins(context, user, header_extra="\n[/start Ð´Ð°Ñ€ÑÐ°Ð½]")


# â”€â”€â”€ Ð¥Ð­Ð Ð­Ð“Ð›Ð­Ð“Ð§Ð˜Ð™Ð ÐœÐ•Ð¡Ð¡Ð•Ð– â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
            logger.error(f"Welcome Ð°Ð»Ð´Ð°Ð°: {e}")

    context.bot_data['last_user'] = user.id

    username_str = f"@{user.username}" if user.username else "username Ð±Ð°Ð¹Ñ…Ð³Ò¯Ð¹"
    header = f"{user.first_name} ({username_str}) | ID: {user.id}"

    if message.text:
        forward_text = f"{header}\n{message.text}"
    elif message.photo:
        forward_text = f"{header}\n[Ð—ÑƒÑ€Ð°Ð³]"
    elif message.video:
        forward_text = f"{header}\n[Ð’Ð¸Ð´ÐµÐ¾]"
    elif message.voice:
        forward_text = f"{header}\n[Ð”ÑƒÑƒ]"
    elif message.document:
        forward_text = f"{header}\n[Ð¤Ð°Ð¹Ð»]"
    elif message.sticker:
        forward_text = f"{header}\n[Ð¡Ñ‚Ð¸ÐºÐµÑ€]"
    else:
        forward_text = f"{header}\n[ÐœÐµÐ´Ð¸Ð°]"

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
            logger.error(f"Admin {admin_id} Ð°Ð»Ð´Ð°Ð°: {e}")


# â”€â”€â”€ ÐÐ”ÐœÐ˜ÐÐ« Ð¥ÐÐ Ð˜Ð£ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ VIP Ñ…ÑƒÐ³Ð°Ñ†Ð°Ð° Ð°ÑÑƒÑƒÐ»Ñ‚ Ñ…Ð°Ñ€Ð¸ÑƒÐ»Ð°Ñ… (bot_data Ð´Ð¾Ñ‚Ð¾Ñ€ Ñ…Ð°Ð´Ð³Ð°Ð»ÑÐ°Ð½) â”€â”€
    pending = context.bot_data.get('pending_vip')
    if pending and text.lstrip('-').isdigit():
        try:
            days = int(text)
            target_user_id = pending['user_id']
            chat_id = pending['chat_id']
            chat_title = pending.get('chat_title', '')
            username = pending['username']
            expiry = db.add_vip(target_user_id, chat_id, days, chat_title=chat_title)
            expiry_str = expiry.strftime('%Y-%m-%d')
            await message.reply_text(
                f"âœ… VIP Ð½ÑÐ¼ÑÐ³Ð´Ð»ÑÑ\n"
                f"ðŸ‘¤ {username}\n"
                f"ðŸ†” {target_user_id}\n"
                f"ðŸ“º {chat_title or chat_id}\n"
                f"ðŸ“… Ð”ÑƒÑƒÑÐ°Ñ…: {expiry_str}"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"ðŸŽ‰ Ð¢Ð°Ð½Ñ‹ VIP ÑÑ€Ñ… Ð¸Ð´ÑÐ²Ñ…Ð¶Ð»ÑÑ!\nðŸ“… Ð”ÑƒÑƒÑÐ°Ñ… Ð¾Ð³Ð½Ð¾Ð¾: {expiry_str}"
                )
            except TelegramError:
                pass
            context.bot_data.pop('pending_vip', None)
            return
        except ValueError:
            pass  # Ñ‚Ð¾Ð¾ Ð±Ð¸Ñˆ Ð±Ð¾Ð» Ð´Ð¾Ð¾Ñˆ Ð½ÑŒ Ò¯Ñ€Ð³ÑÐ»Ð¶Ð¸Ð»Ð½Ñ (Ó©Ó©Ñ€ ÐºÐ¾Ð¼Ð°Ð½Ð´ Ð³ÑÐ¶ Ò¯Ð·Ð½Ñ)

    # â”€â”€ /r ID Ñ‚ÐµÐºÑÑ‚ â”€â”€
    if text.startswith('/r '):
        parts = text.split(' ', 2)
        if len(parts) >= 3:
            try:
                target_id = int(parts[1])
                reply_text = parts[2]
                await context.bot.send_message(chat_id=target_id, text=reply_text)
                await message.reply_text(f"âœ… {target_id}-Ð´ Ð¸Ð»Ð³ÑÑÐ³Ð´Ð»ÑÑ.")
            except Exception as e:
                await message.reply_text(f"âŒ ÐÐ»Ð´Ð°Ð°: {e}")
        else:
            await message.reply_text("ðŸ“Œ Ð¥ÑÑ€ÑÐ³Ð»ÑÑ: /r [user_id] [Ñ‚ÐµÐºÑÑ‚]")
        return

    if text.startswith('/'):
        return

    # â”€â”€ Reply Ñ…Ð¸Ð¹ÑÑÐ½ Ð±Ð¾Ð» Ñ‚ÑÑ€ Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð´ Ñ…Ð°Ñ€Ð¸ÑƒÐ»Ð½Ð° â”€â”€
    if message.reply_to_message:
        replied_msg_id = message.reply_to_message.message_id
        target_id = db.get_user_from_message(replied_msg_id, user.id)
        if target_id:
            try:
                await context.bot.send_message(chat_id=target_id, text=text)
            except TelegramError as e:
                await message.reply_text(f"âŒ ÐÐ»Ð´Ð°Ð°: {e}")
            return

    # â”€â”€ Ð¡Ò¯Ò¯Ð»Ð´ Ð±Ð¸Ñ‡ÑÑÐ½ Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð´ Ñ…Ð°Ñ€Ð¸ÑƒÐ»Ð½Ð° â”€â”€
    last_user = context.bot_data.get('last_user')
    if not last_user:
        await message.reply_text("âŒ Ð¥Ð°Ñ€Ð¸ÑƒÐ»Ð°Ñ… Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡ Ð±Ð°Ð¹Ñ…Ð³Ò¯Ð¹.")
        return

    try:
        await context.bot.send_message(chat_id=last_user, text=text)
    except TelegramError as e:
        await message.reply_text(f"âŒ ÐÐ»Ð´Ð°Ð°: {e}")


# â”€â”€â”€ VIP Ð“Ð Ð£ÐŸÐŸÐ¢ Ð¨Ð˜ÐÐ­ Ð“Ð˜Ð¨Ò®Ò®Ð (group-Ð´ Ð» Ð°Ð¶Ð¸Ð»Ð»Ð°Ð½Ð°) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        username_str = f"@{new_member.username}" if new_member.username else "â€”"
        chat_title = result.chat.title or str(chat_id)

        msg = (
            f"ðŸ”” Ð¨Ð¸Ð½Ñ Ð³Ð¸ÑˆÒ¯Ò¯Ð½ Ð½ÑÐ¼ÑÐ³Ð´Ð»ÑÑ\n\n"
            f"ðŸ‘¤ ÐÑÑ€: {new_member.first_name} ({username_str})\n"
            f"ðŸ†” ID: {new_member.id}\n"
            f"ðŸ“º Ð¡ÑƒÐ²Ð°Ð³: {chat_title}\n\n"
            f"Ð­Ð½Ñ Ñ…Ò¯Ð½ Ñ…ÑÐ´ÑÐ½ Ñ…Ð¾Ð½Ð¾Ð³Ð¾Ð¾Ñ€ VIP ÑÑ€Ñ…Ñ‚ÑÐ¹ Ð²Ñ?\n"
            f"(Ð¢Ð¾Ð¾ Ð±Ð¸Ñ‡Ð½Ñ Ò¯Ò¯)"
        )

        for admin_id in config.ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=msg)
            except TelegramError as e:
                logger.error(f"Admin Ð¼ÑÐ´ÑÐ³Ð´ÑÐ» Ð°Ð»Ð´Ð°Ð°: {e}")

        context.bot_data['pending_vip'] = {
            'user_id': new_member.id,
            'chat_id': chat_id,
            'chat_title': chat_title,
            'username': f"{new_member.first_name} ({username_str})"
        }


# â”€â”€â”€ VIP Ð“Ð Ð£ÐŸÐŸÐ¢ JOIN REQUEST (channel-Ð´ Ð°ÑˆÐ¸Ð³Ð»Ð°Ð½Ð°) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def handle_join_request_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ð¥ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡ join request-ÑÑÑ€ Ð¾Ñ€Ð¾Ñ…Ñ‹Ð³ Ñ…Ò¯ÑÑÑ…ÑÐ´ Ð°Ð²Ñ‚Ð¾Ð¼Ð°Ñ‚Ð°Ð°Ñ€ Ð·Ó©Ð²ÑˆÓ©Ó©Ñ€Ð½Ó©,
    Ð´Ð°Ñ€Ð°Ð° Ð½ÑŒ VIP Ñ…ÑƒÐ³Ð°Ñ†Ð°Ð° Ð°ÑÑƒÑƒÐ½Ð°."""
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
        logger.error(f"Join request Ð·Ó©Ð²ÑˆÓ©Ó©Ñ€Ó©Ñ…Ó©Ð´ Ð°Ð»Ð´Ð°Ð°: {e}")
        return

    username_str = f"@{user.username}" if user.username else "â€”"
    chat_title = request.chat.title or str(chat_id)

    msg = (
        f"ðŸ”” Ð¨Ð¸Ð½Ñ Ð³Ð¸ÑˆÒ¯Ò¯Ð½ Ð½ÑÐ¼ÑÐ³Ð´Ð»ÑÑ\n\n"
        f"ðŸ‘¤ ÐÑÑ€: {user.first_name} ({username_str})\n"
        f"ðŸ†” ID: {user.id}\n"
        f"ðŸ“º Ð¡ÑƒÐ²Ð°Ð³: {chat_title}\n\n"
        f"Ð­Ð½Ñ Ñ…Ò¯Ð½ Ñ…ÑÐ´ÑÐ½ Ñ…Ð¾Ð½Ð¾Ð³Ð¾Ð¾Ñ€ VIP ÑÑ€Ñ…Ñ‚ÑÐ¹ Ð²Ñ?\n"
        f"(Ð¢Ð¾Ð¾ Ð±Ð¸Ñ‡Ð½Ñ Ò¯Ò¯)"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=msg)
        except TelegramError as e:
            logger.error(f"Admin Ð¼ÑÐ´ÑÐ³Ð´ÑÐ» Ð°Ð»Ð´Ð°Ð°: {e}")

    context.bot_data['pending_vip'] = {
        'user_id': user.id,
        'chat_id': chat_id,
        'chat_title': chat_title,
        'username': f"{user.first_name} ({username_str})"
    }


# â”€â”€â”€ VIP ÐšÐžÐœÐÐÐ”Ð£Ð£Ð” â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def cmd_add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("ðŸ“Œ Ð¥ÑÑ€ÑÐ³Ð»ÑÑ: /addvip [user_id] [chat_id] [Ñ…Ð¾Ð½Ð¾Ð³]")
        return
    try:
        user_id = int(args[0])
        chat_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await update.message.reply_text("âŒ Ð‘ÑƒÑ€ÑƒÑƒ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚.")
        return

    chat_title = ""
    try:
        chat = await context.bot.get_chat(chat_id)
        chat_title = chat.title or ""
    except TelegramError:
        pass

    expiry = db.add_vip(user_id, chat_id, days, chat_title=chat_title)
    expiry_str = expiry.strftime('%Y-%m-%d')
    user_info = db.get_user_info(user_id)
    name = user_info['first_name'] if user_info and user_info['first_name'] else str(user_id)
    username = f"@{user_info['username']}" if user_info and user_info['username'] else "â€”"

    await update.message.reply_text(
        f"âœ… VIP Ð½ÑÐ¼ÑÐ³Ð´Ð»ÑÑ\nðŸ‘¤ {name} ({username})\nðŸ†” {user_id}\n"
        f"ðŸ“º {chat_title or chat_id}\nðŸ“… Ð”ÑƒÑƒÑÐ°Ñ…: {expiry_str}"
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"ðŸŽ‰ Ð¢Ð°Ð½Ñ‹ VIP ÑÑ€Ñ… Ð¸Ð´ÑÐ²Ñ…Ð¶Ð»ÑÑ!\nðŸ“… Ð”ÑƒÑƒÑÐ°Ñ… Ð¾Ð³Ð½Ð¾Ð¾: {expiry_str}"
        )
    except TelegramError:
        pass


async def cmd_extend_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 3:
        await update.message.reply_text("ðŸ“Œ Ð¥ÑÑ€ÑÐ³Ð»ÑÑ: /extendvip [user_id] [chat_id] [Ñ…Ð¾Ð½Ð¾Ð³]")
        return
    try:
        user_id = int(args[0])
        chat_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await update.message.reply_text("âŒ Ð‘ÑƒÑ€ÑƒÑƒ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚.")
        return
    result = db.extend_vip(user_id, chat_id, days)
    if result:
        expiry_str = result.strftime('%Y-%m-%d')
        await update.message.reply_text(f"âœ… VIP ÑÑƒÐ½Ð³Ð°Ð³Ð´Ð»Ð°Ð°\nðŸ“… Ð¨Ð¸Ð½Ñ Ð´ÑƒÑƒÑÐ°Ñ…: {expiry_str}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"ðŸŽ‰ VIP ÑÑƒÐ½Ð³Ð°Ð³Ð´Ð»Ð°Ð°!\nðŸ“… Ð¨Ð¸Ð½Ñ Ð´ÑƒÑƒÑÐ°Ñ… Ð¾Ð³Ð½Ð¾Ð¾: {expiry_str}"
            )
        except TelegramError:
            pass
    else:
        await update.message.reply_text("âŒ Ð­Ð½Ñ Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡ Ñ‚ÑƒÑ…Ð°Ð¹Ð½ channel Ð´ÑÑÑ€ VIP Ð±Ð¸Ñˆ Ð±Ð°Ð¹Ð½Ð°.")


async def cmd_remove_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) not in (1, 2):
        await update.message.reply_text("ðŸ“Œ Ð¥ÑÑ€ÑÐ³Ð»ÑÑ: /removevip [user_id] [chat_id]\n(chat_id Ó©Ð³Ó©Ñ…Ð³Ò¯Ð¹ Ð±Ð¾Ð» Ð‘Ò®Ð¥ channel-Ð°Ð°Ñ Ñ…Ð°ÑÐ½Ð°)")
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("âŒ Ð‘ÑƒÑ€ÑƒÑƒ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚.")
        return

    if len(args) == 2:
        try:
            chat_id = int(args[1])
        except ValueError:
            await update.message.reply_text("âŒ Ð‘ÑƒÑ€ÑƒÑƒ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚.")
            return
        success = db.remove_vip(user_id, chat_id)
        chat_ids = [chat_id] if success else []
        if not success:
            await update.message.reply_text("âŒ Ð¥ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡ ÑÐ½Ñ channel Ð´ÑÑÑ€ VIP Ð±Ð¸Ñˆ Ð±Ð°Ð¹Ð½Ð°.")
            return
    else:
        chat_ids = db.remove_vip_all(user_id)
        if not chat_ids:
            await update.message.reply_text("âŒ Ð¥ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡ VIP Ð±Ð¸Ñˆ Ð±Ð°Ð¹Ð½Ð°.")
            return

    await update.message.reply_text(f"âœ… {user_id}-Ð¸Ð¹Ð½ VIP Ñ†ÑƒÑ†Ð»Ð°Ð³Ð´Ð»Ð°Ð°.")
    for gid in chat_ids:
        try:
            await context.bot.ban_chat_member(gid, user_id)
            await context.bot.unban_chat_member(gid, user_id)
        except TelegramError:
            pass
    try:
        await context.bot.send_message(chat_id=user_id, text="âŒ Ð¢Ð°Ð½Ñ‹ VIP ÑÑ€Ñ… Ñ†ÑƒÑ†Ð»Ð°Ð³Ð´Ð»Ð°Ð°.")
    except TelegramError:
        pass


async def cmd_vip_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    vips = db.get_all_vips()
    if not vips:
        await update.message.reply_text("Ð˜Ð´ÑÐ²Ñ…Ñ‚ÑÐ¹ VIP Ð±Ð°Ð¹Ñ…Ð³Ò¯Ð¹.")
        return
    lines = ["VIP Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡Ð¸Ð´:"]
    for v in vips:
        name = v['first_name'] or 'â€”'
        username = f"@{v['username']}" if v['username'] else "â€”"
        expiry = v['vip_expiry'][:10] if v['vip_expiry'] else "â€”"
        chat_title = v['chat_title'] or str(v['chat_id'])
        lines.append(f"{name} ({username}) | {v['user_id']} | {chat_title} | {expiry}")
    await update.message.reply_text("\n".join(lines))


async def cmd_vip_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("ðŸ“Œ Ð¥ÑÑ€ÑÐ³Ð»ÑÑ: /vipinfo [user_id]")
        return
    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("âŒ Ð‘ÑƒÑ€ÑƒÑƒ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚.")
        return
    user = db.get_user_info(user_id)
    if not user:
        await update.message.reply_text("âŒ Ð¥ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡ Ð¾Ð»Ð´ÑÐ¾Ð½Ð³Ò¯Ð¹.")
        return
    username_str = f"@{user['username']}" if user['username'] else "â€”"

    memberships = db.get_vip_memberships(user_id)
    lines = [
        f"ID: {user['user_id']}",
        f"ÐÑÑ€: {user['first_name'] or 'â€”'}",
        f"Username: {username_str}",
    ]
    if not memberships:
        lines.append("VIP: Ð˜Ð´ÑÐ²Ñ…Ð³Ò¯Ð¹ (ÑÐ¼Ð°Ñ€ Ñ‡ channel Ð´ÑÑÑ€ Ð±Ð°Ð¹Ñ…Ð³Ò¯Ð¹)")
    else:
        lines.append("VIP channel-ÑƒÑƒÐ´:")
        for m in memberships:
            chat_title = m['chat_title'] or str(m['chat_id'])
            expiry = m['vip_expiry'][:10] if m['vip_expiry'] else "â€”"
            lines.append(f"  â€¢ {chat_title}: {expiry}")
    await update.message.reply_text("\n".join(lines))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s = db.get_stats()
    await update.message.reply_text(
        f"ÐÐ¸Ð¹Ñ‚ Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡: {s['total_users']}\n"
        f"Ð˜Ð´ÑÐ²Ñ…Ñ‚ÑÐ¹ VIP Ð±Ð¸Ñ‡Ð»ÑÐ³: {s['total_vip']}\n"
        f"Ð˜Ð´ÑÐ²Ñ…Ñ‚ÑÐ¹ VIP Ñ…ÑÑ€ÑÐ³Ð»ÑÐ³Ñ‡: {s['total_vip_users']}"
    )


async def set_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        current = db.get_auto_reply()
        await update.message.reply_text(
            f"ÐžÐ´Ð¾Ð¾Ð³Ð¸Ð¹Ð½ Ð°Ð²Ñ‚Ð¾Ð¼Ð°Ñ‚ Ñ…Ð°Ñ€Ð¸ÑƒÐ»Ñ‚:\n{current}\n\nÓ¨Ó©Ñ€Ñ‡Ð»Ó©Ñ…Ð´Ó©Ó©:\n/setreply [ÑˆÐ¸Ð½Ñ Ñ‚ÐµÐºÑÑ‚]"
        )
        return
    new_text = ' '.join(context.args)
    db.set_auto_reply(new_text)
    await update.message.reply_text(f"âœ… ÐÐ²Ñ‚Ð¾Ð¼Ð°Ñ‚ Ñ…Ð°Ñ€Ð¸ÑƒÐ»Ñ‚ ÑˆÐ¸Ð½ÑÑ‡Ð»ÑÐ³Ð´Ð»ÑÑ:\n{new_text}")


async def view_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    current = db.get_auto_reply()
    await update.message.reply_text(f"ÐÐ²Ñ‚Ð¾Ð¼Ð°Ñ‚ Ñ…Ð°Ñ€Ð¸ÑƒÐ»Ñ‚:\n{current}")


# â”€â”€â”€ SCHEDULER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def check_vip_expirations(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot

    for user in db.get_expiring_soon(3):
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text="âš ï¸ Ð¢Ð°Ð½Ñ‹ VIP ÑÑ€Ñ… 3 Ñ…Ð¾Ð½Ð¾Ð³Ð¸Ð¹Ð½ Ð´Ð¾Ñ‚Ð¾Ñ€ Ð´ÑƒÑƒÑÐ½Ð°!\nÐ¡ÑƒÐ½Ð³ÑƒÑƒÐ»Ð°Ñ…Ñ‹Ð³ Ñ…Ò¯ÑÐ²ÑÐ» Ð±Ð¸Ð´ÑÐ½Ñ‚ÑÐ¹ Ñ…Ð¾Ð»Ð±Ð¾Ð³Ð´Ð¾Ð½Ð¾ ÑƒÑƒ."
            )
        except TelegramError:
            pass

    for user in db.get_expiring_soon(2):
        try:
            await bot.send_message(
                chat_id=user['user_id'],
                text="âš ï¸ Ð¢Ð°Ð½Ñ‹ VIP ÑÑ€Ñ… 2 Ñ…Ð¾Ð½Ð¾Ð³Ð¸Ð¹Ð½ Ð´Ð¾Ñ‚Ð¾Ñ€ Ð´ÑƒÑƒÑÐ½Ð°!\nÐ¡ÑƒÐ½Ð³ÑƒÑƒÐ»Ð°Ñ…Ñ‹Ð³ Ñ…Ò¯ÑÐ²ÑÐ» ÑÐ°Ñ€Ð°Ð°Ñ€Ð°Ð¹."
            )
        except TelegramError:
            pass

    for user in db.get_expired_vips():
        uid = user['user_id']
        gid = user['chat_id']
        name = user.get('first_name') or str(uid)
        username = f"@{user['username']}" if user.get('username') else "â€”"
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
                text=f"âŒ {chat_title} Ð´ÑÑÑ€Ñ… Ñ‚Ð°Ð½Ñ‹ VIP ÑÑ€Ñ…Ð¸Ð¹Ð½ Ñ…ÑƒÐ³Ð°Ñ†Ð°Ð° Ð´ÑƒÑƒÑÐ»Ð°Ð°.\nÐ¡ÑƒÐ½Ð³ÑƒÑƒÐ»Ð°Ñ…Ñ‹Ð³ Ñ…Ò¯ÑÐ²ÑÐ» Ð±Ð¸Ð´ÑÐ½Ñ‚ÑÐ¹ Ñ…Ð¾Ð»Ð±Ð¾Ð³Ð´Ð¾Ð½Ð¾ ÑƒÑƒ."
            )
        except TelegramError:
            pass

        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"ðŸ”” VIP Ð´ÑƒÑƒÑÑÐ°Ð½\nðŸ‘¤ {name} ({username})\nðŸ†” {uid}\nðŸ“º {chat_title}"
                )
            except TelegramError:
                pass


# â”€â”€â”€ MAIN â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))

    # ÐÐ´Ð¼Ð¸Ð½Ñ‹ Ð¼ÐµÑÑÐµÐ¶ â€” ÐºÐ¾Ð¼Ð°Ð½Ð´ÑƒÑƒÐ´Ñ‹Ð½ Ð´Ð°Ñ€Ð°Ð° Ð±Ò¯Ñ€Ñ‚Ð³ÑÐ³Ð´ÑÑ… Ñ‘ÑÑ‚Ð¾Ð¹, Ð³ÑÑ…Ð´ÑÑ
    # filters-Ð°Ð°Ñ€ Ð» Ð°Ð´Ð¼Ð¸Ð½Ñ‹Ð³ ÑÐ»Ð³Ð°Ð´Ð°Ð³ Ñ‚ÑƒÐ» Ð´Ð°Ñ€Ð°Ð°Ð»Ð°Ð» Ñ…Ð°Ð¼Ð°Ð°Ð³Ò¯Ð¹; group=1-ÑÑÑ€ Ð´Ð¾Ð¾Ñˆ Ñ‚Ð°Ð²ÑŒÑ
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

    logger.info("âœ… Bot Ð°Ð¶Ð¸Ð»Ð»Ð°Ð¶ Ð±Ð°Ð¹Ð½Ð°...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=[
            "message", "edited_message", "channel_post", "edited_channel_post",
            "callback_query", "chat_member", "my_chat_member", "chat_join_request"
        ]
    )


if __name__ == '__main__':
    main()
