"""
Обработчики команды /userinfo для просмотра информации о пользователе
"""
import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ParseMode

from databases.database import db
from databases.moderation_db import moderation_db
from utils.permissions import get_effective_rank
from utils.formatting import get_user_mention_html, format_mute_duration
from utils.constants import RANK_NAMES
from handlers.common import parse_user_from_args

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def get_rank_name(rank: int) -> str:
    """Получить название ранга"""
    return RANK_NAMES.get(rank, ("Неизвестно",))[0]


def format_status_name(status: str) -> str:
    """Форматирует статус пользователя в чате для отображения"""
    status_map = {
        'member': 'Участник',
        'administrator': 'Администратор',
        'creator': 'Владелец',
        'restricted': 'Ограничен',
        'banned': 'Забанен',
        'left': 'Покинул чат',
        'kicked': 'Исключен'
    }
    return status_map.get(status, status)


async def userinfo_command(message: Message):
    """Команда просмотра информации о пользователе"""
    chat_id = message.chat.id
    is_private = message.chat.type == 'private'
    
    # Проверяем, включена ли команда userinfo в настройках (только для групп)
    if not is_private:
        from databases.database import db
        stat_settings = await db.get_chat_stat_settings(chat_id)
        if not stat_settings.get('userinfo_enabled', True):
            await message.answer("❌ Команда /userinfo отключена в настройках чата.")
            return
    
    target_user = None
    
    # Парсинг пользователя: reply, mention или аргумент
    # В ЛС можно просматривать информацию только о себе
    if is_private:
        # В ЛС игнорируем все аргументы и reply - показываем только информацию о себе
        target_user = message.from_user
    else:
        # В группах/супергруппах - обычная логика
        if message.reply_to_message:
            if message.reply_to_message.from_user:
                target_user = message.reply_to_message.from_user
        elif message.text and len(message.text.split()) > 1:
            args = message.text.split()
            target_user = await parse_user_from_args(message, args, 1)
            
            if not target_user:
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/userinfo</code> (при ответе на сообщение)\n"
                    "• <code>/userinfo @username</code>",
                    parse_mode=ParseMode.HTML
                )
                return
        else:
            # Если нет аргументов и нет reply, показываем информацию о себе
            target_user = message.from_user
    
    if not target_user:
        await message.answer("❌ Не удалось определить пользователя")
        return
    
    user_id = target_user.id
    
    # Получаем количество фото профиля
    profile_photos_count = 0
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos:
            profile_photos_count = photos.total_count
    except Exception as e:
        logger.debug(f"Не удалось получить фото профиля для пользователя {user_id}: {e}")
    
    # Собираем данные из Telegram API
    telegram_data = {}
    telegram_data['profile_photos_count'] = profile_photos_count
    
    # В ЛС используем get_chat вместо get_chat_member
    if is_private:
        try:
            chat_info = await bot.get_chat(user_id)
            telegram_data['user'] = target_user
            telegram_data['status'] = 'private_chat'
            # В ЛС нет статуса в чате, но можем получить базовую информацию
            if hasattr(chat_info, 'type'):
                if chat_info.type == 'private':
                    telegram_data['status'] = 'private_user'
                elif chat_info.type == 'bot':
                    telegram_data['status'] = 'bot'
        except Exception as e:
            logger.error(f"Ошибка при получении данных из Telegram API для пользователя {user_id} в ЛС: {e}")
            telegram_data['error'] = str(e)
            telegram_data['user'] = target_user
            telegram_data['status'] = 'unknown'
    else:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            
            telegram_data['status'] = member.status
            telegram_data['user'] = member.user
            
            # Дополнительная информация в зависимости от статуса
            if hasattr(member, 'joined_date') and member.joined_date:
                telegram_data['joined_date'] = member.joined_date
            
            if member.status == 'restricted':
                if hasattr(member, 'permissions') and member.permissions:
                    telegram_data['permissions'] = member.permissions
                if hasattr(member, 'until_date'):
                    # Проверяем, что until_date не None и не 0 (бессрочное ограничение)
                    until_date = member.until_date
                    if until_date and until_date != 0:
                        # Проверяем, что это не очень старая дата (например, 1970)
                        if isinstance(until_date, datetime):
                            if until_date.year > 1970:
                                telegram_data['until_date'] = until_date
                        elif isinstance(until_date, int):
                            # Если это timestamp, проверяем что он разумный
                            if until_date > 0:
                                try:
                                    dt = datetime.fromtimestamp(until_date)
                                    if dt.year > 1970:
                                        telegram_data['until_date'] = dt
                                except (ValueError, OSError):
                                    pass
                    else:
                        # Бессрочное ограничение
                        telegram_data['until_date'] = None
            
            if member.status == 'administrator' or member.status == 'creator':
                if hasattr(member, 'can_be_edited'):
                    telegram_data['can_be_edited'] = member.can_be_edited
                if hasattr(member, 'can_manage_chat'):
                    telegram_data['can_manage_chat'] = member.can_manage_chat
                if hasattr(member, 'can_delete_messages'):
                    telegram_data['can_delete_messages'] = member.can_delete_messages
                if hasattr(member, 'can_manage_video_chats'):
                    telegram_data['can_manage_video_chats'] = member.can_manage_video_chats
                if hasattr(member, 'can_restrict_members'):
                    telegram_data['can_restrict_members'] = member.can_restrict_members
                if hasattr(member, 'can_promote_members'):
                    telegram_data['can_promote_members'] = member.can_promote_members
                if hasattr(member, 'can_change_info'):
                    telegram_data['can_change_info'] = member.can_change_info
                if hasattr(member, 'can_invite_users'):
                    telegram_data['can_invite_users'] = member.can_invite_users
                if hasattr(member, 'can_post_messages'):
                    telegram_data['can_post_messages'] = member.can_post_messages
                if hasattr(member, 'can_edit_messages'):
                    telegram_data['can_edit_messages'] = member.can_edit_messages
                if hasattr(member, 'can_pin_messages'):
                    telegram_data['can_pin_messages'] = member.can_pin_messages
                if hasattr(member, 'can_manage_topics'):
                    telegram_data['can_manage_topics'] = member.can_manage_topics
                if hasattr(member, 'is_anonymous'):
                    telegram_data['is_anonymous'] = member.is_anonymous
                # Новые права для историй
                if hasattr(member, 'can_post_stories'):
                    telegram_data['can_post_stories'] = member.can_post_stories
                if hasattr(member, 'can_edit_stories'):
                    telegram_data['can_edit_stories'] = member.can_edit_stories
                if hasattr(member, 'can_delete_stories'):
                    telegram_data['can_delete_stories'] = member.can_delete_stories
                # Кастомный титул администратора
                if hasattr(member, 'custom_title') and member.custom_title:
                    telegram_data['custom_title'] = member.custom_title
        except Exception as e:
            error_str = str(e).lower()
            # Если пользователь не в чате, это нормально - покажем данные из БД
            if "user not found" in error_str or "chat not found" in error_str or "not a member" in error_str:
                logger.debug(f"Пользователь {user_id} не найден в чате {chat_id} или не является участником")
                telegram_data['status'] = 'not_in_chat'
                telegram_data['user'] = target_user
            else:
                logger.error(f"Ошибка при получении данных из Telegram API для пользователя {user_id} в чате {chat_id}: {e}")
                telegram_data['error'] = str(e)
                telegram_data['user'] = target_user
    
    # Собираем данные из базы данных (только для групп/супергрупп)
    db_data = {}
    if not is_private:
        try:
            # Первое появление
            first_seen = await db.get_user_first_seen(chat_id, user_id)
            db_data['first_seen'] = first_seen
            
            # Ранг
            rank = await get_effective_rank(chat_id, user_id)
            db_data['rank'] = rank
            
            # Варны
            warn_count = await moderation_db.get_user_warn_count(chat_id, user_id)
            db_data['warn_count'] = warn_count
            
            # Активные наказания
            active_punishments = await moderation_db.get_active_punishments(chat_id)
            user_punishments = [p for p in active_punishments if p.get('user_id') == user_id]
            db_data['active_punishments'] = user_punishments
            
            # Статистика
            today = datetime.now().strftime('%Y-%m-%d')
            today_stats = await db.get_user_daily_stats(chat_id, user_id, today)
            db_data['today_count'] = today_stats.get('message_count', 0) if today_stats else 0
            
            monthly_stats = await db.get_user_30d_stats(chat_id, user_id)
            total_monthly = sum(day.get('message_count', 0) for day in monthly_stats)
            db_data['monthly_count'] = total_monthly
        except Exception as e:
            logger.error(f"Ошибка при получении данных из БД для пользователя {user_id} в чате {chat_id}: {e}")
            db_data['error'] = str(e)
    
    # Форматируем вывод
    user_display = get_user_mention_html(target_user)
    
    # Определяем, бот это или пользователь
    is_bot = target_user.is_bot if target_user else False
    entity_type = "Боте" if is_bot else "пользователе"
    emoji = "🤖" if is_bot else "👤"
    
    text = f"{emoji} <b>Информация о {entity_type}:</b> {user_display}\n\n"
    
    # Секция Telegram API
    text += "📱 <b>Telegram API:</b>\n"
    
    if 'error' in telegram_data:
        text += f"• ❌ Ошибка получения данных: {telegram_data['error']}\n"
    else:
        user = telegram_data.get('user', target_user)
        
        text += f"• ID: <code>{user.id}</code>\n"
        
        if user.username:
            text += f"• Username: @{user.username}\n"
        
        if user.first_name:
            text += f"• Имя: {user.first_name}\n"
        
        if user.last_name:
            text += f"• Фамилия: {user.last_name}\n"
        
        text += f"• Бот: {'Да' if user.is_bot else 'Нет'}\n"
        
        if hasattr(user, 'is_premium'):
            text += f"• Premium: {'Да' if user.is_premium else 'Нет'}\n"
        
        if user.language_code:
            text += f"• Язык: {user.language_code}\n"
        
        # Дополнительные поля User
        if hasattr(user, 'added_to_attachment_menu') and user.added_to_attachment_menu:
            text += "• Добавлен в меню вложений: Да\n"
        
        if user.is_bot:
            if hasattr(user, 'can_join_groups'):
                text += f"• Может присоединяться к группам: {'Да' if user.can_join_groups else 'Нет'}\n"
            if hasattr(user, 'can_read_all_group_messages'):
                text += f"• Может читать все сообщения: {'Да' if user.can_read_all_group_messages else 'Нет'}\n"
            if hasattr(user, 'supports_inline_queries'):
                text += f"• Поддерживает inline-запросы: {'Да' if user.supports_inline_queries else 'Нет'}\n"
        
        # Количество фото профиля
        if telegram_data.get('profile_photos_count', 0) > 0:
            text += f"• Фото профиля: {telegram_data['profile_photos_count']}\n"
        
        status = telegram_data.get('status', 'unknown')
        if is_private:
            if status == 'private_user':
                text += "• Тип: Пользователь\n"
            elif status == 'bot':
                text += "• Тип: Бот\n"
            else:
                text += "• Тип: Неизвестно\n"
        else:
            if status == 'not_in_chat':
                text += "• Статус в чате: Не в чате (данные недоступны через API)\n"
            else:
                text += f"• Статус в чате: {format_status_name(status)}\n"
        
        if 'joined_date' in telegram_data:
            try:
                joined_date = telegram_data['joined_date']
                if isinstance(joined_date, datetime):
                    formatted_date = joined_date.strftime('%d.%m.%Y %H:%M')
                else:
                    formatted_date = str(joined_date)
                text += f"• Дата присоединения: {formatted_date}\n"
            except Exception:
                pass
        
        # Детальная информация для restricted пользователей
        if status == 'restricted':
            if 'until_date' in telegram_data:
                until_date = telegram_data['until_date']
                if until_date:
                    try:
                        if isinstance(until_date, datetime):
                            formatted_date = until_date.strftime('%d.%m.%Y %H:%M')
                        else:
                            formatted_date = str(until_date)
                        text += f"• Ограничен до: {formatted_date}\n"
                    except Exception:
                        pass
                else:
                    text += "• Ограничен до: Бессрочно\n"
            
            # Детальные permissions для restricted
            if 'permissions' in telegram_data:
                perms = telegram_data['permissions']
                text += "\n<b>Ограничения:</b>\n"
                restricted_perms = []
                
                if hasattr(perms, 'can_send_messages'):
                    restricted_perms.append(f"Сообщения: {'✅' if perms.can_send_messages else '❌'}")
                if hasattr(perms, 'can_send_audios'):
                    restricted_perms.append(f"Аудио: {'✅' if perms.can_send_audios else '❌'}")
                if hasattr(perms, 'can_send_documents'):
                    restricted_perms.append(f"Документы: {'✅' if perms.can_send_documents else '❌'}")
                if hasattr(perms, 'can_send_photos'):
                    restricted_perms.append(f"Фото: {'✅' if perms.can_send_photos else '❌'}")
                if hasattr(perms, 'can_send_videos'):
                    restricted_perms.append(f"Видео: {'✅' if perms.can_send_videos else '❌'}")
                if hasattr(perms, 'can_send_video_notes'):
                    restricted_perms.append(f"Видеосообщения: {'✅' if perms.can_send_video_notes else '❌'}")
                if hasattr(perms, 'can_send_voice_notes'):
                    restricted_perms.append(f"Голосовые: {'✅' if perms.can_send_voice_notes else '❌'}")
                if hasattr(perms, 'can_send_polls'):
                    restricted_perms.append(f"Опросы: {'✅' if perms.can_send_polls else '❌'}")
                if hasattr(perms, 'can_send_other_messages'):
                    restricted_perms.append(f"Другие сообщения: {'✅' if perms.can_send_other_messages else '❌'}")
                if hasattr(perms, 'can_add_web_page_previews'):
                    restricted_perms.append(f"Превью ссылок: {'✅' if perms.can_add_web_page_previews else '❌'}")
                if hasattr(perms, 'can_change_info'):
                    restricted_perms.append(f"Изменение информации: {'✅' if perms.can_change_info else '❌'}")
                if hasattr(perms, 'can_invite_users'):
                    restricted_perms.append(f"Приглашение: {'✅' if perms.can_invite_users else '❌'}")
                if hasattr(perms, 'can_pin_messages'):
                    restricted_perms.append(f"Закрепление: {'✅' if perms.can_pin_messages else '❌'}")
                if hasattr(perms, 'can_manage_topics'):
                    restricted_perms.append(f"Управление топиками: {'✅' if perms.can_manage_topics else '❌'}")
                
                if restricted_perms:
                    text += "• " + " | ".join(restricted_perms) + "\n"
        
        # Права администратора
        if status in ['administrator', 'creator']:
            # Кастомный титул
            if 'custom_title' in telegram_data:
                text += f"• Титул: {telegram_data['custom_title']}\n"
            
            admin_perms = []
            if telegram_data.get('can_manage_chat'):
                admin_perms.append("Управление чатом")
            if telegram_data.get('can_delete_messages'):
                admin_perms.append("Удаление сообщений")
            if telegram_data.get('can_manage_video_chats'):
                admin_perms.append("Управление видеозвонками")
            if telegram_data.get('can_restrict_members'):
                admin_perms.append("Ограничение участников")
            if telegram_data.get('can_promote_members'):
                admin_perms.append("Повышение участников")
            if telegram_data.get('can_change_info'):
                admin_perms.append("Изменение информации")
            if telegram_data.get('can_invite_users'):
                admin_perms.append("Приглашение пользователей")
            if telegram_data.get('can_pin_messages'):
                admin_perms.append("Закрепление сообщений")
            if telegram_data.get('can_manage_topics'):
                admin_perms.append("Управление топиками")
            if telegram_data.get('is_anonymous'):
                admin_perms.append("Анонимный")
            # Новые права для историй
            if telegram_data.get('can_post_stories'):
                admin_perms.append("Публикация историй")
            if telegram_data.get('can_edit_stories'):
                admin_perms.append("Редактирование историй")
            if telegram_data.get('can_delete_stories'):
                admin_perms.append("Удаление историй")
            if telegram_data.get('can_be_edited'):
                admin_perms.append("Может быть отредактирован")
            
            # Показываем секцию только если есть права для отображения
            if admin_perms:
                text += "\n<b>Права администратора:</b>\n"
                text += "• " + ", ".join(admin_perms) + "\n"
    
    # Секция База данных (только для пользователей, не для ботов)
    if not is_bot:
        text += "\n📊 <b>База данных:</b>\n"
        
        if 'error' in db_data:
            text += f"• ❌ Ошибка получения данных: {db_data['error']}\n"
        else:
            if db_data.get('first_seen'):
                try:
                    first_seen = db_data['first_seen']
                    if isinstance(first_seen, str):
                        try:
                            date_obj = datetime.strptime(first_seen, '%Y-%m-%d')
                            formatted_date = date_obj.strftime('%d.%m.%Y')
                        except:
                            formatted_date = first_seen
                    else:
                        formatted_date = str(first_seen)
                    text += f"• В чате с: {formatted_date}\n"
                except Exception:
                    pass
            else:
                text += "• В чате с: Неизвестно (пользователь не был в чате)\n"
            
            rank = db_data.get('rank')
            if rank:
                rank_name = get_rank_name(rank)
                text += f"• Ранг: {rank_name} (ранг {rank})\n"
            
            warn_count = db_data.get('warn_count', 0)
            if warn_count > 0:
                text += f"• Варны: {warn_count}\n"
            
            active_punishments = db_data.get('active_punishments', [])
            if active_punishments:
                punishment_texts = []
                for punishment in active_punishments:
                    p_type = punishment.get('punishment_type', 'unknown')
                    p_type_names = {
                        'ban': 'Бан',
                        'mute': 'Мут',
                        'warn': 'Варн',
                        'kick': 'Кик'
                    }
                    p_name = p_type_names.get(p_type, p_type)
                    
                    expiry_date = punishment.get('expiry_date')
                    if expiry_date:
                        try:
                            if isinstance(expiry_date, str):
                                date_obj = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
                            else:
                                date_obj = expiry_date
                            formatted_date = date_obj.strftime('%d.%m.%Y %H:%M')
                            punishment_texts.append(f"{p_name} (до {formatted_date})")
                        except Exception:
                            duration = punishment.get('duration_seconds')
                            if duration:
                                duration_str = format_mute_duration(duration)
                                punishment_texts.append(f"{p_name} ({duration_str})")
                            else:
                                punishment_texts.append(p_name)
                    else:
                        duration = punishment.get('duration_seconds')
                        if duration:
                            duration_str = format_mute_duration(duration)
                            punishment_texts.append(f"{p_name} ({duration_str})")
                        else:
                            punishment_texts.append(p_name)
                
                if punishment_texts:
                    text += f"• Активные наказания: {', '.join(punishment_texts)}\n"
            else:
                text += "• Активные наказания: Нет\n"
            
            today_count = db_data.get('today_count', 0)
            text += f"• Сообщений сегодня: {today_count}\n"
            
            monthly_count = db_data.get('monthly_count', 0)
            text += f"• Сообщений за месяц: {monthly_count}\n"
    
    await message.answer(text, parse_mode=ParseMode.HTML)


def register_userinfo_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков команды /userinfo"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # Регистрируем команду
    dp.message.register(userinfo_command, Command("userinfo", "ui"))

