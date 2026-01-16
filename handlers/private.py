"""
Обработчики для личных сообщений
"""
import logging
import random
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from databases.database import db
from handlers.common import create_main_menu, safe_answer_callback, update_chat_info_if_needed

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def register_private_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков для личных сообщений"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    dp.callback_query.register(random_chat_callback, F.data == "random_chat")
    dp.callback_query.register(back_to_menu_callback, F.data == "back_to_menu")
    dp.callback_query.register(main_menu_callback, F.data == "main_menu")


async def random_chat_callback(callback: CallbackQuery):
    """Обработчик кнопки 'Случайный чат'"""
    user = callback.from_user
    
    # Получаем все активные чаты
    chats = await db.get_all_active_chats()
    
    if not chats:
        await safe_answer_callback(callback, "😔 Пока нет доступных чатов")
        await callback.message.edit_text(
            "😔 К сожалению, пока нет доступных чатов для случайного выбора.\n\n"
            "Добавьте бота в больше чатов, чтобы эта функция заработала!",
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
            ).as_markup()
        )
        return
    
    # Выбираем случайный чат, избегая повторения
    # Получаем ID последнего выбранного чата для этого пользователя
    last_chat_key = f"last_random_chat_{user.id}"
    last_chat_id = getattr(random_chat_callback, last_chat_key, None)
    
    # Если есть только один чат, выбираем его
    if len(chats) == 1:
        random_chat = chats[0]
    else:
        # Исключаем последний выбранный чат из списка
        available_chats = [chat for chat in chats if chat['chat_id'] != last_chat_id]
        
        # Если после исключения не осталось чатов, используем все чаты
        if not available_chats:
            available_chats = chats
        
        random_chat = random.choice(available_chats)
    
    # Сохраняем выбранный чат для следующего выбора
    setattr(random_chat_callback, last_chat_key, random_chat['chat_id'])
    
    try:
        # Получаем информацию о чате
        try:
            chat_info = await bot.get_chat(random_chat['chat_id'])
            # Обновляем информацию о чате в базе данных
            await update_chat_info_if_needed(random_chat['chat_id'])
        except Exception as e:
            # Если чат был мигрирован, обновляем ID в базе данных
            error_str = str(e).lower()
            if "group chat was upgraded to a supergroup" in error_str:
                import re
                match = re.search(r'with id (-?\d+)', str(e))
                if match:
                    new_chat_id = int(match.group(1))
                    await db.update_chat_id(random_chat['chat_id'], new_chat_id)
                    random_chat['chat_id'] = new_chat_id
                    chat_info = await bot.get_chat(new_chat_id)
            else:
                logger.error(f"Ошибка при получении информации о чате {random_chat['chat_id']}: {e}")
                await safe_answer_callback(callback, "❌ Ошибка при получении информации о чате")
                return
        
        # Формируем текст сообщения
        chat_title = chat_info.title or "Без названия"
        chat_type_emoji = "👥" if chat_info.type == 'group' else "👤" if chat_info.type == 'supergroup' else "📢"
        
        # Получаем количество участников
        member_count = None
        try:
            member_count = await bot.get_chat_member_count(random_chat['chat_id'])
        except Exception:
            pass
        
        member_count_text = f" ({member_count} участников)" if member_count else ""
        
        text = f"""
{chat_type_emoji} <b>{chat_title}</b>{member_count_text}

Вы можете перейти в этот чат или выбрать другой случайный чат.
        """
        
        builder = InlineKeyboardBuilder()
        
        # Кнопка перехода в чат
        if chat_info.username:
            chat_url = f"https://t.me/{chat_info.username}"
            builder.add(InlineKeyboardButton(
                text="➡️ Перейти в чат",
                url=chat_url
            ))
        elif hasattr(chat_info, 'invite_link') and chat_info.invite_link:
            builder.add(InlineKeyboardButton(
                text="➡️ Перейти в чат",
                url=chat_info.invite_link
            ))
        else:
            # Пытаемся получить invite link из базы данных
            chat_db_info = await db.get_chat(random_chat['chat_id'])
            if chat_db_info and chat_db_info.get('invite_link'):
                builder.add(InlineKeyboardButton(
                    text="➡️ Перейти в чат",
                    url=chat_db_info['invite_link']
                ))
        
        builder.add(InlineKeyboardButton(
            text="🎲 Другой чат",
            callback_data="random_chat"
        ))
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="back_to_menu"
        ))
        builder.adjust(1)
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode=ParseMode.HTML
            )
        except Exception as edit_error:
            # Игнорируем ошибку "message is not modified" - это нормально, если сообщение не изменилось
            error_str = str(edit_error).lower()
            if "message is not modified" in error_str:
                pass  # Игнорируем эту ошибку
            else:
                raise  # Пробрасываем другие ошибки дальше
        
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в random_chat_callback: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при выборе чата", show_alert=True)


async def back_to_menu_callback(callback: CallbackQuery):
    """Возврат в главное меню"""
    try:
        # Создаем главное меню
        welcome_text, reply_markup = await create_main_menu()
        
        try:
            await callback.message.edit_text(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception as edit_error:
            # Игнорируем ошибку "message is not modified"
            error_str = str(edit_error).lower()
            if "message is not modified" not in error_str:
                raise
        
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в back_to_menu_callback: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при возврате в меню")


async def main_menu_callback(callback: CallbackQuery):
    """Возврат в главное меню"""
    try:
        # Создаем главное меню
        welcome_text, reply_markup = await create_main_menu()
        
        try:
            await callback.message.edit_text(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception as edit_error:
            # Игнорируем ошибку "message is not modified"
            error_str = str(edit_error).lower()
            if "message is not modified" not in error_str:
                raise
        
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в main_menu_callback: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при обновлении меню")

