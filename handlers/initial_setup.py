"""
Обработчики первоначальной настройки бота
"""
import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, FSInputFile, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from databases.database import db
from databases.raid_protection_db import raid_protection_db
from databases.utilities_db import utilities_db
from utils.permissions import get_effective_rank
from utils.formatting import get_philosophical_access_denied_message
from utils.gifs import set_gifs_enabled
from utils.constants import RANK_OWNER
from handlers.common import safe_answer_callback, check_chat_active
from handlers.top_chats import get_top_chat_settings_async, set_top_chat_settings_async

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None

# Путь к папке с изображениями для initial setup
BASE_PATH = Path(__file__).parent.parent
IMAGES_DIR = BASE_PATH / "Gifs" / "welcome" / "images"


class InitialSetup(StatesGroup):
    """FSM состояния для первоначальной настройки"""
    top_chats = State()
    gifs = State()
    raid_protection = State()
    utilities = State()


async def _ensure_owner(callback: CallbackQuery) -> bool:
    """Проверить, что пользователь является владельцем чата"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        
        effective_rank = await get_effective_rank(chat_id, user_id)
        
        if effective_rank != RANK_OWNER:
            quote = await get_philosophical_access_denied_message()
            await callback.answer(quote, show_alert=True)
            return False
        
        return True
    except Exception as e:
        logger.error(f"Ошибка при проверке прав владельца: {e}")
        await callback.answer("❌ Ошибка при проверке прав", show_alert=True)
        return False


def register_initial_setup_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков первоначальной настройки"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # Callbacks
    dp.callback_query.register(initial_setup_start_callback, F.data == "initial_setup_start")
    dp.callback_query.register(initial_setup_top_chats_callback, F.data.startswith("initial_setup_top_"))
    dp.callback_query.register(initial_setup_gifs_callback, F.data.startswith("initial_setup_gifs_"))
    dp.callback_query.register(initial_setup_raid_protection_callback, F.data.startswith("initial_setup_raid_"))
    dp.callback_query.register(initial_setup_utilities_callback, F.data.startswith("initial_setup_utilities_"))


async def initial_setup_start_callback(callback: CallbackQuery, state: FSMContext):
    """Начало первоначальной настройки"""
    # Проверяем, что чат активен и не заморожен
    if not await check_chat_active(callback):
        return
    
    if not await _ensure_owner(callback):
        return
    
    # Начинаем FSM с первого шага - показ в топе
    await state.set_state(InitialSetup.top_chats)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Включить",
        callback_data="initial_setup_top_enable"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Выключить",
        callback_data="initial_setup_top_disable"
    ))
    builder.add(InlineKeyboardButton(
        text="⏭ Пропустить",
        callback_data="initial_setup_top_skip"
    ))
    builder.adjust(2, 1)
    
    try:
        # Отправляем изображение для шага 1
        image_path = IMAGES_DIR / "step_1.png"
        text = (
            "⚙️ <b>Первоначальная настройка</b>\n\n"
            "<b>Шаг 1 из 4: Показ в топе</b>\n\n"
            "Включить показ этого чата в топе чатов? Это позволит другим пользователям найти ваш чат."
        )
        
        if image_path.exists():
            photo = FSInputFile(str(image_path))
            # Пробуем отредактировать медиа, если сообщение уже содержит медиа
            try:
                await callback.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=builder.as_markup()
                )
            except Exception as edit_error:
                # Если не удалось отредактировать (например, сообщение без медиа), отправляем новое
                error_str = str(edit_error).lower()
                if "message is not modified" in error_str:
                    pass  # Игнорируем эту ошибку
                elif "there is no text in the message to edit" in error_str or "message to edit not found" in error_str:
                    # Отправляем новое сообщение с фото
                    await callback.message.answer_photo(
                        photo=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=builder.as_markup()
                    )
                else:
                    raise
        else:
            logger.warning(f"Изображение не найдено: {image_path}")
            # Fallback на текстовое сообщение
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")


async def initial_setup_top_chats_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка настройки показа в топе"""
    if not await _ensure_owner(callback):
        return
    
    chat_id = callback.message.chat.id
    action = callback.data.split("_")[-1]  # enable, disable, skip
    
    if action == "enable":
        # Включаем показ в топе (устанавливаем show_in_top = 'always')
        current_settings = await get_top_chat_settings_async(chat_id)
        current_settings['show_in_top'] = 'always'
        await set_top_chat_settings_async(chat_id, current_settings)
    elif action == "disable":
        # Выключаем показ в топе (устанавливаем show_in_top = 'never')
        current_settings = await get_top_chat_settings_async(chat_id)
        current_settings['show_in_top'] = 'never'
        await set_top_chat_settings_async(chat_id, current_settings)
    # skip - ничего не делаем
    
    # Переходим к следующему шагу - гифки
    await state.set_state(InitialSetup.gifs)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Включить",
        callback_data="initial_setup_gifs_enable"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Выключить",
        callback_data="initial_setup_gifs_disable"
    ))
    builder.add(InlineKeyboardButton(
        text="⏭ Пропустить",
        callback_data="initial_setup_gifs_skip"
    ))
    builder.adjust(2, 1)
    
    try:
        # Отправляем изображение для шага 2
        image_path = IMAGES_DIR / "step_2.png"
        text = (
            "⚙️ <b>Первоначальная настройка</b>\n\n"
            "<b>Шаг 2 из 4: Гифки</b>\n\n"
            "Включить отправку гифок при выполнении команд модерации? Это сделает работу бота более наглядной."
        )
        
        if image_path.exists():
            photo = FSInputFile(str(image_path))
            try:
                await callback.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=builder.as_markup()
                )
            except Exception as edit_error:
                error_str = str(edit_error).lower()
                if "message is not modified" in error_str:
                    pass
                elif "there is no text in the message to edit" in error_str or "message to edit not found" in error_str:
                    await callback.message.answer_photo(
                        photo=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=builder.as_markup()
                    )
                else:
                    raise
        else:
            logger.warning(f"Изображение не найдено: {image_path}")
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")


