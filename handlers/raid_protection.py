"""
Обработчики команд Анти-Спама
"""
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from databases.raid_protection_db import raid_protection_db
from utils.permissions import get_effective_rank
from utils.constants import RANK_OWNER, RANK_ADMIN
from handlers.common import require_admin_rights, safe_answer_callback

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def register_raid_protection_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков Анти-Спама"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # Команды
    dp.message.register(raid_protection_command, Command("raidprotection"))
    
    # Callbacks - настройки рейд-защиты
    dp.callback_query.register(settings_open_raid_callback, F.data == "settings_open_raid")
    dp.callback_query.register(raid_toggle_callback, F.data == "raid_toggle")
    dp.callback_query.register(raid_notif_callback, F.data.startswith("raid_notif_"))
    dp.callback_query.register(raid_preset_callback, F.data.startswith("raid_preset_"))
    dp.callback_query.register(raid_mute_settings_callback, F.data == "raid_mute_settings")
    dp.callback_query.register(raid_auto_mute_toggle_callback, F.data == "raid_auto_mute_toggle")
    dp.callback_query.register(raid_mute_silent_callback, F.data == "raid_mute_silent")
    # Регистрируем raid_mute_callback последним, чтобы он не перехватывал другие callback'ы
    # Используем startswith, но проверяем в обработчике, что это не специальные callback'ы
    dp.callback_query.register(raid_mute_callback, F.data.startswith("raid_mute_"))


@require_admin_rights
async def raid_protection_command(message: Message):
    """Показать настройки Анти-Спама"""
    chat = message.chat
    settings = await raid_protection_db.get_settings(chat.id)
    
    enabled = settings.get('enabled', True)
    status_text = "✅ Включена" if enabled else "❌ Выключена"
    notification_mode = settings.get('notification_mode', 1)
    
    notif_modes = {0: "Отключены", 1: "Только мощные атаки (≥3)"}
    notif_text = notif_modes.get(notification_mode, "Только мощные атаки")
    
    # Определяем текущий пресет
    current_preset = _detect_current_preset(settings)
    if enabled and current_preset is None:
        current_preset = 'soft'
    preset_names = {'soft': 'Мягкий', 'medium': 'Средний', 'hard': 'Жесткий'}
    preset_display = preset_names.get(current_preset, 'Пользовательский') if enabled else '—'
    
    text = (
        f"🛡️ <b>Настройки Анти-Спама</b>\n\n"
        f"<b>Статус:</b> {status_text}\n"
        f"<b>Режим:</b> {preset_display}\n"
        f"<b>Уведомления:</b> {notif_text}\n\n"
        f"<b>Текущие лимиты:</b>\n"
        f"• GIF-спам: {settings.get('gif_limit', 3)} за {settings.get('gif_time_window', 5)}с\n"
        f"• Стикеры: {settings.get('sticker_limit', 5)} за {settings.get('sticker_time_window', 10)}с\n"
        f"• Дубликаты: {settings.get('duplicate_text_limit', 3)} за {settings.get('duplicate_text_window', 30)}с\n"
        f"• Массовый вход: {settings.get('mass_join_limit', 10)} за {settings.get('mass_join_window', 60)}с\n\n"
        f"Используйте /settings для настройки."
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)


def _detect_current_preset(settings: dict) -> str | None:
    """Определить текущий пресет по настройкам"""
    presets = {
        'soft': {
            'gif_limit': 5, 'gif_time_window': 10,
            'sticker_limit': 8, 'sticker_time_window': 15,
            'duplicate_text_limit': 5, 'duplicate_text_window': 60,
            'mass_join_limit': 15, 'mass_join_window': 120
        },
        'medium': {
            'gif_limit': 3, 'gif_time_window': 5,
            'sticker_limit': 5, 'sticker_time_window': 10,
            'duplicate_text_limit': 3, 'duplicate_text_window': 30,
            'mass_join_limit': 10, 'mass_join_window': 60
        },
        'hard': {
            'gif_limit': 2, 'gif_time_window': 3,
            'sticker_limit': 3, 'sticker_time_window': 5,
            'duplicate_text_limit': 2, 'duplicate_text_window': 15,
            'mass_join_limit': 5, 'mass_join_window': 30
        }
    }
    
    for preset_name, preset_values in presets.items():
        if all(settings.get(key) == value for key, value in preset_values.items()):
            return preset_name
    
    return None


