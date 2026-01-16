"""
Обработчики команд модерации
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from databases.database import db
from databases.moderation_db import moderation_db
from databases.reputation_db import reputation_db
from databases.raid_protection_db import raid_protection_db
from utils.permissions import get_effective_rank, check_permission
from utils.formatting import (
    parse_mute_duration, get_user_mention_html, parse_command_with_reason,
    format_mute_duration
)
from utils.error_handler import get_error_message
from utils.gifs import send_message_with_gif
from utils.constants import RANK_OWNER, RANK_NAMES
from utils.cooldowns import should_show_hint
from handlers.common import (
    parse_user_from_args, delete_message_after_delay,
    require_admin_rights, require_bot_admin_rights, send_access_denied_message,
    extract_user_from_system_message
)

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def get_rank_name(rank: int, count: int = 1) -> str:
    """Получить название ранга с учетом множественного числа"""
    return RANK_NAMES[rank][0] if count == 1 else RANK_NAMES[rank][1]


def extract_channel_from_message(message: Message) -> Optional[Dict[str, Any]]:
    """Извлечь информацию о канале из сообщения, отправленного от имени канала"""
    # Проверяем sender_chat - это означает, что сообщение отправлено от имени канала
    if message.sender_chat and message.sender_chat.type == 'channel':
        channel = message.sender_chat
        return {
            'channel_id': channel.id,
            'channel_username': getattr(channel, 'username', None),
            'channel_title': getattr(channel, 'title', None) or (f"@{channel.username}" if channel.username else f"ID{channel.id}")
        }
    
    return None


def format_channel_mention(channel_id: int, username: str = None, title: str = None) -> str:
    """Форматировать упоминание канала для сообщений"""
    if username:
        return f"@{username}"
    elif title:
        return f"<b>{title}</b>"
    else:
        return f"<b>Канал ID{channel_id}</b>"


def register_moderation_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков команд модерации"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # Регистрируем обработчики
    dp.message.register(mute_command, Command("mute"))
    dp.message.register(unmute_command, Command("unmute"))
    dp.message.register(kick_command, Command("kick"))
    dp.message.register(ban_command, Command("ban"))
    dp.message.register(unban_command, Command("unban"))
    dp.message.register(warn_command, Command("warn"))
    dp.message.register(unwarn_command, Command("unwarn"))
    dp.message.register(warns_command, Command("warns"))
    dp.message.register(ap_command, Command("ap"))
    dp.message.register(unap_command, Command("unap"))
    dp.message.register(staff_command, Command("staff"))
    dp.message.register(punishhistory_command, Command("punishhistory", "История наказаний"))
    
    # Регистрируем callback обработчики для панели истории наказаний
    dp.callback_query.register(punishhistory_page_callback, F.data.startswith("punishhistory_page_"))
    dp.callback_query.register(punishhistory_refresh_callback, F.data.startswith("punishhistory_refresh_"))
    dp.callback_query.register(punishhistory_noop_callback, F.data == "punishhistory_noop")


@require_admin_rights
async def mute_command(message: Message):
    """Команда мута пользователя"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права модератора
    can_mute = await check_permission(chat_id, user_id, 'can_mute', lambda r: r <= 4)
    if not can_mute:
        sent_message = await message.answer("🫠 Ты хочешь заставить кого-то замолчать, но власть — не то, что можно взять просто так. Молчание порождается авторитетом, а не желанием заставить замолчать. Чтобы даровать молчание, нужно самому обладать голосом в этом чате.")
        asyncio.create_task(delete_message_after_delay(sent_message, 5))
        return
    
    # Получаем ранг вызывающего для проверки иерархии
    caller_rank = await get_effective_rank(chat_id, user_id)
    
    # Парсим команду с причиной
    command_line, reason = parse_command_with_reason(message.text)
    args = command_line.split()
    
    target_user = None
    time_str = None
    
    if message.reply_to_message:
        # Проверяем, является ли это сообщением от канала
        channel_info = extract_channel_from_message(message.reply_to_message)
        if channel_info:
            await message.answer("❌ Каналы можно только забанить или разбанить. Использование мута для каналов невозможно.")
            return
        
        # Проверяем, является ли это системным сообщением
        system_user = await extract_user_from_system_message(message.reply_to_message)
        if system_user:
            # Это системное сообщение (присоединение/выход пользователя)
            if len(args) < 2:
                if await should_show_hint(chat_id, user_id):
                    await message.answer(
                        "❌ <b>Некорректный формат команды</b>\n\n"
                        "Использование:\n"
                        "• <code>/mute 10 часов</code> (при ответе на сообщение)\n"
                        "• <code>/mute @username 10 часов</code>\n\n"
                        "Можно указать причину на новой строке:\n"
                        "• <code>/mute 10 часов\nНарушение правил</code>\n\n"
                        "Примеры времени:\n"
                        "• 30 минут\n"
                        "• 2 часа\n"
                        "• 5 дней\n"
                        "• 60 секунд",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await message.answer("❌ Некорректный формат команды")
                return
            
            target_user = system_user
            time_str = ' '.join(args[1:])
        else:
            # Обычное сообщение
            if len(args) < 2:
                if await should_show_hint(chat_id, user_id):
                    await message.answer(
                        "❌ <b>Некорректный формат команды</b>\n\n"
                        "Использование:\n"
                        "• <code>/mute 10 часов</code> (при ответе на сообщение)\n"
                        "• <code>/mute @username 10 часов</code>\n\n"
                        "Можно указать причину на новой строке:\n"
                        "• <code>/mute 10 часов\nНарушение правил</code>\n\n"
                        "Примеры времени:\n"
                        "• 30 минут\n"
                        "• 2 часа\n"
                        "• 5 дней\n"
                        "• 60 секунд",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await message.answer("❌ Некорректный формат команды")
                return
            
            # Проверяем, есть ли from_user в обычном сообщении
            if not message.reply_to_message.from_user:
                await message.answer("❌ Не удалось определить пользователя из сообщения")
                return
            
            target_user = message.reply_to_message.from_user
            time_str = ' '.join(args[1:])
    else:
        # Формат: /mute @username 10 часов
        if len(args) < 3:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/mute 10 часов</code> (при ответе на сообщение)\n"
                    "• <code>/mute @username 10 часов</code>\n\n"
                    "Можно указать причину на новой строке:\n"
                    "• <code>/mute @username 10 часов\nНарушение правил</code>\n\n"
                    "Примеры времени:\n"
                    "• 30 минут\n"
                    "• 2 часа\n"
                    "• 5 дней\n"
                    "• 60 секунд",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/mute 10 часов</code> (при ответе на сообщение)\n"
                    "• <code>/mute @username 10 часов</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
        
        time_str = ' '.join(args[2:])
    
    # Парсим время
    duration_seconds = parse_mute_duration(time_str)
    if duration_seconds is None:
        await message.answer(
            "❌ <b>Некорректный формат времени</b>\n\n"
            "Примеры правильного формата:\n"
            "• 30 минут\n"
            "• 2 часа\n"
            "• 5 дней\n"
            "• 60 секунд",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Проверяем ограничения времени
    if duration_seconds <= 0:
        await message.answer("❌ Время мута должно быть больше 0")
        return
    
    max_duration = 366 * 24 * 3600
    if duration_seconds > max_duration:
        await message.answer("❌ Максимальное время мута: 366 дней")
        return
    
    # Проверяем, что не мутим самого себя
    if target_user.id == user_id:
        await message.answer("❌ Нельзя замутить самого себя")
        return
    
    # Проверяем, что целевой пользователь не является ботом
    if target_user.is_bot:
        await message.answer("❌ Нельзя замутить бота")
        return
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= 2:
        await message.answer("❌ Нельзя замутить владельца или администратора")
        return
    
    # Проверяем, что модератор может мутить этого пользователя
    if target_rank <= caller_rank:
        await message.answer("❌ Нельзя замутить пользователя с равным или выше рангом")
        return
    
    # Вычисляем время окончания мута
    mute_until_dt = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    mute_until_timestamp = int(mute_until_dt.timestamp())
    
    logger.info(f"Мутим пользователя {target_user.id} до {mute_until_dt} (timestamp: {mute_until_timestamp})")
    
    try:
        # Применяем мут
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions=types.ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            ),
            until_date=mute_until_dt
        )
        
        # Деактивируем все активные муты для этого пользователя
        active_mutes = await moderation_db.get_active_punishments(chat_id, "mute")
        for mute in active_mutes:
            if mute['user_id'] == target_user.id:
                await moderation_db.deactivate_punishment(mute['id'])
                logger.info(f"Деактивирован старый мут {mute['id']} для пользователя {target_user.id}")

        # Записываем новое наказание в базу данных модерации
        await moderation_db.add_punishment(
            chat_id=chat_id,
            user_id=target_user.id,
            moderator_id=user_id,
            punishment_type="mute",
            reason=reason,
            duration_seconds=duration_seconds,
            expiry_date=mute_until_dt.isoformat(),
            user_username=target_user.username,
            user_first_name=target_user.first_name,
            user_last_name=target_user.last_name,
            moderator_username=message.from_user.username,
            moderator_first_name=message.from_user.first_name,
            moderator_last_name=message.from_user.last_name
        )
        
        # Обновляем репутацию
        penalty = reputation_db.calculate_reputation_penalty('mute', duration_seconds)
        await reputation_db.add_recent_punishment(target_user.id, 'mute', duration_seconds)
        await reputation_db.update_reputation(target_user.id, penalty)
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Формируем сообщение с причиной
        message_text = f"🔊 Участник <b>{username_display}</b> был(а) замучен(а) на <i>{time_str}</i>\n"
        if reason:
            message_text += f"<b>Причина:</b> <i>{reason}</i>\n"
        message_text += f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
        
        await send_message_with_gif(message, message_text, "mute", parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при применении мута пользователю {target_user.id}: {e}")
        error_msg = get_error_message(e, "мута")
        await message.answer(error_msg)


async def restore_user_mutes(chat_id: int, user_id: int) -> bool:
    """
    Восстанавливает мут пользователя если он активен в базе данных.
    Используется после кика, чтобы сохранить наказание.
    
    Returns:
        True если мут был восстановлен, False если мутов не было или произошла ошибка
    """
    try:
        # Получаем активные муты для пользователя
        active_mutes = await moderation_db.get_active_punishments(chat_id, "mute")
        user_mutes = [mute for mute in active_mutes if mute['user_id'] == user_id]
        
        if not user_mutes:
            return False
        
        # Берем самый поздний мут (последний по времени окончания)
        # Обрабатываем мут с самой поздней датой окончания, если есть
        latest_mute = None
        latest_expiry = None
        
        for mute in user_mutes:
            expiry_str = mute.get('expiry_date')
            if expiry_str:
                try:
                    expiry_date = datetime.fromisoformat(expiry_str)
                    if latest_expiry is None or expiry_date > latest_expiry:
                        latest_expiry = expiry_date
                        latest_mute = mute
                except (ValueError, TypeError):
                    # Некорректная дата, пропускаем этот мут
                    continue
            elif latest_mute is None:
                # Если нашли мут без даты окончания, используем его (но продолжаем поиск лучшего)
                latest_mute = mute
        
        if latest_mute is None:
            return False
        
        # Проверяем, не истек ли мут
        if latest_mute.get('expiry_date'):
            expiry_date = datetime.fromisoformat(latest_mute['expiry_date'])
            now = datetime.now(expiry_date.tzinfo) if expiry_date.tzinfo else datetime.now()
            
            if now >= expiry_date:
                # Мут истек, деактивируем его
                await moderation_db.deactivate_punishment(latest_mute['id'])
                logger.debug(f"Мут {latest_mute['id']} истек для пользователя {user_id}, не восстанавливаем")
                return False
        
        # Восстанавливаем мут
        mute_until = datetime.fromisoformat(latest_mute['expiry_date']) if latest_mute.get('expiry_date') else None
        
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False
            ),
            until_date=mute_until
        )
        
        logger.info(f"Мут восстановлен для пользователя {user_id} в чате {chat_id} до {mute_until}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при восстановлении мута для пользователя {user_id} в чате {chat_id}: {e}")
        return False