async def initial_setup_gifs_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка настройки гифок"""
    if not await _ensure_owner(callback):
        return
    
    chat_id = callback.message.chat.id
    action = callback.data.split("_")[-1]  # enable, disable, skip
    
    if action == "enable":
        set_gifs_enabled(chat_id, True)
    elif action == "disable":
        set_gifs_enabled(chat_id, False)
    # skip - ничего не делаем
    
    # Переходим к следующему шагу - анти-спам
    await state.set_state(InitialSetup.raid_protection)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Включить",
        callback_data="initial_setup_raid_enable"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Выключить",
        callback_data="initial_setup_raid_disable"
    ))
    builder.add(InlineKeyboardButton(
        text="⏭ Пропустить",
        callback_data="initial_setup_raid_skip"
    ))
    builder.adjust(2, 1)
    
    try:
        # Отправляем изображение для шага 3
        image_path = IMAGES_DIR / "step_3.png"
        text = (
            "⚙️ <b>Первоначальная настройка</b>\n\n"
            "<b>Шаг 3 из 4: Анти-Спам</b>\n\n"
            "Включить защиту от спама? Бот будет автоматически удалять подозрительные сообщения и защищать чат от рейдов."
        )
        
        if image_path.exists():
            photo = FSInputFile(str(image_path))
            try:
                await callback.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=builder.as_markup()
                )
            except Exception as edit_error:
                error_str = str(edit_error).lower()
                if "message is not modified" in error_str:
                    pass
                elif "there is no text in the message to edit" in error_str or "message to edit not found" in error_str:
                    await callback.message.answer_photo(
                        photo=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=builder.as_markup()
                    )
                else:
                    raise
        else:
            logger.warning(f"Изображение не найдено: {image_path}")
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")


async def initial_setup_raid_protection_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка настройки анти-спама"""
    if not await _ensure_owner(callback):
        return
    
    chat_id = callback.message.chat.id
    action = callback.data.split("_")[-1]  # enable, disable, skip
    
    if action == "enable":
        # Включаем анти-спам с пресетом "Мягкий"
        await raid_protection_db.update_settings(chat_id, enabled=True)
        # Устанавливаем пресет "Мягкий" (значения по умолчанию уже установлены при создании)
    elif action == "disable":
        await raid_protection_db.update_settings(chat_id, enabled=False)
    # skip - ничего не делаем
    
    # Переходим к последнему шагу - утилиты
    await state.set_state(InitialSetup.utilities)
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Включить",
        callback_data="initial_setup_utilities_enable"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Выключить",
        callback_data="initial_setup_utilities_disable"
    ))
    builder.add(InlineKeyboardButton(
        text="⏭ Пропустить",
        callback_data="initial_setup_utilities_skip"
    ))
    builder.adjust(2, 1)
    
    try:
        # Отправляем изображение для шага 4
        image_path = IMAGES_DIR / "step_4.png"
        text = (
            "⚙️ <b>Первоначальная настройка</b>\n\n"
            "<b>Шаг 4 из 4: Утилиты</b>\n\n"
            "Включить дополнительные утилиты? Это включает защиту от эмодзи-спама, спама реакциями и ложных команд."
        )
        
        if image_path.exists():
            photo = FSInputFile(str(image_path))
            try:
                await callback.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=builder.as_markup()
                )
            except Exception as edit_error:
                error_str = str(edit_error).lower()
                if "message is not modified" in error_str:
                    pass
                elif "there is no text in the message to edit" in error_str or "message to edit not found" in error_str:
                    await callback.message.answer_photo(
                        photo=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=builder.as_markup()
                    )
                else:
                    raise
        else:
            logger.warning(f"Изображение не найдено: {image_path}")
            await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")


