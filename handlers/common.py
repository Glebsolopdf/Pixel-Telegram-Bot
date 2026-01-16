"""
Общие обработчики команд и сообщений
"""
import logging
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from collections import defaultdict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, ChatJoinRequest, ChatMemberUpdated, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from config import BOT_NAME, BOT_DESCRIPTION, DEBUG
from databases.database import db
from utils.command_aliases import get_command_alias, is_command_alias
from utils.permissions import get_effective_rank, check_admin_rights
from utils.constants import RANK_OWNER, RANK_ADMIN
from utils.formatting import get_user_mention_html, get_philosophical_access_denied_message, format_mute_duration
from utils.gifs import send_message_with_gif
from raid_protection import raid_protection
from databases.raid_protection_db import raid_protection_db
from databases.moderation_db import moderation_db
from databases.utilities_db import utilities_db
from databases.reputation_db import reputation_db

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None

_recently_muted_cache: Dict[Tuple[int, int], datetime] = {}

def _cleanup_mute_cache():
    """Очистить старые записи из кеша мута (старше 60 секунд)"""
    current_time = datetime.now()
    keys_to_remove = []
    for key, mute_time in _recently_muted_cache.items():
        if (current_time - mute_time).total_seconds() > 60:
            keys_to_remove.append(key)
    for key in keys_to_remove:
        del _recently_muted_cache[key]
    if keys_to_remove:
        logger.debug(f"Очищено {len(keys_to_remove)} старых записей из кеша мута")


def register_common_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация общих обработчиков"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    dp.message.register(new_chat_member, F.new_chat_members)
    dp.message.register(left_chat_member, F.left_chat_member)
    dp.my_chat_member.register(handle_my_chat_member)
    dp.chat_join_request.register(handle_chat_join_request)
    dp.message_reaction.register(reaction_spam_handler)
    
    dp.message.register(start_command, CommandStart())
    dp.message.register(command_alias_handler, ~F.text.startswith('/'), F.text.func(lambda text: is_command_alias(text)))
    dp.message.register(help_command, Command("help"))
    dp.message.register(reset_day_stat_command, Command("resetdaystat"))
    dp.message.register(private_message_handler, F.chat.type == 'private', ~F.text.startswith('/'))
    # Регистрируем message_handler ПЕРЕД bot_mention_handler, чтобы он вызывался первым
    # message_handler должен обрабатывать все сообщения для статистики
    dp.message.register(message_handler, ~F.text.startswith('/'), ~F.new_chat_members, ~F.left_chat_member)
    # bot_mention_handler обрабатывает упоминания бота (регистрируется после message_handler)
    dp.message.register(bot_mention_handler, F.chat.type.in_(['group', 'supergroup']), ~F.text.startswith('/'))


async def create_main_menu():
    """Создает главное меню - единая функция для всех мест"""
    welcome_text = f"""
🏠 <b>Главное меню</b>

Привет! Я <b>{BOT_NAME}</b> - {BOT_DESCRIPTION}

Сайт: https://pixel-ut.pro


Выберите действие:
    """
    
    builder = InlineKeyboardBuilder()
    
    bot_info = await bot.get_me()
    add_to_chat_url = f"https://t.me/{bot_info.username}?startgroup=true"
    builder.add(InlineKeyboardButton(
        text="➕ Добавить в чат",
        url=add_to_chat_url
    ))

    builder.row(
        InlineKeyboardButton(
            text="📊 Мой профиль",
            callback_data="my_profile_private"
        ),
    )

    builder.row(
        InlineKeyboardButton(
            text="🏆 Топ чатов",
            callback_data="top_chats"
        ),
        InlineKeyboardButton(
            text="🎲 Случайный чат",
            callback_data="random_chat"
        ),
    )
    
    return welcome_text, builder.as_markup()


async def check_chat_active(callback: CallbackQuery) -> bool:
    """Проверяет, что чат активен и не заморожен"""
    try:
        if callback.message and callback.message.chat:
            chat_id = callback.message.chat.id
            if callback.message.chat.type in ['group', 'supergroup']:
                chat_info = await db.get_chat(chat_id)
                if not chat_info:
                    return False
                if not chat_info.get('is_active', True) or chat_info.get('frozen_at'):
                    logger.debug(f"Попытка использовать callback в неактивном/замороженном чате {chat_id}")
                    await safe_answer_callback(callback, "❌ Бот был удален из этого чата", show_alert=True)
                    return False
        return True
    except Exception as e:
        logger.error(f"Ошибка при проверке активности чата: {e}")
        return True


async def safe_answer_callback(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Безопасный ответ на callback-запрос, игнорирует ошибки устаревших запросов"""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as e:
        logger.debug(f"Ошибка при ответе на callback: {e}")
        pass


async def fast_edit_message(callback: CallbackQuery, text: str, reply_markup=None, parse_mode=None):
    """Быстрое обновление сообщения без задержек для навигации"""
    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.debug(f"Ошибка при быстром обновлении сообщения: {e}")
        pass


async def send_access_denied_message(message: Message, chat_id: int, user_id: int):
    """Отправляет сообщение об отказе в доступе пользователю"""
    try:
        quote = await get_philosophical_access_denied_message()
        await message.answer(quote)
    except Exception:
        await message.answer("❌ Недостаточно прав")


async def answer_access_denied_callback(callback: CallbackQuery):
    """Отвечает на callback-запрос с сообщением об отказе в доступе"""
    try:
        quote = await get_philosophical_access_denied_message()
        await callback.answer(quote, show_alert=True)
    except Exception:
        await callback.answer("❌ Недостаточно прав", show_alert=True)


async def update_chat_info_if_needed(chat_id: int) -> bool:
    """Обновление информации о чате при необходимости"""
    try:
        chat_info = await bot.get_chat(chat_id)
        
        member_count = None
        try:
            member_count = await bot.get_chat_member_count(chat_id)
            logger.debug(f"Получено количество участников для чата {chat_id}: {member_count}")
        except Exception as e:
            logger.debug(f"Не удалось получить количество участников для чата {chat_id}: {e}")
            try:
                if chat_info.type == 'channel' and hasattr(chat_info, 'member_count'):
                    member_count = chat_info.member_count
                    logger.debug(f"Получено количество участников через get_chat для канала {chat_id}: {member_count}")
                elif chat_info.type == 'supergroup' and hasattr(chat_info, 'member_count'):
                    member_count = chat_info.member_count
                    logger.debug(f"Получено количество участников через get_chat для супергруппы {chat_id}: {member_count}")
            except Exception as e2:
                logger.debug(f"Альтернативный способ тоже не сработал для чата {chat_id}: {e2}")
        
        is_public = False
        if chat_info.type == 'channel':
            is_public = True
        elif chat_info.type in ['group', 'supergroup']:
            is_public = hasattr(chat_info, 'username') and chat_info.username is not None
        
        chat_username = None
        if hasattr(chat_info, 'username') and chat_info.username:
            chat_username = chat_info.username
        
        invite_link = None
        invite_link_updated = False
        if not is_public and chat_info.type in ['group', 'supergroup']:
            try:
                bot_member = await bot.get_chat_member(chat_id, bot.id)
                if bot_member.status in ['administrator', 'creator']:
                    chat_db_info = await db.get_chat(chat_id)
                    existing_invite_link = chat_db_info.get('invite_link') if chat_db_info else None
                    
                    if not existing_invite_link:
                        try:
                            if existing_invite_link:
                                try:
                                    await bot.revoke_chat_invite_link(
                                        chat_id=chat_id,
                                        invite_link=existing_invite_link
                                    )
                                    logger.debug(f"Удалена старая invite link для чата {chat_id}: {existing_invite_link}")
                                except Exception as revoke_error:
                                    logger.debug(f"Не удалось удалить старую invite link {existing_invite_link}: {revoke_error}")
                            
                            try:
                                primary_link_obj = await bot.export_chat_invite_link(chat_id=chat_id)
                                if primary_link_obj and primary_link_obj.invite_link:
                                    if not existing_invite_link or primary_link_obj.invite_link != existing_invite_link:
                                        try:
                                            await bot.revoke_chat_invite_link(
                                                chat_id=chat_id,
                                                invite_link=primary_link_obj.invite_link
                                            )
                                            logger.debug(f"Удалена основная invite link для чата {chat_id}: {primary_link_obj.invite_link}")
                                        except Exception as revoke_error:
                                            logger.debug(f"Не удалось удалить основную invite link: {revoke_error}")
                            except Exception as export_error:
                                logger.debug(f"Не удалось получить основную invite link для чата {chat_id}: {export_error}")
                            
                            invite_link_obj = await bot.create_chat_invite_link(
                                chat_id=chat_id,
                                name="Bot Auto Link",
                                creates_join_request=False,
                                expire_date=None,
                                member_limit=None
                            )
                            invite_link = invite_link_obj.invite_link
                            invite_link_updated = True
                            logger.info(f"Создана новая invite link для частного чата {chat_id}: {invite_link}")
                        except Exception as e:
                            logger.warning(f"Не удалось создать invite link для чата {chat_id}: {e}")
                    else:
                        invite_link = existing_invite_link
            except Exception as e:
                logger.debug(f"Не удалось создать/обновить invite link для чата {chat_id}: {e}")
        
        if is_public:
            invite_link = None
            invite_link_updated = True
        
        logger.debug(f"Обновляем информацию о чате {chat_id}: member_count={member_count}, is_public={is_public}, username={chat_username}, invite_link={'установлена' if invite_link else 'нет'}")
        
        update_params = {
            'chat_id': chat_id,
            'title': chat_info.title,
            'chat_type': chat_info.type,
            'member_count': member_count,
            'is_active': True,
            'is_public': is_public,
            'username': chat_username,
        }
        
        if invite_link_updated:
            update_params['invite_link'] = invite_link
        
        await db.update_chat_info(**update_params)
        
        return True
    except Exception as e:
        error_str = str(e).lower()
        if "chat not found" in error_str or "bad request" in error_str or "bot was kicked" in error_str or "forbidden" in error_str:
            if DEBUG:
                logger.debug(f"Чат {chat_id} недоступен при обновлении информации (бот исключен или чат не найден): {e}")
            try:
                await db.deactivate_chat(chat_id)
            except Exception:
                pass
        else:
            logger.error(f"Ошибка при обновлении информации о чате {chat_id}: {e}")
        return False


async def delete_message_after_delay(message: Message, delay: int):
    """Удаляет сообщение после указанной задержки"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения после задержки: {e}")


