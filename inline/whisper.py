"""
Whisper message handler - inline bot feature for private messages
"""
import time
import uuid
from typing import Optional, Dict

from aiogram import Bot, Dispatcher, F
from aiogram.types import InlineQuery, CallbackQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from databases.database import db

bot: Optional[Bot] = None

whispers_cache: Dict[str, Dict] = {}

view_cooldowns: Dict[int, float] = {}

WHISPER_EXPIRY_HOURS = 3
WHISPER_MAX_LENGTH = 1000
WHISPER_ALERT_MAX_LENGTH = 170
VIEW_COOLDOWN_SECONDS = 5


def _cleanup_expired_whispers():
    """Remove expired whispers from cache"""
    current_time = time.time()
    expired_ids = [
        whisper_id for whisper_id, whisper_data in whispers_cache.items()
        if whisper_data['expires_at'] < current_time
    ]
    for whisper_id in expired_ids:
        del whispers_cache[whisper_id]
    return len(expired_ids)


def _cleanup_old_cooldowns():
    """Remove old cooldown entries"""
    current_time = time.time()
    expired_user_ids = [
        user_id for user_id, last_view in view_cooldowns.items()
        if current_time - last_view > VIEW_COOLDOWN_SECONDS * 2
    ]
    for user_id in expired_user_ids:
        del view_cooldowns[user_id]


def _parse_whisper_query(query: str, bot_username: str) -> Optional[tuple[str, str]]:
    """
    Parse whisper query in format: @botname message text @recipient
    
    Returns: (message_text, recipient_username) or None if invalid
    """
    if not query:
        return None
    
    query = query.strip()
    query_lower = query.lower()
    bot_username_lower = bot_username.lower()
    
    remaining = None
    
    bot_mention_with_at = f"@{bot_username_lower}"
    if query_lower.startswith(bot_mention_with_at):
        if query.startswith(f"@{bot_username}"):
            remaining = query[len(f"@{bot_username}"):].strip()
        else:
            remaining = query[len(bot_mention_with_at):].strip()
    elif query_lower.startswith(bot_username_lower):
        if query.startswith(bot_username):
            remaining = query[len(bot_username):].strip()
        else:
            remaining = query[len(bot_username_lower):].strip()
    else:
        return None
    
    if not remaining:
        return None
    
    last_at_index = remaining.rfind('@')
    
    if last_at_index == -1:
        return None
    
    recipient_part = remaining[last_at_index + 1:].strip()
    
    if not recipient_part:
        return None
    
    recipient_words = recipient_part.split()
    if recipient_words:
        recipient_username = recipient_words[0].rstrip('.,!?;:')
    else:
        recipient_username = recipient_part.rstrip('.,!?;:')
    
    if not recipient_username:
        return None
    
    message_text = remaining[:last_at_index].strip()
    
    if not message_text:
        return None
    
    return (message_text, recipient_username)


async def create_whisper(sender_id: int, recipient_username: str, message_text: str) -> Optional[str]:
    """
    Create a whisper and store it in cache
    
    Returns: whisper_id if successful, None otherwise
    """
    if len(message_text) > WHISPER_MAX_LENGTH:
        return None
    
    recipient_id = None
    recipient_username_lower = recipient_username.lower()
    
    try:
        username_variants = [recipient_username, recipient_username_lower]
        
        user_data = None
        for username_variant in username_variants:
            user_data = await db.get_user_by_username(username_variant)
            if user_data:
                break
        
        if user_data:
            recipient_id = user_data['user_id']
            if user_data.get('is_bot', False):
                return None
        else:
            if bot:
                try:
                    chat = await bot.get_chat(f"@{recipient_username}")
                    if hasattr(chat, 'is_bot') and chat.is_bot:
                        return None
                    recipient_id = chat.id
                except Exception:
                    recipient_id = None
            else:
                recipient_id = None
        
        if recipient_id and recipient_id == sender_id:
            return None
        
    except Exception:
        recipient_id = None
    
    whisper_id = str(uuid.uuid4())
    
    current_time = time.time()
    expires_at = current_time + (WHISPER_EXPIRY_HOURS * 3600)
    
    whispers_cache[whisper_id] = {
        'sender_id': sender_id,
        'recipient_id': recipient_id,
        'recipient_username': recipient_username_lower,
        'message_text': message_text,
        'created_at': current_time,
        'expires_at': expires_at
    }
    
    return whisper_id