async def initial_setup_utilities_callback(callback: CallbackQuery, state: FSMContext):
    """Обработка настройки утилит"""
    if not await _ensure_owner(callback):
        return
    
    chat_id = callback.message.chat.id
    action = callback.data.split("_")[-1]  # enable, disable, skip
    
    if action == "enable":
        # Включаем основные утилиты
        await utilities_db.update_settings(
            chat_id,
            emoji_spam_enabled=True,
            reaction_spam_enabled=True,
            fake_commands_enabled=True
        )
    elif action == "disable":
        # Выключаем все утилиты
        await utilities_db.update_settings(
            chat_id,
            emoji_spam_enabled=False,
            reaction_spam_enabled=False,
            fake_commands_enabled=False
        )
    # skip - ничего не делаем
    
    # Завершаем настройку
    await state.clear()
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="📖 Документация",
        url="https://pixel-ut.pro/commands"
    ))
    builder.adjust(1)
    
    try:
        # Отправляем финальное изображение для шага 5
        image_path = IMAGES_DIR / "step_5.png"
        caption = (
            "✅ <b>Настройка завершена!</b>\n\n"
            "Базовые параметры бота настроены. Теперь бот готов к работе в вашем чате.\n\n"
            "Для изменения настроек используйте команду <code>/settings</code>\n\n"
            "📖 <a href=\"https://pixel-ut.pro/commands\">Документация по командам</a>"
        )
        
        if image_path.exists():
            photo = FSInputFile(str(image_path))
            try:
                await callback.message.edit_media(
                    media=InputMediaPhoto(
                        media=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    ),
                    reply_markup=builder.as_markup()
                )
            except Exception as edit_error:
                error_str = str(edit_error).lower()
                if "message is not modified" in error_str:
                    pass
                elif "there is no text in the message to edit" in error_str or "message to edit not found" in error_str:
                    await callback.message.answer_photo(
                        photo=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=builder.as_markup()
                    )
                else:
                    raise
        else:
            logger.warning(f"Изображение не найдено: {image_path}")
            await callback.message.edit_text(caption, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup(), disable_web_page_preview=False)
        await callback.answer("✅ Настройка завершена!")
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")