async def extract_user_from_system_message(reply_message: Message) -> Optional[types.User]:
    """
    Извлекает пользователя из системного сообщения Telegram
    
    Поддерживает:
    1. new_chat_members - список новых участников (берем первого)
    2. left_chat_member - вышедший участник
    3. user_joined - новый API для присоединения
    4. user_left - новый API для выхода
    
    Возвращает None если это не системное сообщение или пользователь не найден
    """
    if not reply_message:
        return None
    
    if reply_message.new_chat_members and len(reply_message.new_chat_members) > 0:
        return reply_message.new_chat_members[0]
    
    if reply_message.left_chat_member:
        return reply_message.left_chat_member
    
    if hasattr(reply_message, 'user_joined') and reply_message.user_joined:
        return reply_message.user_joined
    
    if hasattr(reply_message, 'user_left') and reply_message.user_left:
        return reply_message.user_left
    
    return None


async def parse_user_from_args(message: Message, args: list, arg_index: int) -> Optional[types.User]:
    """
    Извлекает информацию о пользователе из аргументов команды
    
    Поддерживает:
    1. Telegram mention entities (text_mention)
    2. @username в тексте
    3. Поиск по user_id (если аргумент - число)
    4. Поиск по first_name в текущем чате
    5. Возвращает None если не найден
    """
    if arg_index >= len(args):
        return None
    
    chat_id = message.chat.id
    arg = args[arg_index].strip()
    
    if message.entities:
        for entity in message.entities:
            if entity.type == "text_mention" and hasattr(entity, 'user'):
                entity_text = message.text[entity.offset:entity.offset + entity.length]
                if entity_text == arg or arg in entity_text:
                    return entity.user
    
    if arg.startswith('@'):
        username = arg[1:]
        try:
            user_data = await db.get_user_by_username(username)
            if user_data:
                from types import SimpleNamespace
                return SimpleNamespace(
                    id=user_data['user_id'],
                    username=user_data['username'],
                    first_name=user_data['first_name'],
                    last_name=user_data.get('last_name'),
                    is_bot=user_data['is_bot']
                )
        except Exception as e:
            logger.error(f"Ошибка при поиске пользователя @{username}: {e}")
    
    if arg.isdigit():
        try:
            user_id = int(arg)
            try:
                chat_member = await bot.get_chat_member(chat_id, user_id)
                return chat_member.user
            except Exception:
                pass
        except ValueError:
            pass
    
    try:
        found_users = await db.search_users_by_name_in_chat(chat_id, arg)
        
        if found_users:
            user_data = found_users[0]
            found_user_id = user_data['user_id']
            
            try:
                chat_member = await bot.get_chat_member(chat_id, found_user_id)
                return chat_member.user
            except Exception as e:
                logger.debug(f"Пользователь {found_user_id} не найден в чате через API: {e}")
                if len(found_users) > 1:
                    for user_data in found_users[1:]:
                        try:
                            found_user_id = user_data['user_id']
                            chat_member = await bot.get_chat_member(chat_id, found_user_id)
                            return chat_member.user
                        except Exception:
                            continue
    except Exception as e:
        logger.error(f"Ошибка при поиске пользователя по имени '{arg}': {e}")
    
    return None


def require_bot_admin_rights(func):
    """Декоратор для проверки прав администратора бота"""
    async def wrapper(message: Message, **kwargs):
        logger.info(f"Команда {func.__name__} вызвана в чате {message.chat.id} ({message.chat.type})")
        
        has_bot_admin = await check_admin_rights(bot, message.chat.id)
        logger.info(f"Права администратора бота: {has_bot_admin}")
        
        if not has_bot_admin:
            quote = await get_philosophical_access_denied_message()
            await message.answer(quote)
            return
        
        logger.info("Права администратора бота есть - выполняем команду")
        return await func(message, **kwargs)
    
    return wrapper