async def build_raid_settings_panel(chat_id: int):
    """Построить панель настроек анти-спама"""
    settings = await raid_protection_db.get_settings(chat_id)
    
    builder = InlineKeyboardBuilder()
    
    # Кнопка включения/выключения
    enabled = settings.get('enabled', True)
    builder.button(
        text=f"{'✅' if enabled else '❌'} Защита: {'Вкл.' if enabled else 'Выкл.'}",
        callback_data="raid_toggle"
    )
    
    # Кнопки режима уведомлений
    notif_mode = settings.get('notification_mode', 1)
    builder.button(
        text=f"{'✅' if notif_mode == 0 else ''} Без уведомлений",
        callback_data="raid_notif_0"
    )
    builder.button(
        text=f"{'✅' if notif_mode == 1 else ''} Мощные атаки",
        callback_data="raid_notif_1"
    )
    
    # Определяем текущий пресет
    current_preset = _detect_current_preset(settings)
    # Если защита включена и пресет не определен - по умолчанию мягкий
    if enabled and current_preset is None:
        current_preset = 'soft'
    
    # Кнопки пресетов с галочками (только если защита включена)
    if enabled:
        soft_check = "✅ " if current_preset == 'soft' else ""
        medium_check = "✅ " if current_preset == 'medium' else ""
        hard_check = "✅ " if current_preset == 'hard' else ""
    else:
        soft_check = medium_check = hard_check = ""
    
    builder.button(text=f"{soft_check}Мягкий", callback_data="raid_preset_soft")
    builder.button(text=f"{medium_check}Средний", callback_data="raid_preset_medium")
    builder.button(text=f"{hard_check}Жесткий", callback_data="raid_preset_hard")
    
    # Настройка мута
    builder.button(text="⏱ Время мута", callback_data="raid_mute_settings")
    
    # Кнопка переключения авто-мута
    auto_mute_enabled = settings.get('auto_mute_enabled', True)
    builder.button(
        text=f"{'✅' if auto_mute_enabled else '❌'} Авто-мут: {'Вкл.' if auto_mute_enabled else 'Выкл.'}",
        callback_data="raid_auto_mute_toggle"
    )
    
    # Кнопка переключения мута без уведомлений
    mute_silent = settings.get('mute_silent', False)
    builder.button(
        text=f"{'✅' if mute_silent else '❌'} Мут без уведомлений",
        callback_data="raid_mute_silent"
    )
    
    # Назад
    builder.button(text="🔙 Назад", callback_data="settings_main")
    
    builder.adjust(1, 2, 3, 1, 1, 1, 1)
    
    status_text = "✅ Включена" if enabled else "❌ Выключена"
    notif_modes = {0: "Отключены", 1: "Только мощные атаки (≥3)"}
    notif_text = notif_modes.get(notif_mode, "Только мощные атаки")
    
    mute_duration = settings.get('mute_duration', 300)
    mute_text = f"{mute_duration // 60} мин" if mute_duration < 3600 else f"{mute_duration // 3600} час"
    
    # Получаем настройки авто-мута
    auto_mute_enabled = settings.get('auto_mute_enabled', True)
    mute_silent = settings.get('mute_silent', False)
    auto_mute_text = "✅ Включен" if auto_mute_enabled else "❌ Выключен"
    mute_silent_text = "✅ Включен" if mute_silent else "❌ Выключен"
    
    # Название текущего пресета для отображения
    preset_names = {'soft': 'Мягкий', 'medium': 'Средний', 'hard': 'Жесткий'}
    preset_display = preset_names.get(current_preset, 'Пользовательский') if enabled else '—'
    
    text = (
        f"🛡️ <b>Настройки Анти-Спама</b>\n\n"
        f"<b>Статус:</b> {status_text}\n"
        f"<b>Режим:</b> {preset_display}\n"
        f"<b>Уведомления:</b> {notif_text}\n"
        f"<b>Время мута:</b> {mute_text}\n"
        f"<b>Авто-мут:</b> {auto_mute_text}\n"
        f"<b>Мут без уведомлений:</b> {mute_silent_text}\n\n"
        f"<b>Текущие лимиты:</b>\n"
        f"• GIF-спам: {settings.get('gif_limit', 3)} за {settings.get('gif_time_window', 5)}с\n"
        f"• Стикеры: {settings.get('sticker_limit', 5)} за {settings.get('sticker_time_window', 10)}с\n"
        f"• Дубликаты: {settings.get('duplicate_text_limit', 3)} за {settings.get('duplicate_text_window', 30)}с\n\n"
        f"<b>Выберите режим защиты:</b>"
    )
    
    return text, builder.as_markup()


