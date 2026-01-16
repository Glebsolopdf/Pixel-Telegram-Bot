"""
Обработчики команд топ чатов и статистики
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from databases.database import db
from config import TOP_CHATS_DEFAULTS
from utils.permissions import get_effective_rank
from utils.formatting import get_user_mention_html
from utils.image_generator import generate_top_chart
from handlers.common import require_admin_rights, safe_answer_callback

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None

def get_top_chat_settings(chat_id: int) -> dict:
    """Получить настройки показа в топе для чата (из БД)"""
    try:
        # Используем синхронный вызов через asyncio для совместимости
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Если цикл уже запущен, создаем задачу
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: asyncio.run(db.get_top_chat_settings(chat_id)))
                return future.result()
        else:
            return loop.run_until_complete(db.get_top_chat_settings(chat_id))
    except Exception as e:
        logger.error(f"Ошибка при получении настроек топа чата {chat_id}: {e}")
        return TOP_CHATS_DEFAULTS.copy()


async def get_top_chat_settings_async(chat_id: int) -> dict:
    """Получить настройки показа в топе для чата (асинхронная версия)"""
    try:
        return await db.get_top_chat_settings(chat_id)
    except Exception as e:
        logger.error(f"Ошибка при получении настроек топа чата {chat_id}: {e}")
        return TOP_CHATS_DEFAULTS.copy()


def set_top_chat_settings(chat_id: int, settings: dict) -> bool:
    """Сохранить настройки показа в топе для чата (в БД)"""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Если цикл уже запущен, создаем задачу
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: asyncio.run(db.update_top_chat_settings(chat_id, settings)))
                return future.result()
        else:
            return loop.run_until_complete(db.update_top_chat_settings(chat_id, settings))
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек топа чата {chat_id}: {e}")
        return False


async def set_top_chat_settings_async(chat_id: int, settings: dict) -> bool:
    """Сохранить настройки показа в топе для чата (асинхронная версия)"""
    try:
        return await db.update_top_chat_settings(chat_id, settings)
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек топа чата {chat_id}: {e}")
        return False


def register_top_chats_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков команд топ чатов"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # Команды
    dp.message.register(top_users_command, Command("top"))
    dp.message.register(top_users_all_chats_command, Command("topall"))
    
    # Callbacks
    dp.callback_query.register(top_chats_callback, F.data == "top_chats")
    dp.callback_query.register(join_chat_callback, F.data.startswith("join_chat_"))


async def get_top_chats_with_settings(days: int = 3, limit: int = 30) -> List[Dict[str, Any]]:
    """Получает топ чатов с учетом настроек показа в топе"""
    all_chats = await db.get_top_chats_by_activity(
        days=days, 
        limit=limit * 3,
        exclude_chat_ids=None,
        include_private=True,
        min_activity_threshold=0  # Не используется, но оставляем для совместимости с БД
    )
    
    filtered_chats = []
    
    for chat in all_chats:
        settings = await get_top_chat_settings_async(chat['chat_id'])
        show_in_top = settings.get('show_in_top', 'public_only')
        
        if show_in_top == 'never':
            continue
        
        if show_in_top == 'public_only' and not chat.get('is_public', False):
            continue
        
        filtered_chats.append(chat)
        
        if len(filtered_chats) >= limit:
            break
    
    return filtered_chats


@require_admin_rights
async def top_users_command(message: Message):
    """Обработчик команды /top - топ активных пользователей за сегодня"""
    chat = message.chat
    user = message.from_user
    
    stat_settings = await db.get_chat_stat_settings(chat.id)
    if not stat_settings['stats_enabled']:
        await message.answer("Статистика отключена для этого чата")
        return
    
    # Дата по московскому времени (UTC+3)
    ts = datetime.utcnow().timestamp() + (3 * 3600)
    today_for_query = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
    today_for_display = datetime.utcfromtimestamp(ts).strftime('%d.%m.%Y')
    logger.info(f"Команда /top в чате {chat.id}: ищем статистику за дату {today_for_query}")
    
    top_users = await db.get_top_users_today(chat.id, 20, 3)
    
    logger.info(f"Команда /top в чате {chat.id}: получено {len(top_users) if top_users else 0} пользователей")
    
    # Проверяем, есть ли данные за сегодня (только для отладки, если нужно)
    # all_stats = await db.get_daily_stats(chat.id, 2)  # Получаем последние 2 дня для проверки
    # if all_stats:
    #     latest_stat_date = all_stats[0]['date']
    #     if latest_stat_date != today_for_query:
    #         logger.warning(f"Статистика показывает данные за {latest_stat_date}, а сегодня {today_for_query}")
    
    if not top_users:
        # Получаем статистику для логирования только если нужно
        all_stats = await db.get_daily_stats(chat.id, 2)
        logger.info(f"Всего записей статистики для чата {chat.id}: {len(all_stats) if all_stats else 0}")
        if all_stats:
            logger.info(f"Последняя запись статистики: дата={all_stats[0]['date']}, сообщений={all_stats[0]['message_count']}")
        
        await message.answer(
            "📊 <b>Топ активных пользователей</b>\n\n"
            "• Данных за сегодня пока нет\n"
            "• Отправьте несколько сообщений для начала статистики",
            parse_mode=ParseMode.HTML
        )
        return
    
    today = today_for_display
    
    top_text = f"📊 <b>Статистика активности по сообщениям за сутки - {today}</b>\n\n"
    total_messages = 0
    for i, user_data in enumerate(top_users, 1):
        user_ping_enabled = await db.get_user_mention_ping_enabled(user_data['user_id'])
        user_name = get_user_mention_html(user_data, enable_link=user_ping_enabled)
        top_text += f"{i}. {user_name} - {user_data['message_count']} сообщений\n"
        total_messages += user_data['message_count']
    top_text += f"\n💬 <b>Всего сообщений: {total_messages}</b>"
    
    try:
        title = f"Топ активных участников - {today}"
        subtitle = "За сутки"
        chart_buf = await generate_top_chart(top_users, title=title, subtitle=subtitle, bot_instance=bot)
        
        chart_bytes = chart_buf.read()
        chart_buf.seek(0)
        
        try:
            photo_params = {
                'photo': types.input_file.BufferedInputFile(chart_bytes, filename="top_users.png"),
                'caption': top_text,
                'parse_mode': ParseMode.HTML,
                'disable_web_page_preview': True
            }
            if message.chat.type == 'supergroup' and message.message_thread_id:
                photo_params['message_thread_id'] = message.message_thread_id
            
            await message.answer_photo(**photo_params)
        except Exception as photo_error:
            if "TOPIC_CLOSED" in str(photo_error):
                logger.warning(f"Топик закрыт, отправляем только текст: {photo_error}")
                try:
                    await message.answer(top_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    logger.error(f"Не удалось отправить сообщение в закрытый топик")
            else:
                raise photo_error
    except Exception as e:
        logger.error(f"Ошибка при генерации графика активности для /top: {e}")
        try:
            await message.answer(top_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as text_error:
            if "TOPIC_CLOSED" in str(text_error):
                logger.warning(f"Топик закрыт, невозможно отправить сообщение")


@require_admin_rights
async def top_users_all_chats_command(message: Message):
    """Топ пользователей за последние 60 дней для текущего чата"""
    try:
        chat = message.chat
        stat_settings = await db.get_chat_stat_settings(chat.id)
        if not stat_settings['stats_enabled']:
            await message.answer("Статистика отключена для этого чата")
            return

        days = 60
        limit = 20  # Ограничиваем до 20 для подписи (лимит Telegram 1024 символа)
        top_users = await db.get_top_users_last_days(chat.id, days=days, limit=limit)
        if not top_users:
            await message.answer(
                "📊 <b>Статистика за 60 дней</b>\n\n"
                "• Данных пока нет",
                parse_mode=ParseMode.HTML
            )
            return

        for user_data in top_users:
            fresh_user_data = await db.get_user(user_data['user_id'])
            if fresh_user_data:
                user_data['username'] = fresh_user_data.get('username')
                user_data['first_name'] = fresh_user_data.get('first_name')
                user_data['last_name'] = fresh_user_data.get('last_name')
        
        header = f"📊 <b>Статистика активности за {days} дней — этот чат</b>\n\n"
        lines = []
        total_messages = 0
        for i, user_data in enumerate(top_users, start=1):
            user_ping_enabled = await db.get_user_mention_ping_enabled(user_data['user_id'])
            user_name = get_user_mention_html(user_data, enable_link=user_ping_enabled)
            lines.append(f"{i}. {user_name} — {user_data['message_count']} сообщений")
            total_messages += user_data['message_count']
        footer = f"\n\n💬 <b>Всего сообщений: {total_messages}</b>"
        text_message = header + "\n".join(lines) + footer
        
        try:
            title = f"Топ активных участников за {days} дней"
            subtitle = f"За последние {days} дней — этот чат"
            chart_buf = await generate_top_chart(top_users, title=title, subtitle=subtitle, bot_instance=bot)
            
            try:
                chart_bytes = chart_buf.read()
                chart_buf.seek(0)
                
                photo_params = {
                    'photo': types.input_file.BufferedInputFile(chart_bytes, filename="topall_users.png"),
                    'caption': text_message,
                    'parse_mode': ParseMode.HTML,
                    'disable_web_page_preview': True
                }
                if message.chat.type == 'supergroup' and message.message_thread_id:
                    photo_params['message_thread_id'] = message.message_thread_id
                
                await message.answer_photo(**photo_params)
            except Exception as photo_error:
                if "TOPIC_CLOSED" in str(photo_error):
                    logger.warning(f"Топик закрыт, отправляем только текст")
                    try:
                        text_params = {
                            'text': text_message,
                            'parse_mode': ParseMode.HTML,
                            'disable_web_page_preview': True
                        }
                        if message.chat.type == 'supergroup' and message.message_thread_id:
                            text_params['message_thread_id'] = message.message_thread_id
                        
                        await message.answer(**text_params)
                    except Exception:
                        logger.error(f"Не удалось отправить сообщение в закрытый топик")
                else:
                    raise photo_error
        except Exception as e:
            logger.error(f"Ошибка при генерации графика топ участников для /topall: {e}")
            try:
                text_params = {
                    'text': text_message,
                    'parse_mode': ParseMode.HTML,
                    'disable_web_page_preview': True
                }
                if message.chat.type == 'supergroup' and message.message_thread_id:
                    text_params['message_thread_id'] = message.message_thread_id
                
                await message.answer(**text_params)
            except Exception as text_error:
                if "TOPIC_CLOSED" in str(text_error):
                    logger.warning(f"Топик закрыт, невозможно отправить сообщение")
    except Exception as e:
        logger.error(f"Ошибка в top_users_all_chats_command: {e}")
        try:
            await message.answer("❌ Произошла ошибка при получении статистики")
        except Exception:
            pass


async def top_chats_callback(callback: CallbackQuery):
    """Обработчик кнопки 'Топ чатов'"""
    try:
        top_chats = await get_top_chats_with_settings(days=3, limit=15)
        
        if not top_chats:
            await safe_answer_callback(callback, "😔 Пока нет активных чатов")
            await callback.message.edit_text(
                "😔 <b>Топ чатов</b>\n\n"
                "К сожалению, пока нет достаточно активных чатов для составления рейтинга.\n\n"
                "Добавьте бота в больше чатов и подождите накопления статистики!",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
                ).as_markup()
            )
            return
        
        top_text = "🏆 <b>Топ 15 чатов</b>\n"
        top_text += f"<i>За последние 3 дня</i>\n\n"
        
        total_messages = sum(chat['total_messages'] for chat in top_chats)
        top_text += f"<b>Всего сообщений: {total_messages}</b>\n\n"
        
        top_text += "📋 <b>Список чатов:</b>\n"
        for i, chat in enumerate(top_chats, 1):
            title = chat['title'][:30] + "..." if len(chat['title']) > 30 else chat['title']
            messages_count = chat['total_messages']
            top_text += f"{i}. {title} - {messages_count} сообщений\n"
        
        top_text += "\n<i>Выберите чат для просмотра:</i>"
        
        builder = InlineKeyboardBuilder()
        
        for i, chat in enumerate(top_chats, 1):
            title = chat['title'][:25] + "..." if len(chat['title']) > 25 else chat['title']
            builder.add(InlineKeyboardButton(
                text=f"{i}. {title}",
                callback_data=f"join_chat_{chat['chat_id']}"
            ))
        
        # Размещаем кнопки чатов по 2 в ряд
        builder.adjust(2)
        
        builder.row(
            InlineKeyboardButton(text="🔄 Обновить", callback_data="top_chats"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
        )
        
        try:
            await callback.message.edit_text(
                top_text,
                parse_mode=ParseMode.HTML,
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True
            )
        except Exception as e:
            if "message is not modified" in str(e):
                await safe_answer_callback(callback, "📊 Топ чатов актуален")
            else:
                raise e
        
    except Exception as e:
        logger.error(f"Ошибка при получении топ чатов: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при получении топ чатов")
        await callback.message.edit_text(
            "❌ <b>Ошибка</b>\n\n"
            "Произошла ошибка при получении топ чатов.\n"
            "Попробуйте позже.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
            ).as_markup()
        )


async def join_chat_callback(callback: CallbackQuery):
    """Обработчик кнопки вступления в чат из топа"""
    try:
        chat_id = int(callback.data.split("_")[2])
        
        chat_info = await db.get_chat(chat_id)
        
        if not chat_info:
            await safe_answer_callback(callback, "❌ Чат не найден", show_alert=True)
            return
        
        # Формируем информацию о чате
        text = f"💬 <b>{chat_info['chat_title']}</b>\n\n"
        
        # Добавляем ссылку на чат если есть
        # Приоритет: для публичных чатов используем username, для приватных - invite_link
        is_public = chat_info.get('is_public', False)
        username = chat_info.get('username')
        invite_link = chat_info.get('invite_link')
        
        builder = InlineKeyboardBuilder()
        
        # Если чат публичный и есть username - используем его
        if is_public and username:
            text += f"🔗 Ссылка: @{username}\n"
            builder.add(InlineKeyboardButton(
                text="💬 Перейти в чат",
                url=f"https://t.me/{username.lstrip('@')}"
            ))
        # Если чат приватный и есть invite_link - используем его
        elif not is_public and invite_link:
            text += f"🔗 <a href='{invite_link}'>Вступить в чат</a>\n"
            builder.add(InlineKeyboardButton(
                text="💬 Перейти в чат",
                url=invite_link
            ))
        # Если есть username, но чат не публичный (старая запись) - используем invite_link если есть
        elif username and invite_link:
            text += f"🔗 <a href='{invite_link}'>Вступить в чат</a>\n"
            builder.add(InlineKeyboardButton(
                text="💬 Перейти в чат",
                url=invite_link
            ))
        # Если есть только username (старая запись без invite_link) - используем его
        elif username:
            text += f"🔗 Ссылка: @{username}\n"
            builder.add(InlineKeyboardButton(
                text="💬 Перейти в чат",
                url=f"https://t.me/{username.lstrip('@')}"
            ))
        else:
            text += "🔒 Приватный чат без публичной ссылки\n"
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад к топу",
            callback_data="top_chats"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True
        )
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в join_chat_callback: {e}")
        await safe_answer_callback(callback, "❌ Ошибка", show_alert=True)