def require_admin_rights(func):
    """Декоратор для проверки прав администратора"""
    async def wrapper(message: Message, **kwargs):
        logger.info(f"Команда {func.__name__} вызвана в чате {message.chat.id} ({message.chat.type})")
        
        if message.chat.type == 'private':
            logger.info("Личное сообщение - пропускаем проверку прав")
            return await func(message)
        
        has_admin = await check_admin_rights(bot, message.chat.id)
        logger.info(f"Права администратора: {has_admin}")
        
        if not has_admin:
            logger.info("Нет прав администратора - отправляем предупреждение")
            await message.answer(
                "⚠️ **Требуются права администратора!**\n\n"
                "Для работы команд в этом чате мне необходимы права администратора.\n"
                "Пожалуйста, выдайте мне права администратора в настройках группы.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        logger.info("Права администратора есть - выполняем команду")
        return await func(message)
    return wrapper


async def start_command(message: Message):
    """Обработчик команды /start в личных сообщениях"""
    user = message.from_user
    
    if message.chat.type != 'private':
        return
    
    await db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        is_bot=user.is_bot
    )
    
    welcome_text, reply_markup = await create_main_menu()
    
    await message.answer(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def command_alias_handler(message: Message):
    """Универсальный обработчик алиасов команд"""
    from handlers.profile import myprofile_command
    from handlers.top_chats import top_users_command, top_users_all_chats_command
    from handlers.moderation import mute_command, unmute_command, kick_command, ban_command, unban_command, warn_command, unwarn_command, ap_command, unap_command, staff_command, punishhistory_command
    from handlers.settings import settings_command, selfdemote_command, rules_command
    from handlers.raid_protection import raid_protection_command
    
    text = message.text.strip() if message.text else ""
    chat_id = message.chat.id
    
    requires_prefix = await db.get_russian_commands_prefix_setting(chat_id)
    
    if requires_prefix:
        if not text.lower().startswith("пиксель"):
            return
        
        text = text[7:].strip()
    
    text_lower = text.lower()
    is_clear_rules = False
    is_rules_command = False
    
    # Проверяем специальные случаи для команды rules
    if text_lower == "очистить" or text_lower == "правила очистить" or text_lower.startswith("правила очистить"):
        english_command = "rules"
        is_clear_rules = True
        is_rules_command = True
    else:
        english_command = get_command_alias(text)
        if english_command == "rules":
            is_rules_command = True
    
    if not english_command:
        return
    
    # Специальная обработка для команды rules - сохраняем всё форматирование
    if is_rules_command:
        # Находим позицию слова "правила" (с учетом регистра)
        rules_word = "правила"
        rules_pos_lower = text_lower.find(rules_word)
        
        if rules_pos_lower != -1:
            # Находим конец слова "правила" в оригинальном тексте
            # Ищем границу слова (конец "правила" + пробелы)
            end_pos = rules_pos_lower + len(rules_word)
            # Пропускаем пробелы после слова "правила"
            while end_pos < len(text) and text[end_pos].isspace():
                end_pos += 1
            
            # Извлекаем всё после слова "правила", сохраняя оригинальное форматирование
            if end_pos < len(text):
                rules_text = text[end_pos:]
                if is_clear_rules:
                    new_text = f"/{english_command} clear"
                elif rules_text.strip().lower() == "clear":
                    new_text = f"/{english_command} clear"
                elif rules_text.strip():
                    # Сохраняем весь текст правил с форматированием
                    # Добавляем пробел только если текст не начинается с пробела или переноса строки
                    if rules_text and not rules_text[0].isspace():
                        new_text = f"/{english_command} {rules_text}"
                    else:
                        new_text = f"/{english_command}{rules_text}"
                else:
                    new_text = f"/{english_command}"
            else:
                new_text = f"/{english_command}"
        else:
            # Если не нашли слово "правила", используем стандартную обработку
            if is_clear_rules:
                new_text = f"/{english_command} clear"
            else:
                new_text = f"/{english_command}"
        
        new_message = message.model_copy(update={"text": new_text})
    elif '\n' in text:
        # Обработка для других команд с переносом строки
        lines = text.split('\n', 1)
        command_line = lines[0].strip()
        reason_line = lines[1].strip()
        
        words = command_line.split()
        
        if english_command == "myprofile_self":
            new_text = f"/{english_command}\n{reason_line}"
        elif english_command == "myprofile" and len(words) >= 2 and words[0] == "кто" and words[1] == "ты":
            if len(words) > 2:
                args = " ".join(words[2:])
                new_text = f"/{english_command} {args}\n{reason_line}"
            else:
                new_text = f"/{english_command}\n{reason_line}"
        elif len(words) > 1:
            args = " ".join(words[1:])
            new_text = f"/{english_command} {args}\n{reason_line}"
        else:
            new_text = f"/{english_command}\n{reason_line}"
        
        new_message = message.model_copy(update={"text": new_text})
    else:
        # Обработка для других команд без переноса строки
        words = text.split()
        
        if english_command == "myprofile_self":
            new_text = f"/{english_command}"
        elif english_command == "myprofile" and len(words) >= 2 and words[0] == "кто" and words[1] == "ты":
            if len(words) > 2:
                args = " ".join(words[2:])
                new_text = f"/{english_command} {args}"
            else:
                new_text = f"/{english_command}"
        elif len(words) > 1:
            args = " ".join(words[1:])
            new_text = f"/{english_command} {args}"
        else:
            new_text = f"/{english_command}"
        
        new_message = message.model_copy(update={"text": new_text})
    
    logger.info(f"Русская команда переведена в английскую в чате {message.chat.id}")

    command_handlers = {
        "top": top_users_command,
        "myprofile": myprofile_command,
        "myprofile_self": myprofile_command,
        "settings": settings_command,
        "ap": ap_command,
        "punishhistory": punishhistory_command,
        "unap": unap_command,
        "selfdemote": selfdemote_command,
        "staff": staff_command,
        "mute": mute_command,
        "unmute": unmute_command,
        "kick": kick_command,
        "ban": ban_command,
        "unban": unban_command,
        "warn": warn_command,
        "unwarn": unwarn_command,
        "topall": top_users_all_chats_command,
        "raidprotection": raid_protection_command,
        "rules": rules_command,
    }

    handler = command_handlers.get(english_command)
    if handler:
        await handler(new_message)


async def reset_day_stat_command(message: Message):
    """Команда для сброса ежедневной статистики (только для администраторов и владельца)"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if message.chat.type == 'private':
        await message.answer("❌ Эта команда доступна только в групповых чатах.")
        return
    
    rank = await get_effective_rank(chat_id, user_id)
    if rank not in [RANK_OWNER, RANK_ADMIN]:
        await message.answer(
            await get_philosophical_access_denied_message(chat_id, user_id)
        )
        return
    
        try:
            from datetime import datetime
            ts = datetime.utcnow().timestamp() + 10800
            today_display = datetime.utcfromtimestamp(ts).strftime('%d.%m.%Y')
            
            success = await db.reset_daily_stats(chat_id)
            if success:
                await message.answer(
                    f"✅ Ежедневная статистика успешно сброшена для чата за {today_display}.\n\n"
                    f"Статистика будет автоматически сбрасываться каждый день в 00:00 МСК."
                )
                logger.info(f"Ежедневная статистика сброшена вручную для чата {chat_id} пользователем {user_id} за {today_display}")
            else:
                await message.answer("❌ Произошла ошибка при сбросе ежедневной статистики.")
                logger.error(f"Ошибка при сбросе ежедневной статистики для чата {chat_id}")
        except Exception as e:
            await message.answer("❌ Произошла ошибка при сбросе ежедневной статистики.")
            logger.error(f"Ошибка при сбросе ежедневной статистики для чата {chat_id}: {e}", exc_info=True)


async def help_command(message: Message):
    """Обработчик команды /help"""
    help_text = """
📋 <b>Справка по командам PIXEL</b>

<b>Основные команды:</b>
• <code>/help</code> - эта справка
• <code>/info</code> - информация о чате
• <code>/top</code> - топ 20 активных пользователей за сегодня
• <code>/topall</code> - топ пользователей за 60 дней в этом чате
• <code>/myprofile</code> - ваш профиль с графиком активности за месяц
• <code>/settings</code> - центральное меню настроек
• <code>/autojoin on|off</code> - авто-принятие заявок на вступление
• <code>/statconfig</code> - настройки статистики (админы)

<b>Команды модерации:</b>
• <code>/ap @username 3</code> - назначить ранг модератора
• <code>/ap 3</code> - назначить ранг (при ответе на сообщение)
• <code>/unap @username</code> - снять ранг модератора
• <code>/unap</code> - снять ранг (при ответе на сообщение)
• <code>/removmymod</code> - снять свой ранг модератора
• <code>/staff</code> - список модераторов чата
• <code>/mute 10 часов</code> - замутить (при ответе на сообщение)
• <code>/mute @username 10 часов</code> - замутить пользователя
• <code>/unmute</code> - размутить (при ответе на сообщение)
• <code>/unmute @username</code> - размутить пользователя
• <code>/kick @username</code> - исключить из чата
• <code>/kick</code> - исключить (при ответе на сообщение)
• <code>/punishhistory</code> или <code>/История наказаний</code> - история наказаний (модераторы)
• <code>/userinfo</code> или <code>/ui</code> - информация о пользователе из Telegram API

<b>Система предупреждений:</b>
• <code>/warn</code> - выдать предупреждение (при ответе)
• <code>/warn @username</code> - выдать предупреждение
• <code>/unwarn</code> - снять предупреждение (при ответе)
• <code>/unwarn @username</code> - снять предупреждение
• <code>/warns</code> - посмотреть предупреждения (при ответе)
• <code>/warns @username</code> - посмотреть предупреждения
• <code>/warnconfig</code> - настройки системы варнов (только админы)

<b>Баны:</b>
• <code>/ban</code> - забанить навсегда (при ответе)
• <code>/ban @username</code> - забанить навсегда
• <code>/ban 1 час</code> - временный бан (при ответе)
• <code>/ban @username 1 час</code> - временный бан
• <code>/unban</code> - разбанить (при ответе)
• <code>/unban @username</code> - разбанить

<b>Правила чата:</b>
• <code>/rules</code> - показать правила чата (доступно всем)
• <code>/rules [текст]</code> - установить правила чата (требуются права)
• <code>/rules clear</code> - удалить правила чата (требуются права)

<b>Настройка прав:</b>
• <code>/rankconfig</code> - настройка прав рангов (владелец)
• <code>/initperms</code> - инициализация прав по умолчанию (владелец)
• <code>/russianprefix</code> - настройка префикса для русских команд (владелец)
• <code>/resetconfig</code> - сброс всех настроек к значениям по умолчанию (администратор)

<b>Защита от рейдов:</b>
• <code>/raidprotection</code> - показать настройки защиты от рейдов

<b>Репутация:</b>
• <code>/reputation</code> или <code>/rep</code> - показать свою репутацию
• <code>/reputation @username</code> - показать репутацию пользователя
• <code>/reputation</code> - показать репутацию (при ответе на сообщение)

<b>Упоминания в топах:</b>
• <code>/mentionping</code> - включить кликабельные упоминания (ping) в топах и статистике
• <code>/unmentionping</code> - выключить кликабельные упоминания в топах и статистике

<b>Сетка чатов:</b>
• <code>/net</code> - панель управления сеткой чатов (только ЛС)
• <code>/netconnect &lt;код&gt;</code> - подключить чат к сетке (4-значный код)
• <code>/netadd &lt;код&gt;</code> - добавить чат в существующую сетку (2-значный код)
• <code>/chatnet</code> - информация о сетке чатов
• <code>/chatnet update</code> - обновить информацию о чатах
• <code>/unnet</code> - отключить чат от сетки

<b>Личные сообщения:</b>
• <code>/menu</code> - вернуться в главное меню

<b>Ранги модерации:</b>
• 1 - Владелец 👑
• 2 - Администратор ⚜️
• 3 - Старший модератор 🛡
• 4 - Младший модератор 🔰

<b>🇷🇺 Русские команды:</b>
• <code>стата</code> → <code>/top</code>
• <code>топ</code> → <code>/top</code>
• <code>стата вся</code> → <code>/topall</code>
• <code>статистика вся</code> → <code>/topall</code>
• <code>профиль</code> → <code>/myprofile</code>
• <code>мой профиль</code> → <code>/myprofile</code>
• <code>настройки</code> → <code>/settings</code>
• <code>конфиг</code> → <code>/settings</code>
• <code>правила</code> → <code>/rules</code>
• <code>правила очистить</code> или <code>очистить</code> → <code>/rules clear</code>
• <code>автодопуск</code> → <code>/autojoin</code>

<b>🛡️ Модерация:</b>
• <code>мут</code> → <code>/mute</code>
• <code>размут</code> → <code>/unmute</code>
• <code>кик</code> → <code>/kick</code>
• <code>бан</code> → <code>/ban</code>
• <code>разбан</code> → <code>/unban</code>
• <code>варн</code> → <code>/warn</code>
• <code>разварн</code> → <code>/unwarn</code>
    """
    
    await message.answer(
        help_text,
        parse_mode=ParseMode.HTML
    )


async def private_message_handler(message: Message, state: FSMContext):
    """Обработчик личных сообщений с ботом - обрабатывает только НЕ-команды"""
    logger.info(f"Обычное сообщение в ЛС от {message.from_user.id} - игнорируем")
    pass


_bot_mention_cache = {}
BOT_MENTION_COOLDOWN = 30


def get_bot_mention_responses() -> list[str]:
    """Получить список ответов на упоминания бота"""
    return [
        "На месте!",
        "Здесь!",
        "Я весь во внимании!",
        "Готов помочь!",
        "Я здесь!",
        "Да, я здесь!",
    ]


async def bot_mention_handler(message: Message):
    """Обработчик упоминаний бота в чате"""
    global _bot_mention_cache
    
    if not message.text:
        return
    
    chat_id = message.chat.id
    text = message.text.lower()
    
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username.lower() if bot_info.username else None
    except Exception:
        return
    
    if not bot_username or f"@{bot_username}" not in text:
        return
    
    import time
    import random
    current_time = time.time()
    last_response_time = _bot_mention_cache.get(chat_id, 0)
    
    if current_time - last_response_time < BOT_MENTION_COOLDOWN:
        return
    
    _bot_mention_cache[chat_id] = current_time
    
    _bot_mention_cache = {k: v for k, v in _bot_mention_cache.items() 
                          if current_time - v < 3600}
    
    responses = get_bot_mention_responses()
    response = random.choice(responses)
    
    try:
        await message.reply(response)
    except Exception as e:
        logger.debug(f"Ошибка при ответе на упоминание в чате {chat_id}: {e}")


async def message_handler(message: Message):
    """Обработчик сообщений: проверка на рейды и подсчет для статистики"""
    _cleanup_mute_cache()
    
    if message.chat.type in ['group', 'supergroup']:
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        try:
            active_mutes = await moderation_db.get_active_punishments(chat_id, "mute")
            user_mutes = [mute for mute in active_mutes if mute['user_id'] == user_id]
            
            if user_mutes:
                try:
                    chat_member = await bot.get_chat_member(chat_id, user_id)
                    user_is_muted = False
                    
                    if hasattr(chat_member, 'status') and chat_member.status == 'restricted':
                        if hasattr(chat_member, 'permissions') and chat_member.permissions:
                            if not chat_member.permissions.can_send_messages:
                                user_is_muted = True
                    
                    if not user_is_muted:
                        from handlers.moderation import restore_user_mutes
                        await restore_user_mutes(chat_id, user_id)
                except Exception as e:
                    logger.debug(f"Не удалось проверить/восстановить мут для пользователя {user_id} в чате {chat_id}: {e}")
        except Exception as e:
            logger.debug(f"Ошибка при проверке мута для пользователя {user_id} в чате {chat_id}: {e}")
        
        is_raid, raid_type, message_id = await raid_protection.check_message(message)
        
        if is_raid and message_id:
            logger.info(f"Обнаружен рейд типа {raid_type} от пользователя {user_id} в чате {chat_id}")
            
            await raid_protection.delete_message(chat_id, message_id)
            await raid_protection_db.add_deleted_message(chat_id, user_id, raid_type)
            
            settings = await raid_protection_db.get_settings(chat_id)
            logger.info(f"Получены настройки для чата {chat_id}: {settings}")
            notification_mode = settings.get('notification_mode', 1)
            mute_duration = settings.get('mute_duration', 300)
            auto_mute_enabled = settings.get('auto_mute_enabled', True)
            mute_silent = settings.get('mute_silent', False)
            
            logger.info(f"Настройки мута для чата {chat_id}: mute_duration={mute_duration}, auto_mute_enabled={auto_mute_enabled}, mute_silent={mute_silent}")
            
            auto_mute_applied = False
            should_send_notification = False
            if mute_duration > 0 and auto_mute_enabled:
                cache_key = (chat_id, user_id)
                current_time = datetime.now()
                recently_muted = False
                
                if cache_key in _recently_muted_cache:
                    time_since_mute = (current_time - _recently_muted_cache[cache_key]).total_seconds()
                    if time_since_mute < 30:
                        logger.info(f"Пользователь {user_id} был замучен недавно ({time_since_mute:.1f} сек назад), пропускаем повторный мут")
                        recently_muted = True
                        auto_mute_applied = False
                    else:
                        del _recently_muted_cache[cache_key]
                
                if not recently_muted:
                    # Отмечаем что обрабатываем этот мут ДО попытки применения
                    _recently_muted_cache[cache_key] = current_time
                    
                    logger.info(f"Попытка применить мут для пользователя {user_id} в чате {chat_id}")
                    try:
                        mute_until = datetime.now() + timedelta(seconds=mute_duration)
                        
                        # Проверяем активные наказания в БД перед применением
                        active_punishments = await moderation_db.get_active_punishments(chat_id, "mute")
                        user_is_muted_in_db = any(punish['user_id'] == user_id for punish in active_punishments)
                        
                        user_is_muted = False
                        try:
                            chat_member = await bot.get_chat_member(chat_id, user_id)
                            logger.info(f"Статус пользователя {user_id} в чате {chat_id}: {chat_member.status}")
                            if hasattr(chat_member, 'status') and chat_member.status == 'restricted':
                                if hasattr(chat_member, 'permissions') and chat_member.permissions:
                                    if not chat_member.permissions.can_send_messages:
                                        user_is_muted = True
                                        logger.info(f"Пользователь {user_id} действительно замучен в Telegram (can_send_messages=False)")
                                    else:
                                        logger.info(f"Пользователь {user_id} имеет статус 'restricted', но может отправлять сообщения")
                            elif hasattr(chat_member, 'status'):
                                logger.info(f"Пользователь {user_id} имеет статус '{chat_member.status}', не замучен")
                        except Exception as e:
                            logger.warning(f"Не удалось проверить статус пользователя {user_id} в чате {chat_id}: {e}")
                            user_is_muted = user_is_muted_in_db
                            logger.info(f"Проверка через БД: user_is_muted={user_is_muted}")
                        
                        # Если уже замучен в БД или в Telegram, пропускаем
                        if user_is_muted or user_is_muted_in_db:
                            logger.info(f"Пользователь {user_id} уже замучен, пропускаем")
                            # Оставляем кэш, чтобы предотвратить повторные попытки
                        
                        if not user_is_muted and not user_is_muted_in_db:
                            from aiogram.types import ChatPermissions
                            try:
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
                                
                                await moderation_db.add_punishment(
                                    chat_id=chat_id,
                                    user_id=user_id,
                                    moderator_id=bot.id,
                                    punishment_type="mute",
                                    reason=f"Автоматический мут за рейд ({raid_type})",
                                    expiry_date=mute_until.isoformat(),
                                    user_username=message.from_user.username,
                                    user_first_name=message.from_user.first_name,
                                    moderator_username=None,
                                    moderator_first_name=BOT_NAME
                                )
                                
                                auto_mute_applied = True
                                duration_minutes = mute_duration // 60
                                logger.info(f"Автоматический мут применен к пользователю {user_id} в чате {chat_id} на {duration_minutes} минут")
                            except Exception as mute_error:
                                # Если не удалось применить мут, удаляем из кэша, чтобы можно было повторить попытку
                                if cache_key in _recently_muted_cache:
                                    del _recently_muted_cache[cache_key]
                                raise mute_error
                            
                    except Exception as e:
                        logger.error(f"Ошибка при применении автоматического мута: {e}")
            else:
                if mute_duration <= 0:
                    logger.info(f"Мут не применен: mute_duration={mute_duration} (должно быть > 0)")
                if not auto_mute_enabled:
                    logger.info(f"Мут не применен: auto_mute_enabled={auto_mute_enabled}")
            
            if auto_mute_applied and not mute_silent:
                cache_key = (chat_id, user_id)
                current_time = datetime.now()
                should_send_notification = True
                
                if cache_key in _recently_muted_cache:
                    time_since_mute = (current_time - _recently_muted_cache[cache_key]).total_seconds()
                    if time_since_mute < 30:
                        should_send_notification = False
                        logger.info(f"Уведомление о муте для пользователя {user_id} уже было отправлено недавно ({time_since_mute:.1f} сек назад), пропускаем")
                
                if should_send_notification:
                    try:
                        user_mention = get_user_mention_html(message.from_user)
                        duration_minutes = mute_duration // 60
                        duration_text = f"{duration_minutes} мин"
                        
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"🔇 Участник {user_mention} замучен на {duration_text} за спам!",
                            parse_mode=ParseMode.HTML
                        )
                        logger.info(f"Отправлено уведомление об автоматическом муте пользователю {user_id} в чате {chat_id}")
                        
                        _recently_muted_cache[cache_key] = current_time
                    except Exception as e:
                        logger.error(f"Ошибка при отправке уведомления о муте: {e}")
            
            if notification_mode == 1:
                recent_deleted_count = await raid_protection_db.get_recent_deleted_count(chat_id, minutes=1)
                
                if recent_deleted_count >= 3:
                    last_notification = await raid_protection_db.get_last_notification_time(chat_id)
                    should_notify = True
                    
                    if last_notification:
                        try:
                            last_notification_time = datetime.fromisoformat(last_notification)
                            time_since_notification = (datetime.now() - last_notification_time).total_seconds()
                            if time_since_notification < 60:
                                should_notify = False
                        except ValueError:
                            pass
                    
                    if should_notify:
                        chat_title = message.chat.title or "Без названия"
                        
                        await raid_protection.notify_owner(
                            chat_id=chat_id,
                            raid_type=raid_type,
                            user_id=None,
                            details=f"Чат: {chat_title}\nУникальных пользователей: {recent_deleted_count}"
                        )
                        
                        await raid_protection_db.update_last_notification_time(chat_id, datetime.now().isoformat())
            
            logger.info(f"🚫 Сообщение от {user_id} в чате {chat_id} определено как рейд, статистика не засчитывается")
            return
        
        utilities_settings = await utilities_db.get_settings(chat_id)
        if utilities_settings.get('emoji_spam_enabled', False) and message.text:
            emoji_limit = utilities_settings.get('emoji_spam_limit', 10)
            
            custom_emoji_count = 0
            if message.entities:
                custom_emoji_count = sum(1 for entity in message.entities if entity.type == 'custom_emoji')
            
            emoji_pattern = re.compile(
                "["
                "\U0001F300-\U0001F9FF"
                "\U00002600-\U000026FF"
                "\U00002700-\U000027BF"
                "\U0001F600-\U0001F64F"
                "\U0001F680-\U0001F6FF"
                "\U0001F1E0-\U0001F1FF"
                "\U0001F900-\U0001F9FF"
                "]",
                flags=re.UNICODE
            )
            regular_emoji_matches = emoji_pattern.findall(message.text)
            regular_emoji_count = len(regular_emoji_matches)
            
            total_emoji_count = custom_emoji_count + regular_emoji_count
            
            if total_emoji_count >= emoji_limit:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                    logger.info(f"Удалено сообщение с {total_emoji_count} эмодзи (кастомных: {custom_emoji_count}, обычных: {regular_emoji_count}) от пользователя {message.from_user.id} в чате {chat_id}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения с эмодзи спамом: {e}")
                logger.info(f"🚫 Сообщение от {message.from_user.id} в чате {chat_id} удалено как эмодзи спам, статистика не засчитывается")
                return
        
        if utilities_settings.get('fake_commands_enabled', False) and message.text and message.entities:
            for entity in message.entities:
                if entity.type == "bot_command":
                    command_text = message.text[entity.offset:entity.offset + entity.length]
                    await utilities_db.add_command_detection(chat_id, command_text)
                    logger.debug(f"Обнаружена команда {command_text} в сообщении от пользователя {message.from_user.id} в чате {chat_id}")
        
        # Проверка на автоматический бан каналов (сообщения, отправленные от имени канала)
        if utilities_settings.get('auto_ban_channels_enabled', False):
            # Проверяем sender_chat - это означает, что сообщение отправлено от имени канала (не переслано)
            if message.sender_chat and message.sender_chat.type == 'channel':
                channel = message.sender_chat
                channel_id = channel.id
                channel_username = getattr(channel, 'username', None)
                channel_title = getattr(channel, 'title', None) or (f"@{channel.username}" if channel.username else f"ID{channel.id}")
                
                # Всегда пытаемся забанить канал через API
                # Если канал уже забанен, API вернет ошибку, которую мы игнорируем
                # Если канал не забанен - баним заново
                try:
                    # Для каналов используем ban_chat_sender_chat вместо ban_chat_member
                    # Примечание: ban_chat_sender_chat не поддерживает временные баны (until_date)
                    await bot.ban_chat_sender_chat(
                        chat_id=chat_id,
                        sender_chat_id=channel_id
                    )
                    
                    logger.info(f"Автоматически забанен канал {channel_id} ({channel_title}) в чате {chat_id}")
                except Exception as e:
                    error_str = str(e).lower()
                    # Если канал уже забанен - это нормально, просто удаляем сообщение
                    if "already banned" in error_str or "chat is banned" in error_str or "already restricted" in error_str:
                        logger.debug(f"Канал {channel_id} уже забанен в чате {chat_id}, просто удаляем сообщение")
                    else:
                        logger.error(f"Ошибка при автоматическом бане канала {channel_id} в чате {chat_id}: {e}")
                
                # Удаляем сообщение в любом случае
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                    logger.info(f"Удалено сообщение от забаненного канала {channel_id} в чате {chat_id}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения от канала {channel_id}: {e}")
                
                # Не засчитываем статистику для сообщений от забаненных каналов
                return
        
        stat_settings = await db.get_chat_stat_settings(chat_id)
        
        # Проверяем, включена ли статистика для чата
        if not stat_settings.get('stats_enabled', True):
            logger.info(f"🚫 Статистика отключена для чата {chat_id}, пропускаем сообщение")
            return
        
        if not stat_settings.get('count_media', True):
            if message.content_type != 'text':
                logger.info(f"🚫 Медиа-сообщения не учитываются в статистике для чата {chat_id}, пропускаем (content_type={message.content_type})")
                return
        
        user_name = message.from_user.first_name or f"@{message.from_user.username}" if message.from_user.username else f"ID{message.from_user.id}"
        chat_name = message.chat.title or "Без названия"
        
        last_message_time_str = await db.get_user_last_message_time(chat_id, message.from_user.id)
        current_time = datetime.now()
        
        if last_message_time_str:
            try:
                last_message_time = datetime.fromisoformat(last_message_time_str)
                time_diff = (current_time - last_message_time).total_seconds()
                
                if time_diff < 0:
                    logger.warning(
                        f"⚠️ Некорректное время в БД для пользователя {user_name} ({message.from_user.id}) "
                        f"в чате \"{chat_name}\": время в БД ({last_message_time_str}) больше текущего. "
                        f"Обновляю время в БД."
                    )
                    await db.update_user_last_message_time(chat_id, message.from_user.id, current_time.isoformat())
                elif time_diff < 1:
                    logger.info(f"🚫 Сообщение пропущено от {user_name} ({message.from_user.id}) в чате \"{chat_name}\" (прошло {time_diff:.3f}с) - слишком быстро после предыдущего, статистика не засчитывается")
                    return
            except ValueError:
                logger.warning(f"Неверный формат времени: {last_message_time_str}")
        
        chat_info = await db.get_chat(chat_id)
        if not chat_info:
            owner_id = None
            try:
                admins = await bot.get_chat_administrators(chat_id)
                for admin in admins:
                    if admin.status == 'creator':
                        owner_id = admin.user.id
                        break
            except Exception:
                pass
            
            await db.add_chat(
                chat_id=chat_id,
                chat_title=message.chat.title or "Без названия",
                owner_id=owner_id
            )
        
        await db.add_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot
        )
        
        try:
            await db.increment_message_count(chat_id)
        except Exception as e:
            logger.error(f"Ошибка при increment_message_count для чата {chat_id}: {e}", exc_info=True)
        
        try:
            result2 = await db.increment_user_message_count(
                chat_id=chat_id,
                user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            if not result2:
                logger.warning(f"⚠️ increment_user_message_count вернул False для пользователя {message.from_user.id} в чате {chat_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка при increment_user_message_count для пользователя {message.from_user.id} в чате {chat_id}: {e}", exc_info=True)

        try:
            await db.ensure_user_first_seen(chat_id, message.from_user.id)
            await db.update_user_last_message_time(chat_id, message.from_user.id, current_time.isoformat())
            logger.info(f"✅ Обработано сообщение от {user_name} ({message.from_user.id}) в чате \"{chat_name}\"")
        except Exception as e:
            logger.error(f"Ошибка при обновлении метаданных пользователя {message.from_user.id} в чате {chat_id}: {e}", exc_info=True)
    else:
        logger.debug(f"message_handler: чат {message.chat.id} не является group/supergroup (тип: {message.chat.type}), пропускаем")


async def new_chat_member(message: Message):
    """Обработчик добавления бота в чат и проверка на массовое присоединение"""
    logger.info(f"Обработчик new_chat_member вызван для чата {message.chat.id}, новых участников: {len(message.new_chat_members)}")
    bot_member = None
    for member in message.new_chat_members:
        if member.id == bot.id:
            bot_member = member
            logger.info(f"Бот обнаружен в списке новых участников чата {message.chat.id}")
            break
    
    if not bot_member and message.chat.type in ['group', 'supergroup']:
        for member in message.new_chat_members:
            await raid_protection_db.add_recent_join(
                chat_id=message.chat.id,
                user_id=member.id,
                username=member.username,
                first_name=member.first_name,
                last_name=member.last_name
            )
            
            try:
                from handlers.moderation import restore_user_mutes
                await restore_user_mutes(message.chat.id, member.id)
            except Exception as e:
                logger.debug(f"Не удалось восстановить мут для пользователя {member.id} в чате {message.chat.id}: {e}")
        
        settings = await raid_protection_db.get_settings(message.chat.id)
        is_mass_join, recent_joins = await raid_protection.check_mass_join(message.chat.id, settings)
        
        if is_mass_join:
            chat_title = message.chat.title or "Без названия"
            await raid_protection.notify_owner(
                chat_id=message.chat.id,
                raid_type='mass_join',
                details=f"Обнаружено массовое присоединение в чате {chat_title}",
                recent_joins=recent_joins
            )
        
        return
    
    if not bot_member:
        return
    
    chat = message.chat
    
    owner_id = None
    if chat.type in ['group', 'supergroup']:
        try:
            admins = await bot.get_chat_administrators(chat.id)
            for admin in admins:
                if admin.status == 'creator':
                    owner_id = admin.user.id
                    break
        except Exception as e:
            logger.warning(f"Не удалось определить владельца чата {chat.id}: {e}")
    
    await db.add_chat(
        chat_id=chat.id,
        chat_title=chat.title or "Без названия",
        owner_id=owner_id
    )
    
    try:
        chat_info = await db.get_chat(chat.id)
        if chat_info and chat_info.get('frozen_at'):
            await db.unfreeze_chat(chat.id)
            logger.info(f"Чат {chat.id} разморожен после повторного добавления бота")
    except Exception as e:
        logger.warning(f"Ошибка при проверке/размораживании чата {chat.id}: {e}")
    
    has_admin = False
    try:
        has_admin = await check_admin_rights(bot, chat.id)
        logger.info(f"Бот добавлен в чат {chat.id} ({chat.title}). Права администратора: {has_admin}, Владелец: {owner_id}")
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора в new_chat_member для чата {chat.id}: {e}", exc_info=True)
        has_admin = False
    
    try:
        if has_admin:
            welcome_text = f"""
🫶 <b>{BOT_NAME}</b> добавлен в чат!

Привет! Меня зовут <b>{BOT_NAME}</b>, я очень рад что вы добавили меня в свою группу!
Если хотите выполнить быструю настройку, нажмите на кнопку "Настройки" и следуйте инструкциям.

<b>Доступные команды:</b>
• <code>/help</code> - справка по командам
• <code>/info</code> - информация о чате  
• <code>/settings</code> - настройки

🚀 Готов к работе! 
            """
            
            builder = InlineKeyboardBuilder()
            if owner_id:
                builder.add(InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data="initial_setup_start"
                ))
                builder.adjust(1)
            
            try:
                await send_message_with_gif(
                    message, 
                    welcome_text, 
                    "welcome", 
                    parse_mode=ParseMode.HTML,
                    reply_markup=builder.as_markup() if owner_id else None
                )
                logger.info(f"Приветственное сообщение отправлено в чат {chat.id} (с правами администратора)")
            except Exception as send_error:
                logger.error(f"Ошибка при отправке приветственного сообщения в чат {chat.id}: {send_error}", exc_info=True)
                try:
                    await bot.send_message(
                        chat_id=chat.id,
                        text=welcome_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=builder.as_markup() if owner_id else None
                    )
                    logger.info(f"Приветственное сообщение отправлено через bot.send_message в чат {chat.id}")
                except Exception as fallback_error:
                    logger.error(f"Критическая ошибка: не удалось отправить приветственное сообщение в чат {chat.id}: {fallback_error}", exc_info=True)
        else:
            welcome_text = f"""
🫶 <b>{BOT_NAME}</b> добавлен в чат!

⚠️ <b>Внимание!</b> Для полноценной работы в этом чате мне нужно выдать права администратора.

            """
            
            try:
                await send_message_with_gif(message, welcome_text, "welcome", parse_mode=ParseMode.HTML)
                logger.info(f"Приветственное сообщение отправлено в чат {chat.id} (без прав администратора)")
            except Exception as send_error:
                logger.error(f"Ошибка при отправке приветственного сообщения в чат {chat.id}: {send_error}", exc_info=True)
                try:
                    await bot.send_message(
                        chat_id=chat.id,
                        text=welcome_text,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info(f"Приветственное сообщение отправлено через bot.send_message в чат {chat.id}")
                except Exception as fallback_error:
                    logger.error(f"Критическая ошибка: не удалось отправить приветственное сообщение в чат {chat.id}: {fallback_error}", exc_info=True)
    except Exception as e:
        logger.error(f"Ошибка при отправке приветственного сообщения в чат {chat.id}: {e}", exc_info=True)


async def left_chat_member(message: Message):
    """Обработчик удаления бота из чата"""
    if message.left_chat_member.id == bot.id:
        chat_id = message.chat.id
        await db.deactivate_chat(chat_id)
        logger.info(f"Бот покинул чат {chat_id}, данные заморожены")


async def handle_chat_join_request(event: ChatJoinRequest):
    """Обработчик заявок на вступление"""
    try:
        chat_id = event.chat.id
        user_id = event.from_user.id
        
        try:
            enabled = await db.get_auto_accept_join_requests(chat_id)
            if not enabled:
                return
        except Exception as e:
            logger.error(f"Ошибка при проверке авто-принятия для чата {chat_id}: {e}")
            return
        
        try:
            await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        except Exception as e:
            logger.error(f"Ошибка при подтверждении заявки {user_id} в чат {chat_id}: {e}")
            return
        
        async def send_notification():
            try:
                notify_enabled = await db.get_auto_accept_notify(chat_id)
                if not notify_enabled:
                    return
                
                owner_id = await db.get_chat_owner(chat_id)
                if not owner_id:
                    return
                
                uname = event.from_user.username
                full_name = (event.from_user.first_name or "")
                if event.from_user.last_name:
                    full_name = f"{full_name} {event.from_user.last_name}".strip()
                user_label = f"@{uname}" if uname else (full_name or str(user_id))
                
                chat_info = await db.get_chat(chat_id)
                chat_title = (chat_info or {}).get('chat_title') or str(chat_id)
                await bot.send_message(owner_id, f"✅ Заявка одобрена: {user_label} в чат \"{chat_title}\"")
            except Exception as e:
                logger.debug(f"Ошибка при отправке уведомления о заявке: {e}")
        
        asyncio.create_task(send_notification())
        
    except Exception as e:
        logger.error(f"Ошибка при обработке заявки на вступление: {e}")


async def reaction_spam_handler(reaction_update: types.MessageReactionUpdated):
    """Обработчик спама реакциями"""
    try:
        chat_id = reaction_update.chat.id
        
        if reaction_update.chat.type not in ['group', 'supergroup']:
            return
        
        if not reaction_update.user:
            return
        
        user_id = reaction_update.user.id
        
        utilities_settings = await utilities_db.get_settings(chat_id)
        if not utilities_settings.get('reaction_spam_enabled', False):
            return
        
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ['administrator', 'creator']:
                return
        except Exception:
            pass
        
        message_id = getattr(reaction_update, 'message_id', None)
        await utilities_db.add_reaction_activity(chat_id, user_id, message_id)
        
        limit = utilities_settings.get('reaction_spam_limit', 5)
        window = utilities_settings.get('reaction_spam_window', 120)
        warning_enabled = utilities_settings.get('reaction_spam_warning_enabled', True)
        punishment = utilities_settings.get('reaction_spam_punishment', 'kick')
        ban_duration = utilities_settings.get('reaction_spam_ban_duration', 300)
        
        recent_reactions = await utilities_db.get_recent_reactions(chat_id, user_id, window)
        
        if len(recent_reactions) >= limit:
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                if member.status in ['kicked', 'left']:
                    logger.debug(f"Пользователь {user_id} уже не в чате {chat_id}, пропускаем наказание")
                    return
            except Exception as e:
                logger.debug(f"Не удалось получить статус пользователя {user_id} в чате {chat_id}, возможно уже исключен: {e}")
                return
            
            has_recent_punishment = await utilities_db.has_recent_punishment(chat_id, user_id, 60)
            if has_recent_punishment:
                logger.debug(f"Пропущено повторное наказание за спам реакциями для пользователя {user_id} в чате {chat_id} (уже наказан недавно)")
                return
            
            has_warning = await utilities_db.has_recent_warning(chat_id, user_id, window)
            
            # Проверяем настройку silent mode
            reaction_spam_silent = utilities_settings.get('reaction_spam_silent', False)
            
            if warning_enabled and not has_warning:
                try:
                    await utilities_db.add_reaction_warning(chat_id, user_id)
                    logger.info(f"Отправлено предупреждение за спам реакциями пользователю {user_id} в чате {chat_id}")
                    
                    # Отправляем сообщение в чат только если silent mode выключен
                    if not reaction_spam_silent:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ <b>Предупреждение</b>\n\n"
                                 f"Пользователь <b>{get_user_mention_html(reaction_update.user)}</b> "
                                 f"отправляет слишком много реакций. Пожалуйста, успокойтесь.",
                            parse_mode=ParseMode.HTML
                        )
                except Exception as e:
                    logger.error(f"Ошибка при отправке предупреждения за спам реакциями: {e}")
            else:
                await utilities_db.add_reaction_punishment(chat_id, user_id, punishment)
                
                try:
                    member_check = await bot.get_chat_member(chat_id, user_id)
                    if member_check.status in ['kicked', 'left']:
                        logger.debug(f"Пользователь {user_id} уже исключен другим обработчиком, пропускаем отправку сообщения")
                        return
                except Exception:
                    logger.debug(f"Пользователь {user_id} уже исключен, пропускаем отправку сообщения")
                    return
                
                try:
                    if punishment == 'kick':
                        active_mutes = await moderation_db.get_active_punishments(chat_id, "mute")
                        has_active_mutes = any(mute['user_id'] == user_id for mute in active_mutes)
                        
                        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
                        
                        if has_active_mutes:
                            from handlers.moderation import restore_user_mutes
                            await restore_user_mutes(chat_id, user_id)
                        
                        logger.info(f"Пользователь {user_id} исключен за спам реакциями в чате {chat_id}")
                        
                        # Отправляем сообщение в чат только если silent mode выключен
                        if not reaction_spam_silent:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"💨 Пользователь <b>{get_user_mention_html(reaction_update.user)}</b> "
                                     f"исключен за спам реакциями.",
                                parse_mode=ParseMode.HTML
                            )
                    elif punishment == 'ban':
                        # Проверяем, есть ли активные муты у пользователя (чтобы сохранить их)
                        active_mutes = await moderation_db.get_active_punishments(chat_id, "mute")
                        has_active_mutes = any(mute['user_id'] == user_id for mute in active_mutes)
                        
                        ban_until = datetime.now() + timedelta(seconds=ban_duration)
                        await bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=user_id,
                            until_date=ban_until
                        )
                        
                        # Сохраняем бан в базу данных
                        await moderation_db.add_punishment(
                            chat_id=chat_id,
                            user_id=user_id,
                            moderator_id=bot.id,
                            punishment_type="ban",
                            reason="Автоматический бан за спам реакциями",
                            duration_seconds=ban_duration,
                            expiry_date=ban_until.isoformat(),
                            user_username=reaction_update.user.username,
                            user_first_name=reaction_update.user.first_name,
                            user_last_name=reaction_update.user.last_name,
                            moderator_username=None,
                            moderator_first_name=BOT_NAME
                        )
                        
                        # Обновляем репутацию
                        penalty = reputation_db.calculate_reputation_penalty('ban', ban_duration)
                        await reputation_db.add_recent_punishment(user_id, 'ban', ban_duration)
                        await reputation_db.update_reputation(user_id, penalty)
                        
                        # Примечание: муты будут восстановлены автоматически когда пользователь вернется и отправит сообщение
                        # (см. message_handler, строки 1187-1191)
                        # Для временных банов это нормально, так как пользователь не может вернуться пока бан активен
                        
                        logger.info(f"Пользователь {user_id} забанен на {ban_duration} сек за спам реакциями в чате {chat_id} (активных мутов: {len([m for m in active_mutes if m['user_id'] == user_id])})")
                        
                        # Отправляем сообщение в чат только если silent mode выключен
                        if not reaction_spam_silent:
                            ban_duration_text = format_mute_duration(ban_duration)
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"🚫 Пользователь <b>{get_user_mention_html(reaction_update.user)}</b> "
                                     f"забанен на <b>{ban_duration_text}</b> за спам реакциями.",
                                parse_mode=ParseMode.HTML
                            )
                        
                        # Отправляем уведомление пользователю
                        try:
                            chat_info = await bot.get_chat(chat_id)
                            chat_title = chat_info.title or "Неизвестный чат"
                            
                            builder = InlineKeyboardBuilder()
                            
                            if chat_info.username:
                                chat_url = f"https://t.me/{chat_info.username}"
                            else:
                                chat_id_str = str(chat_id)
                                if chat_id_str.startswith('-100'):
                                    chat_id_str = chat_id_str[4:]
                                chat_url = f"https://t.me/c/{chat_id_str}"
                            
                            builder.add(InlineKeyboardButton(
                                text="💬 Открыть чат",
                                url=chat_url
                            ))
                            
                            ban_duration_text = format_mute_duration(ban_duration)
                            await bot.send_message(
                                user_id,
                                f"🚫 <b>Вы были забанены</b>\n\n"
                                f"В чате <b>{chat_title}</b> вы получили временный бан на <b>{ban_duration_text}</b> за спам реакциями.",
                                parse_mode=ParseMode.HTML,
                                reply_markup=builder.as_markup()
                            )
                        except Exception as e:
                            error_str = str(e).lower()
                            # Ошибка "bot can't initiate conversation" - пользователь не писал боту или заблокировал его
                            if "can't initiate conversation" in error_str or "forbidden" in error_str:
                                logger.debug(f"Не удалось отправить уведомление пользователю {user_id}: пользователь не писал боту или заблокировал его")
                            else:
                                logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
                except Exception as e:
                    logger.error(f"Ошибка при применении наказания за спам реакциями: {e}")
    except Exception as e:
        logger.error(f"Ошибка в reaction_spam_handler: {e}")


async def handle_my_chat_member(update: ChatMemberUpdated):
    """Обработчик изменения статуса бота"""
    try:
        if update.new_chat_member and update.new_chat_member.user and update.new_chat_member.user.id == (await bot.get_me()).id:
            chat_id = update.chat.id
            if await db.is_chat_blacklisted(chat_id):
                try:
                    await bot.leave_chat(chat_id)
                except Exception as leave_err:
                    logger.error(f"Не удалось покинуть зачерненный чат {chat_id}: {leave_err}")
                return
            
            old_status = update.old_chat_member.status if update.old_chat_member else None
            new_status = update.new_chat_member.status
            
            if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator', 'restricted']:
                logger.debug(f"Бот только что добавлен в чат {chat_id}, пропускаем обработку в handle_my_chat_member (new_chat_member обработает)")
                return
            
            if new_status in ['kicked', 'left']:
                await db.deactivate_chat(chat_id)
                logger.info(f"Бот был удален из чата {chat_id} (статус: {new_status}), данные заморожены")
                return
            
            # Проверяем, что бот только что получил права администратора после реального добавления в чат
            # (старый статус был 'left' или 'kicked'), а не просто изменились права
            if old_status in ['left', 'kicked'] and new_status == 'administrator':
                owner_id = None
                if update.chat.type in ['group', 'supergroup']:
                    try:
                        admins = await bot.get_chat_administrators(chat_id)
                        for admin in admins:
                            if admin.status == 'creator':
                                owner_id = admin.user.id
                                break
                    except Exception as e:
                        logger.warning(f"Не удалось определить владельца чата {chat_id}: {e}")
                
                welcome_text = f"""
🫶 <b>{BOT_NAME}</b> добавлен в чат!

Привет! Меня зовут <b>{BOT_NAME}</b>, я очень рад что вы добавили меня в свою группу!
Если хотите выполнить быструю настройку, нажмите на кнопку "Настройки" и следуйте инструкциям.

<b>Доступные команды:</b>
• <code>/help</code> - справка по командам
• <code>/info</code> - информация о чате  
• <code>/settings</code> - настройки

🚀 Готов к работе! 
                """
                
                builder = InlineKeyboardBuilder()
                if owner_id:
                    builder.add(InlineKeyboardButton(
                        text="⚙️ Настройки",
                        callback_data="initial_setup_start"
                    ))
                    builder.adjust(1)
                
                try:
                    from utils.gifs import send_message_with_gif
                    await bot.send_message(
                        chat_id=chat_id,
                        text=welcome_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=builder.as_markup() if owner_id else None
                    )
                    logger.info(f"Приветственное сообщение отправлено в чат {chat_id} (получены права администратора)")
                except Exception as send_error:
                    logger.error(f"Ошибка при отправке приветственного сообщения в чат {chat_id}: {send_error}", exc_info=True)
    except Exception as e:
        logger.error(f"Ошибка в handle_my_chat_member: {e}")