async def get_whispers_for_user(user_id: int, username: Optional[str] = None) -> list[Dict]:
    """Get all active whispers for a user"""
    _cleanup_expired_whispers()
    
    current_time = time.time()
    user_whispers = []
    
    username_lower = username.lower() if username else None
    
    for whisper_id, whisper_data in whispers_cache.items():
        if whisper_data['expires_at'] <= current_time:
            continue
        
        recipient_id = whisper_data.get('recipient_id')
        recipient_username = whisper_data.get('recipient_username')
        
        if recipient_id == user_id:
            user_whispers.append({**whisper_data, 'whisper_id': whisper_id})
        elif recipient_id is None and username_lower and recipient_username == username_lower:
            user_whispers.append({**whisper_data, 'whisper_id': whisper_id})
    
    user_whispers.sort(key=lambda x: x['created_at'], reverse=True)
    
    return user_whispers


async def get_whisper_by_id(whisper_id: str) -> Optional[Dict]:
    """Get whisper by ID if it exists and hasn't expired"""
    _cleanup_expired_whispers()
    
    whisper = whispers_cache.get(whisper_id)
    if not whisper:
        return None
    
    if whisper['expires_at'] < time.time():
        del whispers_cache[whisper_id]
        return None
    
    return whisper


def check_view_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Check if user can view a whisper (rate limiting)
    
    Returns: (can_view, remaining_seconds)
    """
    current_time = time.time()
    
    if user_id in view_cooldowns:
        last_view = view_cooldowns[user_id]
        time_passed = current_time - last_view
        
        if time_passed < VIEW_COOLDOWN_SECONDS:
            remaining = int(VIEW_COOLDOWN_SECONDS - time_passed)
            return False, remaining
    
    view_cooldowns[user_id] = current_time
    _cleanup_old_cooldowns()
    
    return True, 0


async def inline_query_handler(inline_query: InlineQuery):
    """Handle inline queries for whisper feature"""
    if not bot:
        return
    
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        if not bot_username:
            return
        
        query = inline_query.query.strip()
        user_id = inline_query.from_user.id
        
        parsed = None
        if query and '@' in query:
            last_at_index = query.rfind('@')
            if last_at_index > 0:
                message_part = query[:last_at_index].strip()
                recipient_part = query[last_at_index + 1:].strip()
                
                if message_part and recipient_part:
                    recipient_words = recipient_part.split()
                    recipient_username = recipient_words[0].rstrip('.,!?;:') if recipient_words else recipient_part.rstrip('.,!?;:')
                    
                    if recipient_username and message_part:
                        parsed = (message_part, recipient_username)
        
        if not parsed:
            parsed = _parse_whisper_query(query, bot_username)
        
        if parsed:
            message_text, recipient_username = parsed
            
            if len(message_text) > WHISPER_MAX_LENGTH:
                await inline_query.answer(
                    results=[],
                    cache_time=1,
                    is_personal=True
                )
                return
            
            whisper_id = await create_whisper(user_id, recipient_username, message_text)
            
            if whisper_id:
                sender_username = "Неизвестный"
                try:
                    sender_data = await db.get_user(user_id)
                    if sender_data and sender_data.get('username'):
                        sender_username = f"@{sender_data['username']}"
                    elif sender_data and sender_data.get('first_name'):
                        sender_username = sender_data['first_name']
                except Exception:
                    pass
                
                keyboard = InlineKeyboardBuilder()
                keyboard.add(InlineKeyboardButton(
                    text="👁️ Просмотреть шепот",
                    callback_data=f"whisper_view_{whisper_id}"
                ))
                
                whisper_message = (
                    f"📩 <b>Прошепченное сообщение</b>\n\n"
                    f"От: {sender_username}\n"
                    f"Для: @{recipient_username}\n\n"
                    f"Нажмите кнопку ниже, чтобы просмотреть сообщение"
                )
                
                result = InlineQueryResultArticle(
                    id=whisper_id,
                    title="📩 Отправить шепот",
                    description=f"Прошепченное сообщение для @{recipient_username}",
                    input_message_content=InputTextMessageContent(
                        message_text=whisper_message,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=keyboard.as_markup()
                )
                await inline_query.answer(
                    results=[result],
                    cache_time=1,
                    is_personal=True
                )
            else:
                try:
                    username_variants = [recipient_username, recipient_username.lower()]
                    user_data = None
                    for username_variant in username_variants:
                        user_data = await db.get_user_by_username(username_variant)
                        if user_data:
                            break
                    
                    if not user_data:
                        try:
                            if bot:
                                chat = await bot.get_chat(f"@{recipient_username}")
                                if chat.type == "private" and not chat.is_bot:
                                    error_msg = f"⚠️ Не удалось отправить шепот пользователю @{recipient_username}. Проверьте правильность username."
                                else:
                                    error_msg = f"⚠️ Получатель @{recipient_username} не найден или это не приватный пользователь."
                            else:
                                error_msg = f"⚠️ Получатель @{recipient_username} не найден. Возможно вы ошиблись юзернеймом."
                        except Exception:
                            error_msg = f"⚠️ Получатель @{recipient_username} не найден. Возможно вы ошиблись юзернеймом."
                    elif user_data.get('is_bot', False):
                        error_msg = f"⚠️ Нельзя отправить шепот боту @{recipient_username}"
                    else:
                        error_msg = f"⚠️ Не удалось отправить шепот пользователю @{recipient_username}."
                except Exception:
                    error_msg = f"⚠️ Не удалось отправить шепот. Получатель @{recipient_username} не найден или недоступен."
                
                result = InlineQueryResultArticle(
                    id="error",
                    title="⚠️ Ошибка",
                    description=f"Не удалось отправить шепот @{recipient_username}",
                    input_message_content=InputTextMessageContent(
                        message_text=error_msg
                    )
                )
                await inline_query.answer(
                    results=[result],
                    cache_time=1,
                    is_personal=True
                )
        else:
            query_lower = query.lower() if query else ''
            bot_mention_variants = [
                bot_username.lower(),
                f'@{bot_username.lower()}',
                bot_username,
                f'@{bot_username}'
            ]
            
            starts_with_bot = any(query_lower.startswith(variant.lower()) for variant in bot_mention_variants)
            
            if not query or query_lower in ['', ' ']:
                help_result = InlineQueryResultArticle(
                    id="help_hint",
                    title="💡 Отправить шепот",
                    description=f"Введите: ваш текст @получатель",
                    input_message_content=InputTextMessageContent(
                        message_text=f"💡 <b>Как отправить шепот:</b>\n\nПросто введите ваш текст и username получателя:\n\n<i>ваш текст @получатель</i>\n\nПример: <i>Привет! Как дела? @username</i>\n\n📩 Шепот будет отправлен в чат с кнопкой для просмотра."
                    )
                )
                await inline_query.answer(
                    results=[help_result],
                    cache_time=1,
                    is_personal=True
                )
                return
            elif query_lower in [v.lower() for v in bot_mention_variants]:
                pass
            elif starts_with_bot:
                error_result = InlineQueryResultArticle(
                    id="parse_error",
                    title="⚠️ Ошибка формата",
                    description="Проверьте формат: @бот текст @получатель",
                    input_message_content=InputTextMessageContent(
                        message_text=f"⚠️ Неверный формат. Используйте: @{bot_username} ваш текст @получатель"
                    )
                )
                await inline_query.answer(
                    results=[error_result],
                    cache_time=1,
                    is_personal=True
                )
                return
            else:
                help_result = InlineQueryResultArticle(
                    id="help",
                    title="💡 Формат шепота",
                    description=f"Используйте: @{bot_username} ваш текст @получатель",
                    input_message_content=InputTextMessageContent(
                        message_text=f"💡 Чтобы отправить шепот, используйте формат:\n@{bot_username} ваш текст @получатель\n\nПример: @{bot_username} Привет! @username"
                    )
                )
                await inline_query.answer(
                    results=[help_result],
                    cache_time=1,
                    is_personal=True
                )
                return
            
            user_username = None
            if inline_query.from_user.username:
                user_username = inline_query.from_user.username
            else:
                try:
                    user_data = await db.get_user(user_id)
                    if user_data and user_data.get('username'):
                        user_username = user_data['username']
                except Exception:
                    pass
            
            whispers = await get_whispers_for_user(user_id, user_username)
            
            if not whispers:
                await inline_query.answer(
                    results=[],
                    cache_time=1,
                    is_personal=True
                )
                return
            
            results = []
            for whisper in whispers[:50]:
                whisper_id = whisper['whisper_id']
                sender_id = whisper['sender_id']
                
                sender_username = "Неизвестный"
                try:
                    sender_data = await db.get_user(sender_id)
                    if sender_data and sender_data.get('username'):
                        sender_username = f"@{sender_data['username']}"
                    elif sender_data and sender_data.get('first_name'):
                        sender_username = sender_data['first_name']
                except Exception:
                    pass
                
                message_preview = whisper['message_text'][:50]
                if len(whisper['message_text']) > 50:
                    message_preview += "..."
                
                expires_at = whisper['expires_at']
                current_time = time.time()
                time_remaining = expires_at - current_time
                hours_remaining = int(time_remaining / 3600)
                minutes_remaining = int((time_remaining % 3600) / 60)
                
                time_str = f"{hours_remaining}ч {minutes_remaining}м" if hours_remaining > 0 else f"{minutes_remaining}м"
                
                keyboard = InlineKeyboardBuilder()
                keyboard.add(InlineKeyboardButton(
                    text="👁️ Просмотреть шепот",
                    callback_data=f"whisper_view_{whisper_id}"
                ))
                
                result = InlineQueryResultArticle(
                    id=whisper_id,
                    title=f"📩 Шепот от {sender_username}",
                    description=f"{message_preview} (осталось: {time_str})",
                    input_message_content=InputTextMessageContent(
                        message_text="📩 У вас есть шепот. Нажмите кнопку ниже для просмотра."
                    ),
                    reply_markup=keyboard.as_markup()
                )
                results.append(result)
            
            await inline_query.answer(
                results=results,
                cache_time=1,
                is_personal=True
            )
    
    except Exception:
        try:
            await inline_query.answer(
                results=[],
                cache_time=1,
                is_personal=True
            )
        except Exception:
            pass


async def whisper_callback_handler(callback: CallbackQuery):
    """Handle callback queries for viewing whispers"""
    if not bot:
        return
    
    try:
        if not callback.data or not callback.data.startswith("whisper_view_"):
            return
        
        whisper_id = callback.data.replace("whisper_view_", "")
        user_id = callback.from_user.id
        
        can_view, remaining = check_view_cooldown(user_id)
        if not can_view:
            await callback.answer(
                f"⏳ Пожалуйста, подождите {remaining} секунд перед следующим просмотром",
                show_alert=True
            )
            return
        
        whisper = await get_whisper_by_id(whisper_id)
        
        if not whisper:
            await callback.answer(
                "⚠️ Шепот не найден или истек",
                show_alert=True
            )
            return
        
        recipient_id = whisper.get('recipient_id')
        recipient_username = whisper.get('recipient_username')
        
        is_recipient = False
        if recipient_id == user_id:
            is_recipient = True
        elif recipient_id is None and recipient_username:
            user_username = None
            if callback.from_user.username:
                user_username = callback.from_user.username.lower()
            else:
                try:
                    user_data = await db.get_user(user_id)
                    if user_data and user_data.get('username'):
                        user_username = user_data['username'].lower()
                except Exception:
                    pass
            
            if user_username and recipient_username == user_username:
                is_recipient = True
                whisper['recipient_id'] = user_id
        
        is_sender = whisper['sender_id'] == user_id
        
        if not is_recipient and not is_sender:
            await callback.answer(
                "⚠️ У вас нет доступа к этому шепоту",
                show_alert=True
            )
            return
        
        message_text = whisper['message_text']
        sender_id = whisper['sender_id']
        recipient_id = whisper.get('recipient_id')
        recipient_username_from_cache = whisper.get('recipient_username')
        
        sender_username = "Неизвестный"
        recipient_username = "Неизвестный"
        
        try:
            sender_data = await db.get_user(sender_id)
            if sender_data and sender_data.get('username'):
                sender_username = f"@{sender_data['username']}"
            elif sender_data and sender_data.get('first_name'):
                sender_username = sender_data['first_name']
        except Exception:
            pass
        
        if recipient_id:
            try:
                recipient_data = await db.get_user(recipient_id)
                if recipient_data and recipient_data.get('username'):
                    recipient_username = f"@{recipient_data['username']}"
                elif recipient_data and recipient_data.get('first_name'):
                    recipient_username = recipient_data['first_name']
            except Exception:
                pass
        elif recipient_username_from_cache:
            recipient_username = f"@{recipient_username_from_cache}"
        
        if is_sender:
            display_prefix = f"📩 Ваш шепот для {recipient_username}:\n\n"
        else:
            display_prefix = f"📩 Шепот от {sender_username}:\n\n"
        
        if len(message_text) <= WHISPER_ALERT_MAX_LENGTH:
            display_text = display_prefix + message_text
            await callback.answer(
                display_text,
                show_alert=True
            )
        else:
            if is_sender:
                display_text = f"📩 <b>Ваш шепот для {recipient_username}</b>\n\n{message_text}"
            else:
                display_text = f"📩 <b>Шепот от {sender_username}</b>\n\n{message_text}"
            try:
                chat_id = callback.message.chat.id if callback.message else None
                
                if chat_id:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=display_text,
                        parse_mode=ParseMode.HTML
                    )
                    await callback.answer(
                        "✅ Шепот отправлен в чат",
                        show_alert=False
                    )
                else:
                    await bot.send_message(
                        chat_id=user_id,
                        text=display_text,
                        parse_mode=ParseMode.HTML
                    )
                    await callback.answer(
                        "✅ Шепот отправлен в личные сообщения",
                        show_alert=False
                    )
            except Exception:
                await callback.answer(
                    "⚠️ Не удалось отправить шепот. Нужно открыть ЛС со мной.",
                    show_alert=True
                )
    
    except Exception:
        try:
            await callback.answer(
                "⚠️ Произошла ошибка при просмотре шепота",
                show_alert=True
            )
        except Exception:
            pass


def register_whisper_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Register whisper handlers"""
    global bot
    bot = bot_instance
    
    dispatcher.inline_query.register(inline_query_handler)
    
    dispatcher.callback_query.register(whisper_callback_handler, F.data.startswith("whisper_view_"))


async def cleanup_expired_whispers_task():
    """Cleanup task for expired whispers (called by scheduler)"""
    try:
        _cleanup_expired_whispers()
    except Exception:
        pass