@require_admin_rights
async def unmute_command(message: Message):
    """Команда размута пользователя"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права модератора
    can_unmute = await check_permission(chat_id, user_id, 'can_unmute', lambda r: r <= 4)
    if not can_unmute:
        if await should_show_hint(chat_id, user_id):
            await message.answer("❌ Недостаточно прав для использования размута")
        return
    
    # Парсим команду
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        if len(args) != 1:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/unmute</code> (при ответе на сообщение)\n"
                "• <code>/unmute @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Проверяем, является ли это системным сообщением
        system_user = await extract_user_from_system_message(message.reply_to_message)
        if system_user:
            target_user = system_user
        else:
            if not message.reply_to_message.from_user:
                await message.answer("❌ Не удалось определить пользователя из сообщения")
                return
            target_user = message.reply_to_message.from_user
    else:
        if len(args) != 2:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/unmute</code> (при ответе на сообщение)\n"
                "• <code>/unmute @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/unmute</code> (при ответе на сообщение)\n"
                    "• <code>/unmute @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= 2:
        await message.answer("ℹ️ Владелец и администраторы не могут быть замучены")
        return
    
    # Проверяем, действительно ли пользователь замучен
    is_muted = False
    
    # Проверяем активные муты в базе данных
    try:
        active_punishments = await moderation_db.get_active_punishments(chat_id, "mute")
        for punishment in active_punishments:
            if punishment['user_id'] == target_user.id:
                is_muted = True
                break
    except Exception as e:
        logger.warning(f"Ошибка при проверке активных мутов для пользователя {target_user.id}: {e}")
    
    # Проверяем статус пользователя в Telegram
    if not is_muted:
        try:
            chat_member = await bot.get_chat_member(chat_id, target_user.id)
            if chat_member.status == 'restricted':
                if hasattr(chat_member, 'permissions') and chat_member.permissions:
                    if not chat_member.permissions.can_send_messages:
                        is_muted = True
        except Exception as e:
            logger.warning(f"Ошибка при проверке статуса пользователя {target_user.id} в Telegram: {e}")
    
    # Если пользователь не замучен, сообщаем об этом
    if not is_muted:
        username_display = get_user_mention_html(target_user)
        await message.answer(f"ℹ️ Пользователь <b>{username_display}</b> не замучен", parse_mode=ParseMode.HTML)
        return
    
    try:
        # Снимаем мут (восстанавливаем дефолтные права чата)
        # Используем ChatPermissions() без параметров для дефолтных прав
        # Это уберет пользователя из списка исключений и вернет к стандартным правам участника
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True,
                can_manage_topics=True
            )
        )
        
        # Деактивируем активные наказания типа "mute" для этого пользователя
        try:
            active_punishments = await moderation_db.get_active_punishments(chat_id, "mute")
            for punishment in active_punishments:
                if punishment['user_id'] == target_user.id:
                    await moderation_db.deactivate_punishment(punishment['id'])
                    logger.info(f"Деактивировано наказание {punishment['id']} для пользователя {target_user.id}")
        except Exception as e:
            logger.error(f"Ошибка при деактивации наказаний для пользователя {target_user.id}: {e}")
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Философские цитаты для размута
        philosophical_quotes = [
            "🗣️ Голос - это дар, который нужно беречь и использовать мудро",
            "🔄 Второй шанс - это возможность стать лучше",
            "🌅 После тишины приходит время для слов",
            "🕊️ Свобода слова рождает понимание",
            "💬 Каждое слово имеет значение, каждое молчание - тоже",
            "🌟 Освобождение от ограничений открывает новые горизонты",
            "🦋 Как бабочка выходит из кокона, так и слова выходят из молчания",
            "🌊 Река слов снова течет свободно",
            "🎵 После паузы музыка становится еще прекраснее",
            "🌱 Из тишины рождается мудрость"
        ]
        
        quote = random.choice(philosophical_quotes)
        
        message_text = (
            f"🔊 <b>{username_display}</b> <i>освобожден(а) от тайм-аута</i>\n"
            f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>\n\n"
            f"<blockquote>{quote}</blockquote>"
        )
        
        # Отправляем сообщение в чат
        await send_message_with_gif(message, message_text, "unmute", parse_mode=ParseMode.HTML)
        
        # Отправляем уведомление пользователю
        try:
            builder = InlineKeyboardBuilder()
            
            if message.chat.username:
                chat_url = f"https://t.me/{message.chat.username}"
            else:
                chat_id_str = str(message.chat.id)
                if chat_id_str.startswith('-100'):
                    chat_id_str = chat_id_str[4:]
                chat_url = f"https://t.me/c/{chat_id_str}"
            
            builder.add(InlineKeyboardButton(
                text="💬 Открыть чат",
                url=chat_url
            ))
            
            await bot.send_message(
                target_user.id,
                f"🔊 <b>Вы были размучены</b>\n\n"
                f"В чате <b>{message.chat.title}</b> с вас сняты ограничения на отправку сообщений.",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            error_str = str(e).lower()
            # Ошибка "bot can't initiate conversation" - это нормально, пользователь не писал боту или заблокировал его
            if "can't initiate conversation" in error_str or "forbidden" in error_str:
                logger.debug(f"Не удалось отправить уведомление пользователю {target_user.id}: пользователь не писал боту или заблокировал его")
            else:
                logger.error(f"Не удалось отправить уведомление пользователю {target_user.id}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при снятии мута пользователю {target_user.id}: {e}")
        error_msg = get_error_message(e, "снятия мута")
        await message.answer(error_msg)


@require_admin_rights
async def kick_command(message: Message):
    """Команда кика пользователя из чата"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем, не пытаются ли кикнуть канал
    if message.reply_to_message:
        channel_info = extract_channel_from_message(message.reply_to_message)
        if channel_info:
            await message.answer("❌ Каналы можно только забанить или разбанить. Использование кика для каналов невозможно.")
            return
    
    # Проверяем права - только старшие модераторы и выше могут кикать
    can_kick = await check_permission(chat_id, user_id, 'can_kick', lambda r: r <= 3)
    if not can_kick:
        msg = await message.answer("😑 Куда мы лезем?")
        asyncio.create_task(delete_message_after_delay(msg, 10))
        return
    
    # Парсим команду с причиной
    command_line, reason = parse_command_with_reason(message.text)
    args = command_line.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Проверяем, не пытаются ли кикнуть канал
        channel_info = extract_channel_from_message(message.reply_to_message)
        if channel_info:
            await message.answer("❌ Каналы можно только забанить или разбанить. Использование кика для каналов невозможно.")
            return
        
        if len(args) != 1:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/kick @username</code>\n"
                    "• <code>/kick</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        # Проверяем, является ли это системным сообщением
        system_user = await extract_user_from_system_message(message.reply_to_message)
        if system_user:
            target_user = system_user
        else:
            if not message.reply_to_message.from_user:
                await message.answer("❌ Не удалось определить пользователя из сообщения")
                return
            target_user = message.reply_to_message.from_user
    else:
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/kick @username</code>\n"
                    "• <code>/kick</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/kick</code> (при ответе на сообщение)\n"
                    "• <code>/kick @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    # Проверки
    if target_user.id == bot.id:
        await message.answer("😐 Себя кикать нельзя")
        return
    
    if target_user.id == user_id:
        await message.answer("😐 Себя кикать нельзя")
        return
    
    # Проверяем ранг целевого пользователя
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= 2:
        await message.answer("😑 Нельзя кикнуть владельца или администратора")
        return
    
    try:
        # Проверяем, есть ли активные муты у пользователя (чтобы сохранить их)
        active_mutes = await moderation_db.get_active_punishments(chat_id, "mute")
        has_active_mutes = any(mute['user_id'] == target_user.id for mute in active_mutes)
        
        # Добавляем в черный список и сразу удаляем (кик)
        await bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id)
        
        # Разбаниваем пользователя, чтобы он мог вернуться в чат
        await bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
        
        # Восстанавливаем мут если он был активен (муты не удаляются из БД при кике)
        if has_active_mutes:
            await restore_user_mutes(chat_id, target_user.id)
        
        # Сохраняем кик в базу данных
        await moderation_db.add_punishment(
            chat_id=chat_id,
            user_id=target_user.id,
            moderator_id=user_id,
            punishment_type="kick",
            reason=reason,
            duration_seconds=None,
            expiry_date=None,
            user_username=target_user.username,
            user_first_name=target_user.first_name,
            user_last_name=target_user.last_name,
            moderator_username=message.from_user.username,
            moderator_first_name=message.from_user.first_name,
            moderator_last_name=message.from_user.last_name
        )
        
        # Обновляем репутацию
        penalty = reputation_db.calculate_reputation_penalty('kick')
        await reputation_db.add_recent_punishment(target_user.id, 'kick')
        await reputation_db.update_reputation(target_user.id, penalty)
        
        # Формируем имя пользователя для сообщения
        username_display = get_user_mention_html(target_user)
        
        # Формируем сообщение с причиной
        message_text = f"💨 Участник <b>{username_display}</b> был(а) исключен(а) из чата\n"
        if reason:
            message_text += f"<b>Причина:</b> <i>{reason}</i>\n"
        message_text += f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
        
        await send_message_with_gif(message, message_text, "kick", parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при кике пользователя {target_user.id}: {e}")
        error_msg = get_error_message(e, "исключения")
        await message.answer(error_msg)


@require_admin_rights
async def ban_command(message: Message):
    """Команда бана пользователя"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только старшие модераторы и выше
    can_ban = await check_permission(chat_id, user_id, 'can_ban', lambda r: r <= 3)
    if not can_ban:
        msg = await message.answer("😑 Куда мы лезем?")
        asyncio.create_task(delete_message_after_delay(msg, 10))
        return
    
    # Получаем ранг вызывающего для проверки иерархии
    caller_rank = await get_effective_rank(chat_id, user_id)
    
    # Парсим команду с причиной
    command_line, reason = parse_command_with_reason(message.text)
    args = command_line.split()
    
    target_user = None
    time_str = None
    duration_seconds = None
    
    if message.reply_to_message:
        # Проверяем, является ли это сообщением от канала
        channel_info = extract_channel_from_message(message.reply_to_message)
        if channel_info:
            # Это канал - обрабатываем отдельно
            if len(args) == 1:
                time_str = "навсегда"
                duration_seconds = None
            else:
                time_str = " ".join(args[1:])
                duration_seconds = parse_mute_duration(time_str)
                if duration_seconds is None:
                    await message.answer(
                        "❌ <b>Некорректный формат времени</b>\n\n"
                        "Примеры правильного формата:\n"
                        "• 30 минут\n"
                        "• 2 часа\n"
                        "• 5 дней\n"
                        "• 60 секунд",
                        parse_mode=ParseMode.HTML
                    )
                    return
            
            # Для каналов временный бан не поддерживается - баним навсегда
            time_warning = ""
            if duration_seconds:
                time_warning = "\n\n⚠️ <i>Примечание: Временный бан для каналов не поддерживается. Канал забанен навсегда.</i>"
            
            try:
                # Для каналов используем ban_chat_sender_chat
                await bot.ban_chat_sender_chat(
                    chat_id=chat_id,
                    sender_chat_id=channel_info['channel_id']
                )
                
                # Сохраняем только в punishments для истории (чтобы знать кто и когда забанил)
                await moderation_db.add_punishment(
                    chat_id=chat_id,
                    user_id=None,
                    moderator_id=user_id,
                    punishment_type="ban",
                    reason=reason,
                    duration_seconds=None,  # Каналы всегда баним навсегда
                    expiry_date=None,
                    user_username=channel_info['channel_username'],
                    user_first_name=channel_info['channel_title'],
                    user_last_name=None,
                    moderator_username=message.from_user.username,
                    moderator_first_name=message.from_user.first_name,
                    moderator_last_name=message.from_user.last_name,
                    channel_id=channel_info['channel_id']
                )
                
                channel_display = format_channel_mention(
                    channel_info['channel_id'],
                    channel_info['channel_username'],
                    channel_info['channel_title']
                )
                
                message_text = f"🚫 Канал {channel_display} был забанен навсегда{time_warning}\n"
                
                if reason:
                    message_text += f"<b>Причина:</b> <i>{reason}</i>\n"
                message_text += f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
                
                await send_message_with_gif(message, message_text, "ban", parse_mode=ParseMode.HTML)
                
            except Exception as e:
                logger.error(f"Ошибка при бане канала {channel_info['channel_id']}: {e}")
                error_msg = get_error_message(e, "бана канала")
                await message.answer(error_msg)
            
            return
        
        # Проверяем, является ли это системным сообщением
        system_user = await extract_user_from_system_message(message.reply_to_message)
        if system_user:
            # Это системное сообщение
            if len(args) == 1:
                time_str = "навсегда"
                duration_seconds = None
            else:
                time_str = " ".join(args[1:])
                duration_seconds = parse_mute_duration(time_str)
                if duration_seconds is None:
                    await message.answer(
                        "❌ <b>Некорректный формат времени</b>\n\n"
                        "Примеры правильного формата:\n"
                        "• 30 минут\n"
                        "• 2 часа\n"
                        "• 5 дней\n"
                        "• 60 секунд",
                        parse_mode=ParseMode.HTML
                    )
                    return
            
            target_user = system_user
        else:
            # Обычное сообщение
            if len(args) == 1:
                time_str = "навсегда"
                duration_seconds = None
            else:
                time_str = " ".join(args[1:])
                duration_seconds = parse_mute_duration(time_str)
                if duration_seconds is None:
                    await message.answer("❌ Некорректный формат времени")
                    return
            
            if not message.reply_to_message.from_user:
                await message.answer("❌ Не удалось определить пользователя из сообщения")
                return
            
            target_user = message.reply_to_message.from_user
    else:
        if len(args) < 2:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/ban</code> - бан навсегда (при ответе)\n"
                "• <code>/ban 1 час</code> - временный бан (при ответе)\n"
                "• <code>/ban @username</code> - бан навсегда\n"
                "• <code>/ban @username 1 час</code> - временный бан",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            await message.answer(
                "❌ <b>Пользователь не найден</b>\n\n"
                "Использование:\n"
                "• <code>/ban</code> - бан навсегда (при ответе)\n"
                "• <code>/ban @username</code> или упоминание - бан навсегда",
                parse_mode=ParseMode.HTML
            )
            return
        
        if len(args) == 2:
            time_str = "навсегда"
            duration_seconds = None
        else:
            time_str = " ".join(args[2:])
            duration_seconds = parse_mute_duration(time_str)
            if duration_seconds is None:
                await message.answer("❌ Некорректный формат времени")
                return
    
    # Проверки
    if target_user.is_bot:
        await message.answer("❌ Нельзя забанить бота")
        return
    
    if target_user.id == user_id:
        await message.answer("❌ Нельзя забанить самого себя")
        return
    
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= caller_rank:
        await message.answer("❌ Нельзя забанить пользователя с равным или более высоким рангом")
        return
    
    try:
        ban_until = None
        if duration_seconds:
            ban_until = datetime.now() + timedelta(seconds=duration_seconds)
        
        await bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            until_date=ban_until
        )
        
        await moderation_db.add_punishment(
            chat_id=chat_id,
            user_id=target_user.id,
            moderator_id=user_id,
            punishment_type="ban",
            reason=reason,
            duration_seconds=duration_seconds,
            expiry_date=ban_until.isoformat() if ban_until else None,
            user_username=target_user.username,
            user_first_name=target_user.first_name,
            user_last_name=target_user.last_name,
            moderator_username=message.from_user.username,
            moderator_first_name=message.from_user.first_name,
            moderator_last_name=message.from_user.last_name
        )
        
        penalty = reputation_db.calculate_reputation_penalty('ban', duration_seconds)
        await reputation_db.add_recent_punishment(target_user.id, 'ban', duration_seconds)
        await reputation_db.update_reputation(target_user.id, penalty)
        
        username_display = get_user_mention_html(target_user)
        
        if duration_seconds:
            formatted_time = format_mute_duration(duration_seconds)
            message_text = f"🚫 Участник <b>{username_display}</b> был(а) забанен(а) на <i>{formatted_time}</i>\n"
        else:
            message_text = f"🚫 Участник <b>{username_display}</b> был(а) забанен(а) навсегда\n"
        
        if reason:
            message_text += f"<b>Причина:</b> <i>{reason}</i>\n"
        message_text += f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
        
        await send_message_with_gif(message, message_text, "ban", parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при бане пользователя {target_user.id}: {e}")
        error_msg = get_error_message(e, "бана")
        await message.answer(error_msg)


@require_admin_rights
async def unban_command(message: Message):
    """Команда разбана пользователя"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    can_unban = await check_permission(chat_id, user_id, 'can_unban', lambda r: r <= 3)
    if not can_unban:
        msg = await message.answer("😑 Куда мы лезем?")
        asyncio.create_task(delete_message_after_delay(msg, 10))
        return
    
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        # Проверяем, является ли это сообщением от канала
        channel_info = extract_channel_from_message(message.reply_to_message)
        if channel_info:
            # Это канал - разбаниваем его
            if len(args) != 1:
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unban</code> (при ответе на сообщение от канала)",
                    parse_mode=ParseMode.HTML
                )
                return
            
            try:
                # Для каналов используем unban_chat_sender_chat
                # Просто разбаниваем через API, не проверяем БД
                await bot.unban_chat_sender_chat(
                    chat_id=chat_id,
                    sender_chat_id=channel_info['channel_id']
                )
                
                # Деактивируем наказания в punishments (для истории)
                active_bans = await moderation_db.get_active_punishments(chat_id, "ban")
                for ban in active_bans:
                    ban_channel_id = ban.get('channel_id')
                    ban_user_id = ban.get('user_id')
                    if ban_channel_id == channel_info['channel_id'] or (ban_user_id == channel_info['channel_id'] and ban_user_id < 0):
                        await moderation_db.deactivate_punishment(ban['id'])
                
                channel_display = format_channel_mention(
                    channel_info['channel_id'],
                    channel_info['channel_username'],
                    channel_info['channel_title']
                )
                
                message_text = (
                    f"✅ Канал {channel_display} был разбанен\n"
                    f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
                )
                
                await send_message_with_gif(message, message_text, "unban", parse_mode=ParseMode.HTML)
                
            except Exception as e:
                logger.error(f"Ошибка при разбане канала {channel_info['channel_id']}: {e}")
                error_msg = get_error_message(e, "разбана канала")
                await message.answer(error_msg)
            
            return
        
        if len(args) != 1:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/unban</code> (при ответе на сообщение)\n"
                "• <code>/unban @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Проверяем, является ли это системным сообщением
        system_user = await extract_user_from_system_message(message.reply_to_message)
        if system_user:
            target_user = system_user
        else:
            if not message.reply_to_message.from_user:
                await message.answer("❌ Не удалось определить пользователя из сообщения")
                return
            target_user = message.reply_to_message.from_user
    else:
        if len(args) != 2:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/unban</code> (при ответе на сообщение)\n"
                "• <code>/unban @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/unban</code> (при ответе на сообщение)\n"
                    "• <code>/unban @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    if target_user.is_bot:
        await message.answer("❌ Нельзя разбанить бота")
        return
    
    if target_user.id == user_id:
        await message.answer("❌ Нельзя разбанить самого себя")
        return
    
    # Проверяем, действительно ли пользователь забанен
    is_banned = False
    
    # Проверяем активные баны в базе данных
    try:
        active_punishments = await moderation_db.get_active_punishments(chat_id, "ban")
        for punishment in active_punishments:
            if punishment['user_id'] == target_user.id:
                is_banned = True
                break
    except Exception as e:
        logger.warning(f"Ошибка при проверке активных банов для пользователя {target_user.id}: {e}")
    
    # Проверяем статус пользователя в Telegram
    if not is_banned:
        try:
            chat_member = await bot.get_chat_member(chat_id, target_user.id)
            if chat_member.status == 'kicked':
                is_banned = True
        except Exception as e:
            error_str = str(e).lower()
            # Если пользователь не найден в чате, возможно он забанен
            # Попробуем выполнить unban - если пользователь не забанен, получим ошибку
            if "user not found" in error_str or "chat not found" in error_str:
                # Пользователь может быть забанен, но мы не можем проверить через get_chat_member
                # Попробуем выполнить unban и посмотрим на результат
                pass
            else:
                logger.warning(f"Ошибка при проверке статуса пользователя {target_user.id} в Telegram: {e}")
    
    # Если пользователь не забанен, сообщаем об этом
    if not is_banned:
        username_display = get_user_mention_html(target_user)
        await message.answer(f"ℹ️ Пользователь <b>{username_display}</b> не забанен", parse_mode=ParseMode.HTML)
        return
    
    try:
        await bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
        
        active_bans = await moderation_db.get_active_punishments(chat_id, "ban")
        for ban in active_bans:
            if ban['user_id'] == target_user.id:
                await moderation_db.deactivate_punishment(ban['id'])
        
        username_display = get_user_mention_html(target_user)
        
        philosophical_quotes = [
            "🌅 Каждому рассвету предшествует ночь, каждому прощению - ошибка",
            "🌊 Река находит путь к океану, даже если на пути есть камни",
            "🕊️ Птица, которая упала, может снова взлететь",
            "🌱 Из самого темного семени может вырасти самый яркий цветок",
            "🌙 Луна светит даже после самой темной ночи",
            "🍃 Новый лист может вырасти на том же дереве",
            "🌌 Звезды не исчезают навсегда, они просто скрываются за облаками"
        ]
        
        quote = random.choice(philosophical_quotes)
        
        message_text = (
            f"✅ <b>{username_display}</b> <i>был(а) разбанен(а)</i>\n"
            f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>\n\n"
            f"<blockquote>{quote}</blockquote>"
        )
        
        # Проверяем настройку silent mute
        settings = await raid_protection_db.get_settings(chat_id)
        mute_silent = settings.get('mute_silent', False)
        
        # Отправляем сообщение в чат только если silent mode выключен
        if not mute_silent:
            await send_message_with_gif(message, message_text, "unban", parse_mode=ParseMode.HTML)
        
        # Отправляем уведомление пользователю
        try:
            builder = InlineKeyboardBuilder()
            
            if message.chat.username:
                chat_url = f"https://t.me/{message.chat.username}"
            else:
                chat_id_str = str(message.chat.id)
                if chat_id_str.startswith('-100'):
                    chat_id_str = chat_id_str[4:]
                chat_url = f"https://t.me/c/{chat_id_str}"
            
            builder.add(InlineKeyboardButton(
                text="💬 Открыть чат",
                url=chat_url
            ))
            
            await bot.send_message(
                target_user.id,
                f"✅ <b>Вы были разбанены</b>\n\n"
                f"В чате <b>{message.chat.title}</b> с вас сняты ограничения на участие в группе.",
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            error_str = str(e).lower()
            # Ошибка "bot can't initiate conversation" - пользователь не писал боту или заблокировал его
            if "can't initiate conversation" in error_str or "forbidden" in error_str:
                logger.debug(f"Не удалось отправить уведомление пользователю {target_user.id}: пользователь не писал боту или заблокировал его")
            else:
                logger.error(f"Ошибка при отправке уведомления пользователю {target_user.id}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при разбане пользователя {target_user.id}: {e}")
        error_msg = get_error_message(e, "разбана")
        await message.answer(error_msg)


@require_admin_rights
async def warn_command(message: Message):
    """Команда выдачи предупреждения пользователю"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    can_warn = await check_permission(chat_id, user_id, 'can_warn', lambda r: r <= 4)
    if not can_warn:
        msg = await message.answer("😑 Куда мы лезем?")
        asyncio.create_task(delete_message_after_delay(msg, 10))
        return
    
    caller_rank = await get_effective_rank(chat_id, user_id)
    
    command_line, reason = parse_command_with_reason(message.text)
    args = command_line.split()
    
    target_user = None
    
    if message.reply_to_message:
        if len(args) != 1:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/warn</code> (при ответе на сообщение)\n"
                    "• <code>/warn @username</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        # Проверяем, является ли это системным сообщением
        system_user = await extract_user_from_system_message(message.reply_to_message)
        if system_user:
            target_user = system_user
        else:
            if not message.reply_to_message.from_user:
                await message.answer("❌ Не удалось определить пользователя из сообщения")
                return
            target_user = message.reply_to_message.from_user
    else:
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/warn</code> (при ответе на сообщение)\n"
                    "• <code>/warn @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/warn</code> (при ответе на сообщение)\n"
                    "• <code>/warn @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    if target_user.is_bot:
        await message.answer("❌ Нельзя выдать предупреждение боту")
        return
    
    if target_user.id == user_id:
        await message.answer("❌ Нельзя выдать предупреждение самому себе")
        return
    
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= caller_rank:
        await message.answer("❌ Нельзя выдать предупреждение пользователю с равным или более высоким рангом")
        return
    
    try:
        await moderation_db.add_warn(
            chat_id=chat_id,
            user_id=target_user.id,
            moderator_id=user_id,
            reason=reason,
            user_username=target_user.username,
            user_first_name=target_user.first_name,
            user_last_name=target_user.last_name,
            moderator_username=message.from_user.username,
            moderator_first_name=message.from_user.first_name,
            moderator_last_name=message.from_user.last_name
        )
        
        penalty = reputation_db.calculate_reputation_penalty('warn')
        await reputation_db.add_recent_punishment(target_user.id, 'warn')
        await reputation_db.update_reputation(target_user.id, penalty)
        
        warn_count = await moderation_db.get_user_warn_count(chat_id, target_user.id)
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        warn_limit = warn_settings['warn_limit']
        
        username_display = get_user_mention_html(target_user)
        
        if warn_count >= warn_limit:
            punishment_type = warn_settings['punishment_type']
            
            if punishment_type == 'kick':
                # Проверяем, есть ли активные муты у пользователя (чтобы сохранить их)
                active_mutes = await moderation_db.get_active_punishments(chat_id, "mute")
                has_active_mutes = any(mute['user_id'] == target_user.id for mute in active_mutes)
                
                await bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id)
                await bot.unban_chat_member(chat_id=chat_id, user_id=target_user.id)
                
                # Восстанавливаем мут если он был активен (муты не удаляются из БД при кике)
                if has_active_mutes:
                    await restore_user_mutes(chat_id, target_user.id)
                
                penalty = reputation_db.calculate_reputation_penalty('kick')
                await reputation_db.add_recent_punishment(target_user.id, 'kick')
                await reputation_db.update_reputation(target_user.id, penalty)
                
                await moderation_db.clear_user_warns(chat_id, target_user.id)
                
                message_text = (
                    f"🚫 Участник <b>{username_display}</b> достиг(ла) лимита предупреждений ({warn_limit}/{warn_limit})\n"
                    f"💨 Участник был(а) исключен(а) из чата\n"
                    f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
                )
                await send_message_with_gif(message, message_text, "kick", parse_mode=ParseMode.HTML)
                
            elif punishment_type == 'mute':
                mute_duration = warn_settings['mute_duration'] or 3600
                mute_until = datetime.now() + timedelta(seconds=mute_duration)
                
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=target_user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_polls=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                        can_change_info=False,
                        can_invite_users=False,
                        can_pin_messages=False
                    ),
                    until_date=mute_until
                )
                
                await moderation_db.add_punishment(
                    chat_id=chat_id,
                    user_id=target_user.id,
                    moderator_id=user_id,
                    punishment_type="mute",
                    reason="Достигнут лимит предупреждений",
                    duration_seconds=mute_duration,
                    expiry_date=mute_until.isoformat(),
                    user_username=target_user.username,
                    user_first_name=target_user.first_name,
                    user_last_name=target_user.last_name,
                    moderator_username=message.from_user.username,
                    moderator_first_name=message.from_user.first_name,
                    moderator_last_name=message.from_user.last_name
                )
                
                await moderation_db.clear_user_warns(chat_id, target_user.id)
                
                time_str = format_mute_duration(mute_duration)
                
                message_text = (
                    f"🚫 Участник <b>{username_display}</b> достиг(ла) лимита предупреждений ({warn_limit}/{warn_limit})\n"
                    f"🔇 Участник был(а) замучен(а) на <i>{time_str}</i>\n"
                    f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
                )
                await send_message_with_gif(message, message_text, "mute", parse_mode=ParseMode.HTML)
        else:
            message_text = f"⚠️ Участник <b>{username_display}</b> получил(а) предупреждение ({warn_count}/{warn_limit})\n"
            if reason:
                message_text += f"<b>Причина:</b> <i>{reason}</i>\n"
            message_text += f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>"
            
            await send_message_with_gif(message, message_text, "warn", parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при выдаче предупреждения пользователю {target_user.id}: {e}")
        error_msg = get_error_message(e, "выдачи предупреждения")
        await message.answer(error_msg)


@require_admin_rights
async def unwarn_command(message: Message):
    """Команда снятия предупреждения пользователю"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    can_unwarn = await check_permission(chat_id, user_id, 'can_unwarn', lambda r: r <= 4)
    if not can_unwarn:
        await send_access_denied_message(message, chat_id, user_id)
        return
    
    caller_rank = await get_effective_rank(chat_id, user_id)
    
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        if len(args) != 1:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unwarn</code> (при ответе на сообщение)\n"
                    "• <code>/unwarn @username</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        # Проверяем, является ли это системным сообщением
        system_user = await extract_user_from_system_message(message.reply_to_message)
        if system_user:
            target_user = system_user
        else:
            if not message.reply_to_message.from_user:
                await message.answer("❌ Не удалось определить пользователя из сообщения")
                return
            target_user = message.reply_to_message.from_user
    else:
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unwarn</code> (при ответе на сообщение)\n"
                    "• <code>/unwarn @username</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/unwarn</code> (при ответе на сообщение)\n"
                    "• <code>/unwarn @username</code> или упоминание пользователя",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    if target_user.is_bot:
        await message.answer("❌ Нельзя снять предупреждение боту")
        return
    
    if target_user.id == user_id:
        await message.answer("❌ Нельзя снять предупреждение самому себе")
        return
    
    target_rank = await get_effective_rank(chat_id, target_user.id)
    if target_rank <= caller_rank:
        await message.answer("❌ Нельзя снять предупреждение пользователю с равным или более высоким рангом")
        return
    
    try:
        warn_count = await moderation_db.get_user_warn_count(chat_id, target_user.id)
        if warn_count == 0:
            await message.answer("❌ У пользователя нет активных предупреждений")
            return
        
        success = await moderation_db.remove_warn(chat_id, target_user.id)
        if not success:
            error_msg = get_error_message(Exception("Failed to remove warn"), "снятия предупреждения")
            await message.answer(error_msg)
            return
        
        new_warn_count = await moderation_db.get_user_warn_count(chat_id, target_user.id)
        
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        warn_limit = warn_settings['warn_limit']
        
        username_display = get_user_mention_html(target_user)
        
        await message.answer(
            f"✅ У участника(а) <b>{username_display}</b> снято предупреждение ({new_warn_count}/{warn_limit})\n"
            f"<b>Модератор:</b> <i>{message.from_user.first_name or message.from_user.username or 'Неизвестно'}</i>",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка при снятии предупреждения пользователю {target_user.id}: {e}")
        error_msg = get_error_message(e, "снятия предупреждения")
        await message.answer(error_msg)


@require_admin_rights
async def warns_command(message: Message):
    """Команда просмотра предупреждений пользователя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        if len(args) != 1:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/warns</code> (при ответе на сообщение)\n"
                "• <code>/warns @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user = message.reply_to_message.from_user
    else:
        if len(args) != 2:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/warns</code> (при ответе на сообщение)\n"
                "• <code>/warns @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            await message.answer(
                "❌ <b>Пользователь не найден</b>\n\n"
                "Использование:\n"
                "• <code>/warns</code> (при ответе на сообщение)\n"
                "• <code>/warns @username</code> или упоминание пользователя",
                parse_mode=ParseMode.HTML
            )
            return
    
    try:
        active_warns = await moderation_db.get_user_warns(chat_id, target_user.id, active_only=True)
        all_warns = await moderation_db.get_user_warns(chat_id, target_user.id, active_only=False)
        
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        warn_limit = warn_settings['warn_limit']
        
        username_display = get_user_mention_html(target_user)
        
        warn_count = len(active_warns)
        message_text = f"📊 <b>Предупреждения участника {username_display}:</b> {warn_count}/{warn_limit}\n\n"
        
        if all_warns:
            message_text += "<b>История предупреждений:</b>\n"
            for i, warn in enumerate(all_warns, 1):
                try:
                    warn_date = datetime.fromisoformat(warn['warn_date'])
                    date_str = warn_date.strftime("%d.%m.%Y %H:%M")
                except:
                    date_str = warn['warn_date']
                
                moderator_name = warn['moderator_first_name'] or warn['moderator_username'] or "Неизвестно"
                status = "✅" if warn['is_active'] else "❌"
                
                message_text += f"{i}. {status} {date_str}\n"
                if warn.get('reason'):
                    message_text += f"   Причина: {warn['reason']}\n"
                message_text += f"   Модератор: {moderator_name}\n"
        else:
            message_text += "История предупреждений пуста"
        
        await message.answer(message_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при получении предупреждений пользователя {target_user.id}: {e}")
        error_msg = get_error_message(e, "получения предупреждений")
        await message.answer(error_msg)


@require_admin_rights
async def ap_command(message: Message):
    """Команда назначения ранга модератора"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только владелец/администраторы Telegram могут назначать
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status not in ['creator', 'administrator']:
            msg = await message.answer("😑 Куда мы лезем?")
            asyncio.create_task(delete_message_after_delay(msg, 10))
            return
    except Exception as e:
        logger.error(f"Ошибка при проверке прав для команды /ap: {e}")
        error_msg = get_error_message(e, "проверки прав")
        await message.answer(error_msg)
        return
    
    args = message.text.split()
    
    target_user = None
    rank = None
    
    if message.reply_to_message:
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/ap @username 3</code>\n"
                    "• <code>/ap 3</code> (при ответе на сообщение)\n\n"
                    "Ранги: 1-Совладелец, 2-Администратор, 3-Старший модератор, 4-Младший модератор",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        try:
            rank = int(args[1])
            target_user = message.reply_to_message.from_user
        except ValueError:
            await message.answer("❌ Ранг должен быть числом от 1 до 4")
            return
    else:
        if len(args) != 3:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/ap @username 3</code>\n"
                    "• <code>/ap 3</code> (при ответе на сообщение)\n\n"
                    "Ранги: 1-Совладелец, 2-Администратор, 3-Старший модератор, 4-Младший модератор",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        try:
            rank = int(args[2])
        except ValueError:
            await message.answer("❌ Ранг должен быть числом от 1 до 4")
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/ap @username 3</code> или упоминание пользователя\n"
                    "• <code>/ap 3</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    if rank < 1 or rank > 4:
        await message.answer("❌ Ранг должен быть от 1 до 4")
        return
    
    # Проверяем права на назначение ранга 1 (Co-owner) - только Telegram creator может назначить
    if rank == 1:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status != 'creator':
                msg = await message.answer("❌ Только владелец чата может назначить совладельца")
                asyncio.create_task(delete_message_after_delay(msg, 5))
                return
        except Exception as e:
            logger.error(f"Ошибка при проверке прав для назначения ранга 1: {e}")
            error_msg = get_error_message(e, "проверки прав")
            await message.answer(error_msg)
            return
    
    # Проверяем права на назначение конкретного ранга через систему прав бота
    permission_map = {
        4: 'can_assign_rank_4',
        3: 'can_assign_rank_3',
        2: 'can_assign_rank_2'
    }
    
    if rank in permission_map:
        permission_type = permission_map[rank]
        can_assign = await check_permission(chat_id, user_id, permission_type, lambda r: r <= 2)
        if not can_assign:
            rank_name = get_rank_name(rank)
            msg = await message.answer(f"❌ У вас нет прав на назначение ранга: {rank_name}")
            asyncio.create_task(delete_message_after_delay(msg, 5))
            return
    
    if target_user.id == user_id:
        await message.answer("❌ Нельзя назначить ранг самому себе")
        return
    
    if target_user.is_bot:
        await message.answer("❌ Нельзя назначить ранг боту")
        return
    
    await db.add_user(
        user_id=target_user.id,
        username=target_user.username,
        first_name=target_user.first_name,
        last_name=target_user.last_name,
        is_bot=target_user.is_bot
    )
    
    success = await db.assign_moderator(chat_id, target_user.id, rank, user_id)
    
    if success:
        # Для ранга 1 показываем "Совладелец" вместо "Владелец"
        if rank == 1:
            rank_name = "Совладелец"
        else:
            rank_name = get_rank_name(rank)
        username_display = get_user_mention_html(target_user)
        
        await message.answer(
            f"✅ <b>{username_display}</b> назначен на должность: <b>{rank_name}</b>",
            parse_mode=ParseMode.HTML
        )
    else:
        error_msg = get_error_message(Exception("Failed to assign rank"), "назначения ранга")
        await message.answer(error_msg)


@require_admin_rights
async def unap_command(message: Message):
    """Команда снятия ранга модератора"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права - только администраторы Telegram могут снимать
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status not in ['creator', 'administrator']:
            if await should_show_hint(chat_id, user_id):
                await message.answer("❌ Недостаточно прав для снятия модераторов")
            return
    except Exception as e:
        logger.error(f"Ошибка при проверке прав для команды /unap: {e}")
        error_msg = get_error_message(e, "проверки прав")
        await message.answer(error_msg)
        return
    
    # Проверяем права на снятие рангов через систему прав бота
    can_remove_rank = await check_permission(chat_id, user_id, 'can_remove_rank', lambda r: r <= 2)
    if not can_remove_rank:
        msg = await message.answer("❌ У вас нет прав на снятие рангов модераторов")
        asyncio.create_task(delete_message_after_delay(msg, 5))
        return
    
    args = message.text.split()
    
    target_user = None
    
    if message.reply_to_message:
        if len(args) != 1:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unap @username</code>\n"
                    "• <code>/unap</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = message.reply_to_message.from_user
    else:
        if len(args) != 2:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Некорректный формат команды</b>\n\n"
                    "Использование:\n"
                    "• <code>/unap @username</code>\n"
                    "• <code>/unap</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Некорректный формат команды")
            return
        
        target_user = await parse_user_from_args(message, args, 1)
        if not target_user:
            if await should_show_hint(chat_id, user_id):
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/unap @username</code> или упоминание пользователя\n"
                    "• <code>/unap</code> (при ответе на сообщение)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.answer("❌ Пользователь не найден")
            return
    
    if target_user.id == user_id:
        await message.answer("❌ Нельзя снять ранг самому себе")
        return
    
    current_rank = await db.get_user_rank(chat_id, target_user.id)
    if current_rank is None:
        username_display = get_user_mention_html(target_user)
        await message.answer(f"❌ <b>{username_display}</b> не является модератором", parse_mode=ParseMode.HTML)
        return
    
    success = await db.remove_moderator(chat_id, target_user.id)
    
    if success:
        username_display = get_user_mention_html(target_user)
        
        await message.answer(
            f"✅ <b>{username_display}</b> снят с должности",
            parse_mode=ParseMode.HTML
        )
    else:
        error_msg = get_error_message(Exception("Failed to remove rank"), "снятия ранга")
        await message.answer(error_msg)


@require_admin_rights
async def staff_command(message: Message):
    """Команда отображения списка модераторов"""
    # Проверка на спам командами выполняется в middleware
    chat_id = message.chat.id
    
    # Получаем всех модераторов чата из БД
    moderators = await db.get_chat_moderators(chat_id)
    
    # Группируем модераторов по рангам
    ranks = {}
    owner_users = []  # Telegram creator
    co_owners = []  # Rank 1 from DB (Co-owners)
    
    # Получаем Telegram creator
    creator_id = None
    try:
        chat_admins = await bot.get_chat_administrators(chat_id)
        for admin in chat_admins:
            if admin.status == 'creator':
                user = admin.user
                if not user.is_bot:
                    creator_id = user.id
                    owner_users.append({
                        'user_id': user.id,
                        'username': user.username,
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'rank': RANK_OWNER
                    })
                break
    except Exception as e:
        logger.error(f"Ошибка при получении владельца чата {chat_id}: {e}")
    
    # Добавляем модераторов из БД бота
    for mod in moderators:
        rank = mod['rank']
        
        # Rank 1 from DB: если это не Telegram creator, то это Co-owner (Совладелец)
        if rank == RANK_OWNER:
            # Добавляем в совладельцы только если это НЕ Telegram creator
            if creator_id is None or mod['user_id'] != creator_id:
                co_owners.append(mod)
            # Если это Telegram creator, он уже отображается как "Владелец", пропускаем
            continue
        
        if rank not in ranks:
            ranks[rank] = []
        
        if not any(existing_mod['user_id'] == mod['user_id'] for existing_mod in ranks[rank]):
            ranks[rank].append(mod)
    
    # Проверяем, есть ли кто-то для отображения
    has_anyone = owner_users or co_owners or ranks
    
    if not has_anyone:
        await send_message_with_gif(
            message,
            "👥 <b>Модераторы чата</b>\n\n• Модераторы не назначены",
            "moderatorslist",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Формируем сообщение
    staff_text = "👥 <b>Модераторы чата</b>\n\n"
    
    rank_emojis = {
        1: "👑",
        2: "⚜️",
        3: "🛡",
        4: "🔰"
    }
    
    # Сначала показываем владельца (Telegram creator)
    if owner_users:
        staff_text += f"👑 <b>Владелец:</b>\n"
        for owner in owner_users:
            user_display = get_user_mention_html(owner)
            staff_text += f"• {user_display}\n"
        staff_text += "\n"
    
    # Затем показываем совладельцев (rank 1 from DB)
    if co_owners:
        co_owner_name = "Совладелец" if len(co_owners) == 1 else "Совладельцы"
        staff_text += f"👑 <b>{co_owner_name}:</b>\n"
        for co_owner in co_owners:
            user_display = get_user_mention_html(co_owner)
            staff_text += f"• {user_display}\n"
        staff_text += "\n"
    
    # Затем показываем остальные ранги (2, 3, 4)
    for rank in sorted(ranks.keys()):
        mods = ranks[rank]
        rank_name = get_rank_name(rank, len(mods))
        emoji = rank_emojis.get(rank, "👤")
        
        staff_text += f"{emoji} <b>{rank_name}:</b>\n"
        
        for mod in mods:
            user_display = get_user_mention_html(mod)
            staff_text += f"• {user_display}\n"
        
        staff_text += "\n"
    
    await send_message_with_gif(message, staff_text, "moderatorslist", parse_mode=ParseMode.HTML)


async def verify_punishment_status(chat_id: int, user_id: int, punishment_type: str) -> Optional[bool]:
    """
    Проверяет фактический статус наказания в Telegram API
    
    Args:
        chat_id: ID чата
        user_id: ID пользователя
        punishment_type: Тип наказания ('ban' или 'mute')
    
    Returns:
        True если действительно активно, False если не активно, None если не удалось проверить
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        
        if punishment_type == 'ban':
            # Для бана проверяем статус 'kicked' (забанен)
            return member.status == 'kicked'
        elif punishment_type == 'mute':
            # Для мута проверяем права на отправку сообщений
            if hasattr(member, 'permissions') and member.permissions:
                return not member.permissions.can_send_messages
            # Если нет permissions, значит пользователь не в чате или это старый API
            return None
        else:
            return None
    except Exception as e:
        logger.debug(f"Не удалось проверить статус наказания для пользователя {user_id} в чате {chat_id}: {e}")
        return None


def format_punishment_entry(punishment: dict, verified_status: Optional[bool] = None) -> str:
    """
    Форматирует запись о наказании для отображения
    
    Args:
        punishment: Словарь с данными о наказании
        verified_status: Результат проверки через Telegram API (True/False/None)
    
    Returns:
        Отформатированная строка
    """
    # Эмодзи для типов наказаний
    type_emojis = {
        'ban': '🔴',
        'mute': '🔇',
        'warn': '⚠️',
        'kick': '👢'
    }
    
    type_names = {
        'ban': 'Ban',
        'mute': 'Mute',
        'warn': 'Warn',
        'kick': 'Kick'
    }
    
    emoji = type_emojis.get(punishment['punishment_type'], '⚙️')
    type_name = type_names.get(punishment['punishment_type'], punishment['punishment_type'])
    
    # Формируем упоминание пользователя (HTML)
    user_id = punishment.get('user_id')
    user_name = punishment.get('user_username')
    first_name = punishment.get('user_first_name', '') or ''
    last_name = punishment.get('user_last_name', '') or ''
    
    # Убираем "None" из имени
    if first_name == 'None':
        first_name = ''
    if last_name == 'None':
        last_name = ''
    
    if user_name:
        user_display = f"<a href='tg://user?id={user_id}'>@{user_name}</a>"
    elif first_name or last_name:
        display_name = f"{first_name} {last_name}".strip()
        user_display = f"<a href='tg://user?id={user_id}'>{display_name}</a>"
    else:
        user_display = f"<a href='tg://user?id={user_id}'>ID{user_id}</a>"
    
    # Формируем упоминание модератора (HTML)
    mod_id = punishment.get('moderator_id')
    mod_username = punishment.get('moderator_username')
    mod_first_name = punishment.get('moderator_first_name', '') or ''
    mod_last_name = punishment.get('moderator_last_name', '') or ''
    
    # Убираем "None" из имени
    if mod_first_name == 'None':
        mod_first_name = ''
    if mod_last_name == 'None':
        mod_last_name = ''
    
    if mod_id:
        if mod_username:
            mod_display = f"<a href='tg://user?id={mod_id}'>@{mod_username}</a>"
        elif mod_first_name or mod_last_name:
            mod_display_name = f"{mod_first_name} {mod_last_name}".strip()
            mod_display = f"<a href='tg://user?id={mod_id}'>{mod_display_name}</a>"
        else:
            mod_display = f"<a href='tg://user?id={mod_id}'>ID{mod_id}</a>"
    else:
        mod_display = "Неизвестно"
    
    # Форматируем дату
    try:
        date_str = punishment['date']
        if date_str:
            date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            formatted_date = date_obj.strftime('%d.%m.%Y %H:%M')
        else:
            formatted_date = "Неизвестно"
    except Exception:
        formatted_date = "Неизвестно"
    
    # Формируем статус
    # Кики всегда завершены - это разовое действие
    if punishment.get('punishment_type') == 'kick':
        status = "Завершен"
    elif verified_status is True:
        status = "Активен (проверено)"
    elif verified_status is False:
        status = "Завершен"
    elif verified_status is None:
        if punishment.get('is_active'):
            status = "Активен (не проверено)"
        else:
            status = "Завершен"
    else:
        status = "Неизвестно"
    
    # Формируем причину (показываем только если указана)
    reason = punishment.get('reason')
    if reason and reason.strip():
        # Обрезаем длинную причину
        if len(reason) > 30:
            reason_display = reason[:27] + "..."
        else:
            reason_display = reason
        reason_part = f" | {reason_display}"
    else:
        reason_part = ""
    
    # Собираем результат в одну строку
    result = f"{emoji} {type_name} | {user_display}{reason_part} | Модератор: {mod_display} | {formatted_date} | {status}"
    
    return result


@require_admin_rights
async def punishhistory_command(message: Message):
    """Команда просмотра истории наказаний"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем права на просмотр истории наказаний
    can_view = await check_permission(chat_id, user_id, 'can_view_punishhistory', lambda r: r <= 3)
    if not can_view:
        sent_message = await message.answer("❌ У вас нет прав для просмотра истории наказаний")
        asyncio.create_task(delete_message_after_delay(sent_message, 5))
        return
    
    # Сразу показываем все наказания
    await show_punishment_panel(message, page=1)


async def show_punishment_type_menu(message_or_callback):
    """
    Показывает меню выбора типа наказания
    
    Args:
        message_or_callback: Message или CallbackQuery объект
    """
    # Определяем chat_id и способ отправки сообщения
    if isinstance(message_or_callback, Message):
        chat_id = message_or_callback.chat.id
        send_func = message_or_callback.answer
        edit_func = None
    else:  # CallbackQuery
        chat_id = message_or_callback.message.chat.id
        send_func = None
        edit_func = message_or_callback.message.edit_text
    
    text = "📋 <b>История наказаний</b>\n\n"
    text += "Выберите тип наказания для просмотра:"
    
    # Создаем клавиатуру с выбором типа
    builder = InlineKeyboardBuilder()
    
    type_buttons = [
        ('🔴 Баны', 'ban'),
        ('🔇 Муты', 'mute'),
        ('⚠️ Варны', 'warn'),
        ('👢 Кики', 'kick'),
        ('📊 Все', 'all')
    ]
    
    for btn_text, btn_type in type_buttons:
        builder.button(
            text=btn_text,
            callback_data=f"punishhistory_type_{btn_type}"
        )
    
    builder.adjust(2, 2, 1)
    
    # Отправляем или редактируем сообщение
    try:
        if edit_func:
            await edit_func(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            if isinstance(message_or_callback, CallbackQuery):
                await message_or_callback.answer()
        else:
            await send_func(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка при отображении меню выбора типа: {e}")


async def show_punishment_panel(message_or_callback, page: int = 1):
    """
    Показывает панель истории наказаний
    
    Args:
        message_or_callback: Message или CallbackQuery объект
        page: Номер страницы
    """
    # Определяем chat_id и способ отправки сообщения
    if isinstance(message_or_callback, Message):
        chat_id = message_or_callback.chat.id
        send_func = message_or_callback.answer
        edit_func = None
    else:  # CallbackQuery
        chat_id = message_or_callback.message.chat.id
        send_func = None
        edit_func = message_or_callback.message.edit_text
    
    # Получаем все наказания (и активные, и завершенные)
    result = await moderation_db.get_punishments_paginated(
        chat_id=chat_id,
        page=page,
        per_page=10,
        punishment_type=None,  # Все типы
        active_only=None  # Все наказания
    )
    
    punishments = result['punishments']
    total_count = result['total_count']
    total_pages = result['total_pages']
    
    # Формируем текст заголовка
    header = f"📋 <b>История наказаний</b>\n\n"
    header += f"Всего записей: {total_count}\n"
    header += f"Страница {page} из {total_pages}\n\n"
    
    if not punishments:
        text = header + "История наказаний пуста."
    else:
        text = header
        # Проверяем статус в Telegram для активных ban и mute
        for punishment in punishments:
            verified_status = None
            # Проверяем только для активных ban и mute
            if punishment.get('is_active') and punishment['punishment_type'] in ['ban', 'mute']:
                verified_status = await verify_punishment_status(
                    chat_id, punishment['user_id'], punishment['punishment_type']
                )
            
            entry = format_punishment_entry(punishment, verified_status)
            text += entry + "\n"
    
    # Создаем клавиатуру - только пагинация
    builder = InlineKeyboardBuilder()
    
    # Кнопки пагинации
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"punishhistory_page_{page - 1}"
        ))
    
    nav_buttons.append(InlineKeyboardButton(
        text=f"{page}/{total_pages}",
        callback_data="punishhistory_noop"
    ))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(
            text="Вперед ▶️",
            callback_data=f"punishhistory_page_{page + 1}"
        ))
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    # Кнопка обновления
    builder.button(
        text="🔄 Обновить", 
        callback_data=f"punishhistory_refresh_{page}"
    )
    
    # Отправляем или редактируем сообщение
    try:
        if edit_func:
            await edit_func(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            if isinstance(message_or_callback, CallbackQuery):
                await message_or_callback.answer()
        else:
            await send_func(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка при отображении панели наказаний: {e}")


async def punishhistory_page_callback(callback: CallbackQuery):
    """Обработчик переключения страницы"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        
        # Проверяем права
        can_view = await check_permission(chat_id, user_id, 'can_view_stats', lambda r: r <= 3)
        if not can_view:
            await callback.answer("❌ У вас нет прав для просмотра истории наказаний", show_alert=True)
            return
        
        # Формат: punishhistory_page_{page}
        parts = callback.data.split('_')
        if len(parts) >= 3:
            page = int(parts[2])
            await show_punishment_panel(callback, page=page)
        else:
            await callback.answer("❌ Ошибка в данных страницы", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в punishhistory_page_callback: {e}")
        await callback.answer("❌ Ошибка при переключении страницы", show_alert=True)


async def punishhistory_refresh_callback(callback: CallbackQuery):
    """Обработчик обновления панели"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        
        # Проверяем права
        can_view = await check_permission(chat_id, user_id, 'can_view_stats', lambda r: r <= 3)
        if not can_view:
            await callback.answer("❌ У вас нет прав для просмотра истории наказаний", show_alert=True)
            return
        
        # Формат: punishhistory_refresh_{page}
        parts = callback.data.split('_')
        if len(parts) >= 3:
            page = int(parts[2])
            await show_punishment_panel(callback, page)
        else:
            # Fallback на значения по умолчанию
            await show_punishment_panel(callback, page=1)
    except Exception as e:
        logger.error(f"Ошибка в punishhistory_refresh_callback: {e}")
        await callback.answer("❌ Ошибка при обновлении", show_alert=True)


async def punishhistory_noop_callback(callback: CallbackQuery):
    """Пустой обработчик для кнопки с номером страницы"""
    await callback.answer()