async def settings_open_raid_callback(callback: CallbackQuery):
    """Открыть настройки Анти-Спама"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    
    text, markup = await build_raid_settings_panel(chat_id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await callback.answer("🛡️ Анти-Спам")


async def raid_toggle_callback(callback: CallbackQuery):
    """Переключить Анти-Спам"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    
    settings = await raid_protection_db.get_settings(chat_id)
    new_status = not settings.get('enabled', True)
    
    await raid_protection_db.update_settings(chat_id, enabled=new_status)
    
    text, markup = await build_raid_settings_panel(chat_id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await callback.answer(f"Защита {'включена' if new_status else 'выключена'}")


async def raid_notif_callback(callback: CallbackQuery):
    """Изменить режим уведомлений"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    
    mode = int(callback.data.split("_")[2])
    
    await raid_protection_db.update_settings(chat_id, notification_mode=mode)
    
    text, markup = await build_raid_settings_panel(chat_id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    
    notif_modes = {0: "Отключены", 1: "Только мощные атаки"}
    await callback.answer(f"Уведомления: {notif_modes.get(mode, 'Неизвестно')}")


async def raid_preset_callback(callback: CallbackQuery):
    """Применить пресет настроек"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    
    preset = callback.data.split("_")[2]
    
    # Пресеты настроек
    presets = {
        'soft': {
            'gif_limit': 5, 'gif_time_window': 10,
            'sticker_limit': 8, 'sticker_time_window': 15,
            'duplicate_text_limit': 5, 'duplicate_text_window': 60,
            'mass_join_limit': 15, 'mass_join_window': 120
        },
        'medium': {
            'gif_limit': 3, 'gif_time_window': 5,
            'sticker_limit': 5, 'sticker_time_window': 10,
            'duplicate_text_limit': 3, 'duplicate_text_window': 30,
            'mass_join_limit': 10, 'mass_join_window': 60
        },
        'hard': {
            'gif_limit': 2, 'gif_time_window': 3,
            'sticker_limit': 3, 'sticker_time_window': 5,
            'duplicate_text_limit': 2, 'duplicate_text_window': 15,
            'mass_join_limit': 5, 'mass_join_window': 30
        }
    }
    
    if preset in presets:
        await raid_protection_db.update_settings(chat_id, **presets[preset])
    
    text, markup = await build_raid_settings_panel(chat_id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    
    preset_names = {'soft': 'Мягкий', 'medium': 'Средний', 'hard': 'Жесткий'}
    await callback.answer(f"Применен пресет: {preset_names.get(preset, 'Неизвестный')}")


async def raid_mute_settings_callback(callback: CallbackQuery):
    """Открыть настройки времени мута"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    
    settings = await raid_protection_db.get_settings(chat_id)
    current_duration = settings.get('mute_duration', 300)
    
    builder = InlineKeyboardBuilder()
    
    mute_times = [
        (60, "1 мин"), (180, "3 мин"), (300, "5 мин"), (600, "10 мин"),
        (900, "15 мин"), (1800, "30 мин"), (3600, "1 час"), (7200, "2 часа")
    ]
    
    for duration, label in mute_times:
        selected = "✅ " if duration == current_duration else ""
        builder.button(text=f"{selected}{label}", callback_data=f"raid_mute_{duration}")
    
    builder.button(text="🔙 Назад", callback_data="settings_open_raid")
    builder.adjust(4, 4, 1)
    
    text = (
        "⏱ <b>Настройка времени мута</b>\n\n"
        f"Текущее время: <b>{current_duration // 60} мин</b>\n\n"
        "Выберите время мута при обнаружении спама:"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def raid_mute_callback(callback: CallbackQuery):
    """Установить время мута"""
    # Пропускаем специальные callback'ы, которые обрабатываются другими обработчиками
    if callback.data in ("raid_mute_settings", "raid_mute_silent"):
        return
    
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    
    # Проверяем, что после "raid_mute_" идет число
    try:
        duration = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        logger.warning(f"Неверный формат callback_data для raid_mute_callback: {callback.data}")
        return
    
    logger.info(f"Сохранение mute_duration={duration} для чата {chat_id}")
    result = await raid_protection_db.update_settings(chat_id, mute_duration=duration)
    if result:
        logger.info(f"Настройка mute_duration успешно сохранена: {duration} сек для чата {chat_id}")
    else:
        logger.error(f"Ошибка при сохранении mute_duration для чата {chat_id}")
    
    # Возвращаемся к настройкам рейда
    text, markup = await build_raid_settings_panel(chat_id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    
    await callback.answer(f"Время мута: {duration // 60} мин")


async def raid_auto_mute_toggle_callback(callback: CallbackQuery):
    """Переключить авто-мут"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    
    settings = await raid_protection_db.get_settings(chat_id)
    new_status = not settings.get('auto_mute_enabled', True)
    
    logger.info(f"Сохранение auto_mute_enabled={new_status} для чата {chat_id}")
    result = await raid_protection_db.update_settings(chat_id, auto_mute_enabled=new_status)
    if result:
        logger.info(f"Настройка auto_mute_enabled успешно сохранена: {new_status} для чата {chat_id}")
    else:
        logger.error(f"Ошибка при сохранении auto_mute_enabled для чата {chat_id}")
    
    text, markup = await build_raid_settings_panel(chat_id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await callback.answer(f"Авто-мут {'включен' if new_status else 'выключен'}")


async def raid_mute_silent_callback(callback: CallbackQuery):
    """Переключить мут без уведомлений"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    
    settings = await raid_protection_db.get_settings(chat_id)
    new_status = not settings.get('mute_silent', False)
    
    logger.info(f"Сохранение mute_silent={new_status} для чата {chat_id}")
    result = await raid_protection_db.update_settings(chat_id, mute_silent=new_status)
    if result:
        logger.info(f"Настройка mute_silent успешно сохранена: {new_status} для чата {chat_id}")
    else:
        logger.error(f"Ошибка при сохранении mute_silent для чата {chat_id}")
    
    text, markup = await build_raid_settings_panel(chat_id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await callback.answer(f"Мут без уведомлений {'включен' if new_status else 'выключен'}")
