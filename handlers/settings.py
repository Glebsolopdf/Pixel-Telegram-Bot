"""
Обработчики команд настроек
"""
import logging
import re
from collections import Counter
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from databases.database import db
from databases.moderation_db import moderation_db
from databases.network_db import network_db
from databases.raid_protection_db import raid_protection_db
from databases.utilities_db import utilities_db
from utils.permissions import get_effective_rank, check_permission
from utils.formatting import format_mute_duration, get_philosophical_access_denied_message
from utils.gifs import get_gifs_enabled, set_gifs_enabled
from utils.text_quality import is_text_meaningful
from utils.constants import RANK_OWNER, RANK_ADMIN, RANK_JUNIOR_MOD, RANK_NAMES, DEFAULT_RANK_PERMISSIONS
from handlers.common import (
    require_admin_rights, require_bot_admin_rights, 
    safe_answer_callback, fast_edit_message, answer_access_denied_callback,
    check_chat_active
)
from handlers.top_chats import get_top_chat_settings, set_top_chat_settings, get_top_chat_settings_async, set_top_chat_settings_async
from config import RAID_PROTECTION, TOP_CHATS_DEFAULTS

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None

warn_settings_context = set()
rank_settings_context = set()


def get_rank_name(rank: int, count: int = 1) -> str:
    """Получить название ранга с учетом множественного числа"""
    return RANK_NAMES[rank][0] if count == 1 else RANK_NAMES[rank][1]


def _is_rank_settings_context(chat_id: int, message_id: int) -> bool:
    """Проверить, открыто ли меню настроек рангов из главного меню"""
    return (chat_id, message_id) in rank_settings_context


async def _ensure_admin(callback: CallbackQuery) -> bool:
    """Проверка, что действия с меню выполняет владелец/администратор."""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    try:
        effective_rank = await get_effective_rank(chat_id, user_id)
        if effective_rank <= 2:
            return True
        await answer_access_denied_callback(callback)
        return False
    except Exception:
        await answer_access_denied_callback(callback)
        return False


def register_settings_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков команд настроек"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    dp.message.register(settings_command, Command("settings"))
    dp.message.register(selfdemote_command, Command("removmymod"))
    dp.message.register(autojoin_command, Command("autojoin"))
    dp.message.register(russianprefix_command, Command("russianprefix"))
    dp.message.register(warnconfig_command, Command("warnconfig"))
    dp.message.register(rankconfig_command, Command("rankconfig"))
    dp.message.register(resetconfig_command, Command("resetconfig"))
    dp.message.register(rules_command, Command("rules"))
    
    dp.callback_query.register(settings_close_callback, F.data == "settings_close")
    dp.callback_query.register(settings_back_root_callback, F.data == "settings_back_root")
    dp.callback_query.register(settings_main_callback, F.data == "settings_main")
    dp.callback_query.register(settings_resetconfig_callback, F.data == "settings_resetconfig")
    
    dp.callback_query.register(settings_open_gifs_callback, F.data == "settings_open_gifs")
    dp.callback_query.register(gifs_enable_callback, F.data == "gifs_enable")
    dp.callback_query.register(gifs_disable_callback, F.data == "gifs_disable")
    
    dp.callback_query.register(settings_open_autojoin_callback, F.data == "settings_open_autojoin")
    dp.callback_query.register(autojoin_enable_callback, F.data == "autojoin_enable")
    dp.callback_query.register(autojoin_disable_callback, F.data == "autojoin_disable")
    dp.callback_query.register(autojoin_notify_enable_callback, F.data == "autojoin_notify_enable")
    dp.callback_query.register(autojoin_notify_disable_callback, F.data == "autojoin_notify_disable")
    
    dp.callback_query.register(selfdemote_confirm_callback, F.data.startswith("selfdemote_confirm_"))
    dp.callback_query.register(selfdemote_cancel_callback, F.data.startswith("selfdemote_cancel_"))
    
    dp.callback_query.register(russianprefix_enable_callback, F.data == "russianprefix_enable")
    dp.callback_query.register(russianprefix_disable_callback, F.data == "russianprefix_disable")
    dp.callback_query.register(settings_open_ruprefix_callback, F.data == "settings_open_ruprefix")
    
    dp.callback_query.register(settings_open_warn_callback, F.data == "settings_open_warn")
    dp.callback_query.register(warnconfig_limit_callback, F.data == "warnconfig_limit")
    dp.callback_query.register(warnlimit_set_callback, F.data.startswith("warnlimit_"))
    dp.callback_query.register(warnconfig_punishment_callback, F.data == "warnconfig_punishment")
    dp.callback_query.register(warnpunishment_set_callback, F.data.startswith("warnpunishment_"))
    dp.callback_query.register(warnconfig_mutetime_callback, F.data == "warnconfig_mutetime")
    dp.callback_query.register(warnmutetime_set_callback, F.data.startswith("warnmutetime_"))
    dp.callback_query.register(warnconfig_bantime_callback, F.data == "warnconfig_bantime")
    dp.callback_query.register(warnbantime_set_callback, F.data.startswith("warnbantime_"))
    dp.callback_query.register(warnconfig_back_callback, F.data == "warnconfig_back")
    
    dp.callback_query.register(settings_open_stat_callback, F.data == "settings_open_stat")
    dp.callback_query.register(statconfig_toggle_stats_callback, F.data == "statconfig_toggle_stats")
    dp.callback_query.register(statconfig_toggle_media_callback, F.data == "statconfig_toggle_media")
    dp.callback_query.register(statconfig_toggle_profile_callback, F.data == "statconfig_toggle_profile")
    dp.callback_query.register(statconfig_toggle_userinfo_callback, F.data == "statconfig_toggle_userinfo")
    
    dp.callback_query.register(settings_open_ranks_callback, F.data == "settings_open_ranks")
    dp.callback_query.register(rankconfig_select_callback, F.data.startswith("rankconfig_select_"))
    dp.callback_query.register(rankconfig_back_callback, F.data == "rankconfig_back")
    dp.callback_query.register(rankconfig_reset_all_callback, F.data == "rankconfig_reset_all")
    dp.callback_query.register(rankconfig_reset_callback, F.data.startswith("rankconfig_reset_"))
    dp.callback_query.register(rankconfig_category_callback, F.data.startswith("rankconfig_category_"))
    dp.callback_query.register(rankconfig_toggle_callback, F.data.startswith("rankconfig_toggle_"))
    
    dp.callback_query.register(settings_open_top_callback, F.data == "settings_open_top")
    dp.callback_query.register(top_settings_visibility_callback, F.data == "top_settings_visibility")
    dp.callback_query.register(top_setting_visibility_callback, F.data.startswith("top_setting_visibility_"))
    
    dp.callback_query.register(settings_initperms_callback, F.data == "settings_initperms")
    dp.callback_query.register(initperms_confirm_callback, F.data == "initperms_confirm")
    
    dp.callback_query.register(settings_open_utilities_callback, F.data == "settings_open_utilities")
    dp.callback_query.register(utilities_emoji_spam_callback, F.data == "utilities_emoji_spam")
    dp.callback_query.register(utilities_emoji_spam_toggle_callback, F.data == "utilities_emoji_spam_toggle")
    dp.callback_query.register(utilities_emoji_spam_limit_callback, F.data == "utilities_emoji_spam_limit")
    dp.callback_query.register(utilities_emoji_spam_limit_set_callback, F.data.startswith("utilities_emoji_limit_"))
    dp.callback_query.register(utilities_reaction_spam_callback, F.data == "utilities_reaction_spam")
    dp.callback_query.register(utilities_reaction_spam_toggle_callback, F.data == "utilities_reaction_spam_toggle")
    dp.callback_query.register(utilities_reaction_spam_limit_callback, F.data == "utilities_reaction_spam_limit")
    dp.callback_query.register(utilities_reaction_spam_limit_set_callback, F.data.startswith("utilities_reaction_limit_"))
    dp.callback_query.register(utilities_reaction_spam_window_callback, F.data == "utilities_reaction_spam_window")
    dp.callback_query.register(utilities_reaction_spam_window_set_callback, F.data.startswith("utilities_reaction_window_"))
    dp.callback_query.register(utilities_reaction_spam_warning_callback, F.data == "utilities_reaction_spam_warning")
    dp.callback_query.register(utilities_reaction_spam_punishment_callback, F.data == "utilities_reaction_spam_punishment")
    dp.callback_query.register(utilities_reaction_spam_punishment_set_callback, F.data.startswith("utilities_reaction_punishment_"))
    dp.callback_query.register(utilities_reaction_spam_ban_duration_callback, F.data == "utilities_reaction_spam_ban_duration")
    dp.callback_query.register(utilities_reaction_spam_ban_duration_set_callback, F.data.startswith("utilities_reaction_ban_duration_"))
    dp.callback_query.register(utilities_reaction_spam_silent_callback, F.data == "utilities_reaction_spam_silent")
    dp.callback_query.register(utilities_fake_commands_callback, F.data == "utilities_fake_commands")
    dp.callback_query.register(utilities_fake_commands_toggle_callback, F.data == "utilities_fake_commands_toggle")
    dp.callback_query.register(utilities_auto_ban_channels_callback, F.data == "utilities_auto_ban_channels")
    dp.callback_query.register(utilities_auto_ban_channels_toggle_callback, F.data == "utilities_auto_ban_channels_toggle")
    dp.callback_query.register(utilities_back_callback, F.data == "utilities_back")
    
    dp.callback_query.register(resetconfig_confirm_callback, F.data == "resetconfig_confirm")
    dp.callback_query.register(resetconfig_cancel_callback, F.data == "resetconfig_cancel")


async def build_settings_menu(chat_id: int, effective_rank: int):
    """Построить главное меню настроек"""
    builder = InlineKeyboardBuilder()
    
    builder.button(text="📊 Общие команды", callback_data="settings_open_stat")
    builder.button(text="⚠️ Варны", callback_data="settings_open_warn")
    builder.button(text="🔰 Права/ранги", callback_data="settings_open_ranks")
    builder.button(text="🇷🇺 Префикс", callback_data="settings_open_ruprefix")
    builder.button(text="🚪 Автодопуск", callback_data="settings_open_autojoin")
    builder.button(text="🛡️ Анти-Спам", callback_data="settings_open_raid")
    builder.button(text="🔧 Утилиты", callback_data="settings_open_utilities")
    builder.button(text="🎬 Гифки", callback_data="settings_open_gifs")
    builder.button(text="🏆 Топ", callback_data="settings_open_top")
    if effective_rank == RANK_OWNER:
        builder.button(text="⚙️ Сброс прав", callback_data="settings_initperms")
    if effective_rank <= RANK_ADMIN:
        builder.button(text="🔄 Сброс настроек", callback_data="settings_resetconfig")
    builder.button(text="✖️ Закрыть", callback_data="settings_close")
    
    builder.adjust(2, 2, 2, 1, 2, 1, 1, 1)
    
    settings_text = (
        "⚙️ <b>Настройки чата</b>\n\n"
        f"<b>Ваш ранг:</b> {RANK_NAMES.get(effective_rank, ('Неизвестно', 'Неизвестно'))[0]}\n\n"
        "Выберите раздел:"
    )
    
    return settings_text, builder.as_markup()


async def build_readonly_settings_view(chat_id: int) -> str:
    """Построить текстовый обзор настроек для обычных пользователей (без кнопок)"""
    
    gifs_enabled = get_gifs_enabled(chat_id)
    autojoin_enabled = await db.get_auto_accept_join_requests(chat_id)
    russian_prefix = await db.get_russian_commands_prefix_setting(chat_id)
    warn_settings = await moderation_db.get_warn_settings(chat_id)
    stat_settings = await db.get_chat_stat_settings(chat_id)
    raid_settings = await raid_protection_db.get_settings(chat_id)
    utilities_settings = await utilities_db.get_settings(chat_id)
    
    punishment_names = {'kick': 'Кик', 'mute': 'Мут', 'ban': 'Бан'}
    warn_punishment = punishment_names.get(warn_settings['punishment_type'], 'Неизвестно')
    
    raid_enabled = raid_settings.get('enabled', True)
    
    text = (
        "⚙️ <b>Настройки чата</b>\n\n"
        "<i>Только для просмотра. Изменять могут модераторы.</i>\n\n"
        
        f"<b>Основные:</b>\n"
        f"• Статистика: {'✅' if stat_settings.get('stats_enabled', True) else '❌'}\n"
        f"• Гифки: {'✅' if gifs_enabled else '❌'}\n"
        f"• Автодопуск: {'✅' if autojoin_enabled else '❌'}\n"
        f"• Русский префикс: {'✅' if russian_prefix else '❌'}\n\n"
        
        f"<b>Варны:</b>\n"
        f"• Лимит: {warn_settings['warn_limit']}\n"
        f"• Наказание: {warn_punishment}\n\n"
        
        f"<b>Анти-Спам:</b>\n"
        f"• Статус: {'✅ Включен' if raid_enabled else '❌ Выключен'}\n\n"
        
        f"<b>Утилиты:</b>\n"
        f"• Эмодзи спам: {'✅ Включено' if utilities_settings.get('emoji_spam_enabled', False) else '❌ Выключено'}\n"
    )
    
    if utilities_settings.get('emoji_spam_enabled', False):
        text += f"• Лимит эмодзи: {utilities_settings.get('emoji_spam_limit', 10)}\n"
    
    text += (
        f"• Спам реакциями: {'✅ Включено' if utilities_settings.get('reaction_spam_enabled', False) else '❌ Выключено'}\n"
        f"• Ложные команды: {'✅ Включено' if utilities_settings.get('fake_commands_enabled', False) else '❌ Выключено'}\n"
    )
    
    return text


@require_bot_admin_rights
async def settings_command(message: Message, **kwargs):
    """Обработчик команды /settings - центральное меню настроек"""
    chat = message.chat
    user = message.from_user
    
    # Проверяем, что чат активен и не заморожен (только для групповых чатов)
    if chat.type in ['group', 'supergroup']:
        chat_info = await db.get_chat(chat.id)
        if chat_info and (not chat_info.get('is_active', True) or chat_info.get('frozen_at')):
            await message.answer("❌ Бот был удален из этого чата")
            return
    
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    if effective_rank > RANK_JUNIOR_MOD:
        readonly_text = await build_readonly_settings_view(chat.id)
        await message.answer(readonly_text, parse_mode=ParseMode.HTML)
        return
    
    settings_text, markup = await build_settings_menu(chat.id, effective_rank)
    
    await message.answer(
        settings_text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    )


async def selfdemote_command(message: Message):
    """Само-снятие с модераторского поста"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Проверяем, является ли пользователь реальным Telegram creator (владельцем)
    # Совладельцы (rank 1 из БД) могут снимать себя, только настоящий владелец не может
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status == 'creator':
            await message.answer("😑 Вы не можете снять себя этой командой.")
            return
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса пользователя {user_id} в чате {chat_id}: {e}")
    
    effective_rank = await get_effective_rank(chat_id, user_id)
    if effective_rank > RANK_JUNIOR_MOD:
        await message.answer("🙂‍↔️ У вас нет модераторского поста.")
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"selfdemote_confirm_{user_id}")
    builder.button(text="🔙 Отмена", callback_data=f"selfdemote_cancel_{user_id}")
    builder.adjust(1, 1)

    await message.answer(
        "⚠️ Вы уверены, что хотите снять себя с модераторского поста?",
        reply_markup=builder.as_markup()
    )


async def selfdemote_confirm_callback(callback: CallbackQuery):
    """Подтверждение само-снятия"""
    try:
        chat_id = callback.message.chat.id
        user_id = callback.from_user.id
        
        try:
            suffix = callback.data.split("selfdemote_confirm_", 1)[1]
            initiator_id = int(suffix)
        except Exception:
            initiator_id = None

        if initiator_id != user_id:
            await callback.answer("Эта кнопка не для вас.", show_alert=True)
            return

        # Проверяем, является ли пользователь реальным Telegram creator (владельцем)
        # Совладельцы (rank 1 из БД) могут снимать себя, только настоящий владелец не может
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status == 'creator':
                await callback.answer("Владелец не может снять себя этой кнопкой.", show_alert=True)
                return
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса пользователя {user_id} в чате {chat_id}: {e}")
        
        effective_rank = await get_effective_rank(chat_id, user_id)
        if effective_rank > RANK_JUNIOR_MOD:
            await callback.answer("У вас нет модераторского поста.", show_alert=True)
            return

        success = await db.remove_moderator(chat_id, user_id)
        if success:
            await fast_edit_message(
                callback,
                "✅ Вы сняли себя с модераторского поста. Теперь вы — пользователь.",
                reply_markup=None,
                parse_mode=None,
            )
            await callback.answer("Готово")
        else:
            await callback.answer("Не удалось снять вас с поста. Попробуйте позже.", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка selfdemote_confirm_callback: {e}")
        await callback.answer("Ошибка", show_alert=True)


async def selfdemote_cancel_callback(callback: CallbackQuery):
    """Отмена само-снятия"""
    try:
        user_id = callback.from_user.id
        try:
            suffix = callback.data.split("selfdemote_cancel_", 1)[1]
            initiator_id = int(suffix)
        except Exception:
            initiator_id = None

        if initiator_id != user_id:
            await callback.answer("Эта кнопка не для вас.", show_alert=True)
            return

        await fast_edit_message(callback, "❎ Отменено.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка selfdemote_cancel_callback: {e}")
        await callback.answer("Ошибка")


async def settings_open_autojoin_callback(callback: CallbackQuery):
    """Открытие настроек автодопуска"""
    try:
        chat_id = callback.message.chat.id
        effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
        if effective_rank not in (RANK_OWNER, RANK_ADMIN):
            await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
            return
        
        enabled = await db.get_auto_accept_join_requests(chat_id)
        notify = await db.get_auto_accept_notify(chat_id)
        status = "Включено ✅" if enabled else "Выключено ❌"
        notify_status = "Вкл." if notify else "Выкл."

        builder = InlineKeyboardBuilder()
        if enabled:
            builder.button(text="❌ Выключить", callback_data="autojoin_disable")
        else:
            builder.button(text="✅ Включить", callback_data="autojoin_enable")
        if notify:
            builder.button(text="🔕 Откл. уведомления", callback_data="autojoin_notify_disable")
        else:
            builder.button(text="🔔 Вкл. уведомления", callback_data="autojoin_notify_enable")
        builder.button(text="🔙 Назад", callback_data="settings_back_root")
        builder.adjust(1, 1, 1)

        text = (
            "🚪 <b>Автодопуск заявок</b>\n\n"
            f"Статус: <b>{status}</b>\n"
            f"Уведомления: <b>{notify_status}</b>\n\n"
            "Когда включено — бот автоматически одобряет заявки."
        )
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_autojoin_callback: {e}")
        await callback.answer("Ошибка")


async def settings_open_gifs_callback(callback: CallbackQuery):
    """Открытие настроек гифок"""
    if not await check_chat_active(callback):
        return
    try:
        chat_id = callback.message.chat.id
        effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
        if effective_rank not in (RANK_OWNER, RANK_ADMIN):
            await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
            return
        
        enabled = get_gifs_enabled(chat_id)
        status = "Включено ✅" if enabled else "Выключено ❌"

        builder = InlineKeyboardBuilder()
        if enabled:
            builder.button(text="❌ Выключить", callback_data="gifs_disable")
        else:
            builder.button(text="✅ Включить", callback_data="gifs_enable")
        builder.button(text="🔙 Назад", callback_data="settings_main")
        builder.adjust(1, 1)

        text = (
            "🎬 <b>Настройки гифок</b>\n\n"
            f"Статус: <b>{status}</b>\n\n"
            "Когда включено — бот отправляет гифки с сообщениями модерации."
        )
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_gifs_callback: {e}")
        await callback.answer("Ошибка")


async def gifs_enable_callback(callback: CallbackQuery):
    """Включить гифки для чата"""
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    set_gifs_enabled(chat_id, True)
    await settings_open_gifs_callback(callback)


async def gifs_disable_callback(callback: CallbackQuery):
    """Выключить гифки для чата"""
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    set_gifs_enabled(chat_id, False)
    await settings_open_gifs_callback(callback)


async def autojoin_enable_callback(callback: CallbackQuery):
    """Включить автодопуск"""
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    await db.set_auto_accept_join_requests(chat_id, True)
    await settings_open_autojoin_callback(callback)


async def autojoin_disable_callback(callback: CallbackQuery):
    """Выключить автодопуск"""
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    await db.set_auto_accept_join_requests(chat_id, False)
    await settings_open_autojoin_callback(callback)


async def autojoin_notify_enable_callback(callback: CallbackQuery):
    """Включить уведомления автодопуска"""
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    await db.set_auto_accept_notify(chat_id, True)
    await settings_open_autojoin_callback(callback)


async def autojoin_notify_disable_callback(callback: CallbackQuery):
    """Выключить уведомления автодопуска"""
    chat_id = callback.message.chat.id
    effective_rank = await get_effective_rank(chat_id, callback.from_user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await db.set_auto_accept_notify(chat_id, False)
    await settings_open_autojoin_callback(callback)


async def settings_back_root_callback(callback: CallbackQuery):
    """Вернуться к корню настроек"""
    try:
        chat = callback.message.chat
        user = callback.from_user
        effective_rank = await get_effective_rank(chat.id, user.id)
        
        settings_text, markup = await build_settings_menu(chat.id, effective_rank)
        await callback.message.edit_text(settings_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_back_root_callback: {e}")
        await callback.answer("Ошибка")


async def settings_main_callback(callback: CallbackQuery):
    """Главное меню настроек"""
    await settings_back_root_callback(callback)


async def settings_close_callback(callback: CallbackQuery):
    """Закрыть меню настроек"""
    try:
        warn_settings_context.discard((callback.message.chat.id, callback.message.message_id))
        rank_settings_context.discard((callback.message.chat.id, callback.message.message_id))
        await callback.message.delete()
    except Exception:
        await callback.answer("Закрыто")


async def settings_resetconfig_callback(callback: CallbackQuery):
    """Обработчик кнопки сброса настроек из меню"""
    chat = callback.message.chat
    user = callback.from_user
    
    effective_rank = await get_effective_rank(chat.id, user.id)
    if effective_rank > RANK_ADMIN:
        await callback.answer("❌ Только администратор или владелец чата может сбросить настройки!", show_alert=True)
        return
    
    text = (
        "⚠️ <b>Сброс всех настроек</b>\n\n"
        "Вы уверены, что хотите сбросить <b>все настройки</b> чата к значениям по умолчанию?\n\n"
        "<b>Будут сброшены:</b>\n"
        "• Настройки варнов\n"
        "• Настройки статистики\n"
        "• Права рангов\n"
        "• Русский префикс\n"
        "• Автодопуск\n"
        "• Настройки анти-спама\n"
        "• Настройки утилит\n"
        "• Настройки гифок\n"
        "• Настройки топ чатов\n\n"
        "⚠️ <i>Это действие нельзя отменить!</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Да, сбросить все",
        callback_data="resetconfig_confirm"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="resetconfig_cancel"
    ))
    builder.add(InlineKeyboardButton(
        text="🔙 Назад к настройкам",
        callback_data="settings_main"
    ))
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await callback.answer()


@require_admin_rights
@require_bot_admin_rights
async def autojoin_command(message: Message):
    """Включить/выключить авто-принятие заявок: /autojoin on|off"""
    chat = message.chat
    args = (message.text or "").split()
    if len(args) < 2 or args[1].lower() not in ("on", "off"):
        current = await db.get_auto_accept_join_requests(chat.id)
        status = "включено" if current else "выключено"
        await message.answer(
            "⚙️ <b>Авто-принятие заявок</b>\n\n"
            f"Текущее состояние: <b>{status}</b>\n"
            "Используйте: <code>/autojoin on</code> или <code>/autojoin off</code>",
            parse_mode=ParseMode.HTML
        )
        return
    enabled = args[1].lower() == "on"
    await db.set_auto_accept_join_requests(chat.id, enabled)
    await message.answer("✅ Авто-принятие заявок " + ("включено" if enabled else "выключено"))


@require_admin_rights
@require_bot_admin_rights
async def russianprefix_command(message: Message):
    """Команда настройки префикса для русских команд"""
    chat = message.chat
    user = message.from_user
    
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    if effective_rank != RANK_OWNER:
        await message.answer("❌ Только владелец чата может изменить эту настройку!")
        return
    
    current_setting = await db.get_russian_commands_prefix_setting(chat.id)
    
    builder = InlineKeyboardBuilder()
    
    if current_setting:
        builder.add(InlineKeyboardButton(
            text="❌ Отключить префикс",
            callback_data="russianprefix_disable"
        ))
        status_text = "✅ <b>Включен</b> - русские команды требуют префикс \"Пиксель\""
        example_text = "Пример: <code>Пиксель стата</code> или <code>Пиксель мут @user 5 минут</code>"
    else:
        builder.add(InlineKeyboardButton(
            text="✅ Включить префикс",
            callback_data="russianprefix_enable"
        ))
        status_text = "❌ <b>Отключен</b> - русские команды работают без префикса"
        example_text = "Пример: <code>стата</code> или <code>мут @user 5 минут</code>"
    
    builder.adjust(1)
    
    settings_text = f"""
🇷🇺 <b>Настройка префикса для русских команд</b>

<b>Статус:</b> {status_text}

<b>Описание:</b>
Эта настройка помогает избежать конфликтов с другими ботами. 
Когда включена, русские команды должны начинаться с "Пиксель".

{example_text}

<i>Рекомендация: Включите префикс в чатах с несколькими ботами.</i>
    """
    
    await message.answer(
        settings_text,
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )


async def russianprefix_enable_callback(callback: CallbackQuery):
    """Включить префикс для русских команд"""
    chat = callback.message.chat
    user = callback.from_user
    
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец чата может изменить эту настройку!")
        return
    
    success = await db.set_russian_commands_prefix_setting(chat.id, True)
    
    if success:
        await callback.message.edit_text(
            "✅ <b>Префикс для русских команд включен!</b>\n\n"
            "Теперь русские команды должны начинаться с \"Пиксель\":\n"
            "• <code>Пиксель стата</code>\n"
            "• <code>Пиксель мут @user 5 минут</code>\n"
            "• <code>Пиксель настройки</code>\n\n"
            "Это поможет избежать конфликтов с другими ботами.",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer("❌ Ошибка при изменении настройки!")
    
    await callback.answer()


async def russianprefix_disable_callback(callback: CallbackQuery):
    """Отключить префикс для русских команд"""
    chat = callback.message.chat
    user = callback.from_user
    
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец чата может изменить эту настройку!")
        return
    
    success = await db.set_russian_commands_prefix_setting(chat.id, False)
    
    if success:
        await callback.message.edit_text(
            "❌ <b>Префикс для русских команд отключен!</b>\n\n"
            "Теперь русские команды работают без префикса:\n"
            "• <code>стата</code>\n"
            "• <code>мут @user 5 минут</code>\n"
            "• <code>настройки</code>\n\n"
            "⚠️ <b>Внимание:</b> Это может вызвать конфликты с другими ботами.",
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.answer("❌ Ошибка при изменении настройки!")
    
    await callback.answer()


async def rules_command(message: Message):
    """Команда для управления правилами чата"""
    chat = message.chat
    user = message.from_user
    chat_id = chat.id
    user_id = user.id
    
    logger.info(f"rules_command вызван в чате {chat_id} пользователем {user_id}, текст: {message.text}")
    
    command_text = message.text or ""
    logger.debug(f"Исходный command_text: '{command_text}'")
    match = re.match(r'^/rules(@\w+)?\s*(.*)$', command_text, re.IGNORECASE | re.DOTALL)
    if match:
        command_text = match.group(2)  # Извлекаем только аргументы (все после команды), сохраняя форматирование
    else:
        command_text = ""
    
    logger.debug(f"command_text после обработки: '{command_text}', пустой: {not command_text or not command_text.strip()}")
    
    # Проверяем, пустой ли текст (после удаления пробелов в начале и конце)
    if not command_text or not command_text.strip():
        logger.info(f"Показываем правила для чата {chat_id}")
        try:
            logger.debug(f"Вызываем db.get_rules_text для чата {chat_id}")
            current_rules = await db.get_rules_text(chat_id)
            logger.info(f"Получены правила: {current_rules is not None}, длина: {len(current_rules) if current_rules else 0}")
            
            if current_rules:
                if len(current_rules) <= 4096:
                    text = f"📋 <b>Правила чата</b>\n\n{current_rules}"
                    logger.debug(f"Отправляем правила (длина: {len(text)})")
                    await message.answer(text, parse_mode=ParseMode.HTML)
                else:
                    chunks = [current_rules[i:i+4000] for i in range(0, len(current_rules), 4000)]
                    logger.debug(f"Отправляем правила частями ({len(chunks)} частей)")
                    await message.answer(
                        f"📋 <b>Правила чата</b> (часть 1/{len(chunks)})\n\n{chunks[0]}",
                        parse_mode=ParseMode.HTML
                    )
                    for i, chunk in enumerate(chunks[1:], 2):
                        await message.answer(
                            f"📋 <b>Правила чата</b> (часть {i}/{len(chunks)})\n\n{chunk}",
                            parse_mode=ParseMode.HTML
                        )
            else:
                logger.info("Правила не установлены, отправляем сообщение")
                await message.answer("📋 <b>Правила чата</b>\n\nПравила еще не установлены.", parse_mode=ParseMode.HTML)
                logger.info("Сообщение об отсутствии правил отправлено")
        except Exception as e:
            logger.error(f"Ошибка при показе правил в чате {chat_id}: {e}", exc_info=True)
            try:
                await message.answer("❌ Ошибка при получении правил чата.")
            except:
                pass
        return
    
    can_manage_rules = await check_permission(chat_id, user_id, 'can_manage_rules', lambda r: r <= 2)
    if not can_manage_rules:
        quote = await get_philosophical_access_denied_message()
        await message.answer(quote)
        return
    
    # Проверяем на "clear" (без учета пробелов в начале/конце)
    rules_text_stripped = command_text.strip()
    
    if rules_text_stripped.lower() == "clear":
        success = await db.set_rules_text(chat_id, None)
        if success:
            await message.answer("✅ Правила чата удалены.")
        else:
            await message.answer("❌ Ошибка при удалении правил.")
        return
    
    # Используем оригинальный текст с форматированием для сохранения
    rules_text = command_text
    
    # Убираем только ведущие и завершающие пробелы/переносы для проверки длины
    rules_text_for_validation = rules_text.strip()
    
    if len(rules_text_for_validation) > 4000:
        await message.answer(
            f"❌ Текст правил слишком длинный!\n\n"
            f"Текущая длина: {len(rules_text_for_validation)} символов\n"
            f"Максимальная длина: 4000 символов"
        )
        return
    
    # Проверка качества текста использует текст без ведущих/завершающих пробелов
    is_valid, error_msg = is_text_meaningful(rules_text_for_validation)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    
    # Сохраняем оригинальный текст для preview (до замены на HTML)
    original_rules_text = rules_text
    
    rules_text = re.sub(
        r'(https?://(?:www\.)?telegra\.ph/[^\s<>"\'()]+|www\.telegra\.ph/[^\s<>"\'()]+)',
        lambda m: f'<a href="{"https://" if not m.group(1).startswith("http") else ""}{m.group(1)}">Telegraph</a>',
        rules_text,
        flags=re.IGNORECASE
    )
    rules_text = re.sub(
        r'(https?://(?:www\.)?teletype\.in/[^\s<>"\'()]+|www\.teletype\.in/[^\s<>"\'()]+)',
        lambda m: f'<a href="{"https://" if not m.group(1).startswith("http") else ""}{m.group(1)}">Teletype</a>',
        rules_text,
        flags=re.IGNORECASE
    )
    
    success = await db.set_rules_text(chat_id, rules_text)
    
    if success:
        preview = original_rules_text[:3500] + "..." if len(original_rules_text) > 3500 else original_rules_text
        from html import escape
        preview_escaped = escape(preview)
        
        await message.answer(
            f"✅ <b>Правила чата обновлены!</b>\n\n"
            f"📏 <b>Длина:</b> {len(original_rules_text)} символов\n\n"
            f"📋 <b>Правила:</b>\n"
            f"<code>{preview_escaped}</code>",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer("❌ Ошибка при сохранении правил.")


async def settings_open_ruprefix_callback(callback: CallbackQuery):
    """Открыть настройки русского префикса"""
    chat = callback.message.chat
    user = callback.from_user
    
    effective_rank = await get_effective_rank(chat.id, user.id)
    if effective_rank not in (RANK_OWNER, RANK_ADMIN):
        await callback.answer("Эта настройка доступна только владельцу/администратору чата", show_alert=True)
        return
    
    current_setting = await db.get_russian_commands_prefix_setting(chat.id)
    
    builder = InlineKeyboardBuilder()
    
    if current_setting:
        builder.button(text="❌ Отключить", callback_data="russianprefix_disable")
        status_text = "✅ Включен"
    else:
        builder.button(text="✅ Включить", callback_data="russianprefix_enable")
        status_text = "❌ Выключен"
    
    builder.button(text="🔙 Назад", callback_data="settings_main")
    builder.adjust(1, 1)
    
    text = (
        "🇷🇺 <b>Префикс для русских команд</b>\n\n"
        f"Статус: <b>{status_text}</b>\n\n"
        "Когда включено — команды должны начинаться с \"Пиксель\"."
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


@require_admin_rights
@require_bot_admin_rights
async def warnconfig_command(message: Message):
    """Команда настройки системы варнов"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await message.answer(quote)
        return
    
    await warnconfig_show_settings(message, chat_id, from_command=True)


async def warnconfig_show_settings(message, chat_id, from_settings: bool = False, from_command: bool = False):
    """Функция для отображения настроек варнов"""
    try:
        warn_settings = await moderation_db.get_warn_settings(chat_id)
        
        mute_time_text = "Не установлено"
        if warn_settings['mute_duration']:
            mute_time_text = format_mute_duration(warn_settings['mute_duration'])
        
        if warn_settings['punishment_type'] == 'kick':
            punishment_text = "Кик"
        elif warn_settings['punishment_type'] == 'mute':
            punishment_text = "Мут"
        elif warn_settings['punishment_type'] == 'ban':
            punishment_text = "Бан"
        else:
            punishment_text = "Неизвестно"
        
        if warn_settings['punishment_type'] == 'mute':
            message_text = (
                f"⚠️ <b>Настройки варнов</b>\n\n"
                f"<b>Лимит:</b> {warn_settings['warn_limit']}\n"
                f"<b>Наказание:</b> {punishment_text}\n"
                f"<b>Время мута:</b> {mute_time_text}"
            )
        elif warn_settings['punishment_type'] == 'ban':
            message_text = (
                f"⚠️ <b>Настройки варнов</b>\n\n"
                f"<b>Лимит:</b> {warn_settings['warn_limit']}\n"
                f"<b>Наказание:</b> {punishment_text}\n"
                f"<b>Время бана:</b> {mute_time_text}"
            )
        else:
            message_text = (
                f"⚠️ <b>Настройки варнов</b>\n\n"
                f"<b>Лимит:</b> {warn_settings['warn_limit']}\n"
                f"<b>Наказание:</b> {punishment_text}"
            )
        
        builder = InlineKeyboardBuilder()
        
        builder.button(text="🔢 Лимит", callback_data="warnconfig_limit")
        builder.button(text="⚡ Наказание", callback_data="warnconfig_punishment")
        
        if warn_settings['punishment_type'] == 'mute':
            builder.button(text="⏱ Время мута", callback_data="warnconfig_mutetime")
        elif warn_settings['punishment_type'] == 'ban':
            builder.button(text="⏱ Время бана", callback_data="warnconfig_bantime")
        
        builder.button(text="🔙 Назад", callback_data="settings_main")
        builder.adjust(1)
        
        if from_command:
            await message.answer(message_text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        else:
            await message.edit_text(message_text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка при отображении настроек варнов для чата {chat_id}: {e}")


async def settings_open_warn_callback(callback: CallbackQuery):
    """Открыть настройки варнов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    await warnconfig_show_settings(callback.message, chat_id, from_settings=True)
    await safe_answer_callback(callback)


async def warnconfig_limit_callback(callback: CallbackQuery):
    """Обработчик кнопки изменения лимита варнов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    builder = InlineKeyboardBuilder()
    
    for i in range(1, 11):
        builder.button(text=str(i), callback_data=f"warnlimit_{i}")
    
    builder.button(text="🔙 Назад", callback_data="warnconfig_back")
    builder.adjust(5, 5, 1)
    
    await callback.message.edit_text(
        "🔢 <b>Выберите лимит варнов:</b>\n\n"
        "Количество предупреждений, после которых будет применено наказание.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await safe_answer_callback(callback)


async def warnlimit_set_callback(callback: CallbackQuery):
    """Обработчик установки лимита варнов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    limit = int(callback.data.split("_")[1])
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    try:
        await moderation_db.update_warn_settings(chat_id, warn_limit=limit)
        await safe_answer_callback(callback, f"✅ Лимит варнов установлен: {limit}")
        await warnconfig_show_settings(callback.message, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при установке лимита варнов: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при установке лимита")


async def warnconfig_punishment_callback(callback: CallbackQuery):
    """Обработчик кнопки изменения типа наказания"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    builder = InlineKeyboardBuilder()
    
    builder.button(text="💨 Кик", callback_data="warnpunishment_kick")
    builder.button(text="🔇 Мут", callback_data="warnpunishment_mute")
    builder.button(text="🚫 Бан", callback_data="warnpunishment_ban")
    builder.button(text="🔙 Назад", callback_data="warnconfig_back")
    builder.adjust(2, 1, 1)
    
    await callback.message.edit_text(
        "⚡ <b>Выберите тип наказания:</b>\n\n"
        "• <b>Кик</b> - исключение из чата\n"
        "• <b>Мут</b> - временное ограничение на отправку сообщений\n"
        "• <b>Бан</b> - постоянный запрет на вход в чат",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await safe_answer_callback(callback)


async def warnpunishment_set_callback(callback: CallbackQuery):
    """Обработчик установки типа наказания"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    punishment_type = callback.data.split("_")[1]
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    try:
        await moderation_db.update_warn_settings(chat_id, punishment_type=punishment_type)
        
        punishment_names = {'kick': 'Кик', 'mute': 'Мут', 'ban': 'Бан'}
        punishment_text = punishment_names.get(punishment_type, "Неизвестно")
        
        await safe_answer_callback(callback, f"✅ Тип наказания установлен: {punishment_text}")
        await warnconfig_show_settings(callback.message, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при установке типа наказания: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при установке типа наказания")


async def warnconfig_mutetime_callback(callback: CallbackQuery):
    """Обработчик кнопки изменения времени мута"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    builder = InlineKeyboardBuilder()
    
    times = [
        (300, "5 минут"), (900, "15 минут"), (1800, "30 минут"),
        (3600, "1 час"), (7200, "2 часа"), (21600, "6 часов"),
        (43200, "12 часов"), (86400, "1 день"), (172800, "2 дня"),
        (259200, "3 дня"), (432000, "5 дней"), (604800, "7 дней")
    ]
    
    for duration, text in times:
        builder.button(text=text, callback_data=f"warnmutetime_{duration}")
    
    builder.button(text="🔙 Назад", callback_data="warnconfig_back")
    builder.adjust(2, 2, 2, 2, 2, 2, 1)
    
    await callback.message.edit_text(
        "⏰ <b>Выберите время мута:</b>\n\n"
        "Время, на которое пользователь будет замучен при достижении лимита варнов.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await safe_answer_callback(callback)


async def warnmutetime_set_callback(callback: CallbackQuery):
    """Обработчик установки времени мута"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    duration = int(callback.data.split("_")[1])
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    try:
        await moderation_db.update_warn_settings(chat_id, mute_duration=duration)
        time_text = format_mute_duration(duration)
        await safe_answer_callback(callback, f"✅ Время мута установлено: {time_text}")
        await warnconfig_show_settings(callback.message, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при установке времени мута: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при установке времени мута")


async def warnconfig_bantime_callback(callback: CallbackQuery):
    """Обработчик кнопки изменения времени бана"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    builder = InlineKeyboardBuilder()
    
    times = [
        (3600, "1 час"), (21600, "6 часов"), (86400, "1 день"),
        (259200, "3 дня"), (604800, "7 дней"), (1296000, "15 дней"),
        (2592000, "30 дней"), (0, "Навсегда")
    ]
    
    for duration, text in times:
        builder.button(text=text, callback_data=f"warnbantime_{duration}")
    
    builder.button(text="🔙 Назад", callback_data="warnconfig_back")
    builder.adjust(2, 2, 2, 2, 1)
    
    await callback.message.edit_text(
        "⏰ <b>Выберите время бана:</b>\n\n"
        "Время, на которое пользователь будет забанен при достижении лимита варнов.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup()
    )
    
    await safe_answer_callback(callback)


async def warnbantime_set_callback(callback: CallbackQuery):
    """Обработчик установки времени бана"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    duration = int(callback.data.split("_")[1])
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    try:
        await moderation_db.update_warn_settings(chat_id, mute_duration=duration)
        time_text = "Навсегда" if duration == 0 else format_mute_duration(duration)
        await safe_answer_callback(callback, f"✅ Время бана установлено: {time_text}")
        await warnconfig_show_settings(callback.message, chat_id)
    except Exception as e:
        logger.error(f"Ошибка при установке времени бана: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при установке времени бана")


async def warnconfig_back_callback(callback: CallbackQuery):
    """Обработчик кнопки 'Назад' в настройках варнов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_warns = await check_permission(chat_id, user_id, 'can_config_warns', lambda r: r <= 2)
    if not can_config_warns:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote)
        return
    
    await warnconfig_show_settings(callback.message, chat_id)
    await safe_answer_callback(callback)




async def settings_open_stat_callback(callback: CallbackQuery):
    """Открыть настройки статистики"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    try:
        stat_settings = await db.get_chat_stat_settings(chat_id)
        builder = InlineKeyboardBuilder()

        stats_icon = "✅" if stat_settings['stats_enabled'] else "❌"
        builder.button(text=f"{stats_icon} Статистика включена", callback_data="statconfig_toggle_stats")
        media_icon = "✅" if stat_settings.get('count_media', True) else "❌"
        builder.button(text=f"{media_icon} Считать медиа", callback_data="statconfig_toggle_media")
        profile_icon = "✅" if stat_settings.get('profile_enabled', True) else "❌"
        builder.button(text=f"{profile_icon} Команда профиля", callback_data="statconfig_toggle_profile")
        userinfo_icon = "✅" if stat_settings.get('userinfo_enabled', True) else "❌"
        builder.button(text=f"{userinfo_icon} Команда userinfo", callback_data="statconfig_toggle_userinfo")
        builder.adjust(1)
        builder.button(text="🔙 Назад", callback_data="settings_main")

        message_text = "📊 <b>Общие команды</b>\n\n"
        message_text += f"Статистика: {'✅ включена' if stat_settings['stats_enabled'] else '❌ отключена'}\n"
        message_text += f"Userinfo: {'✅ включена' if stat_settings.get('userinfo_enabled', True) else '❌ отключена'}\n\n"
        message_text += "Выберите настройку:"

        await callback.message.edit_text(message_text, parse_mode=ParseMode.HTML)
        await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка settings_open_stat_callback: {e}")
        await callback.answer("❌ Ошибка при открытии настроек", show_alert=True)


async def statconfig_toggle_stats_callback(callback: CallbackQuery):
    """Переключить статистику"""
    if not await _ensure_admin(callback):
        return
    chat_id = callback.message.chat.id
    try:
        stat_settings = await db.get_chat_stat_settings(chat_id)
        new_value = not stat_settings['stats_enabled']
        await db.set_chat_stats_enabled(chat_id, new_value)
        await settings_open_stat_callback(callback)
    except Exception as e:
        logger.error(f"Ошибка statconfig_toggle_stats: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


async def statconfig_toggle_media_callback(callback: CallbackQuery):
    """Переключить подсчет медиа"""
    if not await _ensure_admin(callback):
        return
    chat_id = callback.message.chat.id
    try:
        stat_settings = await db.get_chat_stat_settings(chat_id)
        new_value = not stat_settings.get('count_media', True)
        await db.set_chat_stats_count_media(chat_id, new_value)
        await settings_open_stat_callback(callback)
    except Exception as e:
        logger.error(f"Ошибка statconfig_toggle_media: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


async def statconfig_toggle_profile_callback(callback: CallbackQuery):
    """Переключить команду профиля"""
    if not await _ensure_admin(callback):
        return
    chat_id = callback.message.chat.id
    try:
        stat_settings = await db.get_chat_stat_settings(chat_id)
        new_value = not stat_settings.get('profile_enabled', True)
        await db.set_chat_stats_profile_enabled(chat_id, new_value)
        await settings_open_stat_callback(callback)
    except Exception as e:
        logger.error(f"Ошибка statconfig_toggle_profile: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)


async def statconfig_toggle_userinfo_callback(callback: CallbackQuery):
    """Переключить команду userinfo"""
    if not await _ensure_admin(callback):
        return
    chat_id = callback.message.chat.id
    try:
        stat_settings = await db.get_chat_stat_settings(chat_id)
        new_value = not stat_settings.get('userinfo_enabled', True)
        await db.set_chat_stats_userinfo_enabled(chat_id, new_value)
        await settings_open_stat_callback(callback)
    except Exception as e:
        logger.error(f"Ошибка statconfig_toggle_userinfo: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)



async def rankconfig_command(message: Message):
    """Команда настройки прав рангов"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 2)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await message.answer(quote)
        return
    
    try:
        await db.initialize_rank_permissions(chat_id)
        
        message_text = (
            "⚙️ <b>Настройка прав рангов</b>\n\n"
            "Выберите ранг для настройки:"
        )
        
        builder = InlineKeyboardBuilder()
        
        for rank in [1, 2, 3, 4]:
            rank_name = get_rank_name(rank)
            emoji = "👑" if rank == 1 else "⚜️" if rank == 2 else "🛡" if rank == 3 else "🔰"
            builder.button(text=f"{emoji} {rank_name}", callback_data=f"rankconfig_select_{rank}")
        
        builder.adjust(2)
        
        builder.button(text="🔄 Сбросить все к стандарту", callback_data="rankconfig_reset_all")
        
        await message.answer(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отображении настроек рангов для чата {chat_id}: {e}")
        await message.answer("❌ Ошибка при отображении настроек рангов")


async def show_rankconfig_main_menu(message, chat_id, from_settings: bool = None):
    """Показать главное меню настроек рангов"""
    try:
        if from_settings is None:
            from_settings = _is_rank_settings_context(chat_id, message.message_id)

        message_text = (
            "🔰 <b>Настройка прав рангов</b>\n\n"
            "Выберите ранг:"
        )
        
        builder = InlineKeyboardBuilder()
        
        for rank in [1, 2, 3, 4]:
            rank_name = get_rank_name(rank)
            emoji = "👑" if rank == 1 else "⚜️" if rank == 2 else "🛡" if rank == 3 else "🔰"
            builder.button(text=f"{emoji} {rank_name}", callback_data=f"rankconfig_select_{rank}")
        
        builder.button(text="🔄 Сбросить", callback_data="rankconfig_reset_all")
        if from_settings:
            builder.button(text="🔙 Назад", callback_data="settings_main")
            rank_settings_context.add((chat_id, message.message_id))
            builder.adjust(2, 2, 1, 1)
        else:
            rank_settings_context.discard((chat_id, message.message_id))
            builder.adjust(2, 2, 1)
        
        await message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка при отображении главного меню настроек рангов: {e}")


async def settings_open_ranks_callback(callback: CallbackQuery):
    """Открыть настройки прав рангов"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 2)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await callback.answer(quote, show_alert=True)
        return

    try:
        rank_settings_context.add((chat_id, callback.message.message_id))
        await show_rankconfig_main_menu(callback.message, chat_id)
        await safe_answer_callback(callback)
    except Exception as e:
        logger.error(f"Ошибка settings_open_ranks_callback: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при загрузке настроек", show_alert=True)


async def rankconfig_select_callback(callback: CallbackQuery):
    """Выбрать ранг для настройки"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 2)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote, show_alert=True)
        return
    
    from_settings = _is_rank_settings_context(chat_id, callback.message.message_id)
    rank = int(callback.data.split("_")[2])
    await show_rank_permissions(callback.message, chat_id, rank, from_settings)
    await safe_answer_callback(callback)


async def rankconfig_back_callback(callback: CallbackQuery):
    """Назад в меню настроек рангов"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 2)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote, show_alert=True)
        return
    
    # Определяем, откуда пришли (из настроек или из команды)
    from_settings = _is_rank_settings_context(chat_id, callback.message.message_id)
    await show_rankconfig_main_menu(callback.message, chat_id, from_settings)
    await safe_answer_callback(callback)


async def rankconfig_reset_all_callback(callback: CallbackQuery):
    """Сбросить все настройки рангов"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 2)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await callback.answer(quote, show_alert=True)
        return
    
    try:
        for rank in [1, 2, 3, 4]:
            await db.reset_rank_permissions_to_default(chat_id, rank)
        
        await safe_answer_callback(callback, "✅ Все настройки рангов сброшены к стандартным", show_alert=True)
        await show_rankconfig_main_menu(callback.message, chat_id)
    except Exception as e:
        logger.error(f"Ошибка rankconfig_reset_all: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при сбросе настроек", show_alert=True)


async def show_rank_permissions(message, chat_id, rank, from_settings: bool = None):
    """Показать права конкретного ранга"""
    try:
        if from_settings is None:
            from_settings = _is_rank_settings_context(chat_id, message.message_id)

        # Получаем права из БД и объединяем с дефолтными
        db_permissions = await db.get_all_rank_permissions(chat_id, rank)
        default_permissions = DEFAULT_RANK_PERMISSIONS.get(rank, {})
        # Используем дефолтные права как основу и перезаписываем значениями из БД
        permissions = {**default_permissions, **db_permissions}
        
        rank_name = get_rank_name(rank)
        emoji = "👑" if rank == 1 else "⚜️" if rank == 2 else "🛡" if rank == 3 else "🔰"
        
        message_text = f"{emoji} <b>Права: {rank_name}</b>\n\n"
        
        message_text += "<b>Команды модерации:</b>\n"
        warn_icon = "✅" if permissions.get('can_warn', False) else "❌"
        unwarn_icon = "✅" if permissions.get('can_unwarn', False) else "❌"
        mute_icon = "✅" if permissions.get('can_mute', False) else "❌"
        unmute_icon = "✅" if permissions.get('can_unmute', False) else "❌"
        kick_icon = "✅" if permissions.get('can_kick', False) else "❌"
        ban_icon = "✅" if permissions.get('can_ban', False) else "❌"
        unban_icon = "✅" if permissions.get('can_unban', False) else "❌"
        
        message_text += f"{warn_icon} Варны  {unwarn_icon} Снятие варнов\n"
        message_text += f"{mute_icon} Муты  {unmute_icon} Размуты\n"
        message_text += f"{kick_icon} Кики  {ban_icon} Баны  {unban_icon} Разбаны\n\n"
        
        message_text += "<b>Назначение рангов:</b>\n"
        assign_4_icon = "✅" if permissions.get('can_assign_rank_4', False) else "❌"
        assign_3_icon = "✅" if permissions.get('can_assign_rank_3', False) else "❌"
        assign_2_icon = "✅" if permissions.get('can_assign_rank_2', False) else "❌"
        remove_icon = "✅" if permissions.get('can_remove_rank', False) else "❌"
        
        message_text += f"{assign_4_icon} Младшие модераторы  {assign_3_icon} Старшие модераторы\n"
        message_text += f"{assign_2_icon} Администраторы  {remove_icon} Снятие рангов\n\n"
        
        message_text += "<b>Настройки:</b>\n"
        config_warns_icon = "✅" if permissions.get('can_config_warns', False) else "❌"
        config_ranks_icon = "✅" if permissions.get('can_config_ranks', False) else "❌"
        config_ranks_lock = " 🔒" if rank == 1 else ""
        
        message_text += f"{config_warns_icon} Настройки варнов  {config_ranks_icon} Настройки рангов{config_ranks_lock}\n\n"
        
        # Команды
        message_text += "<b>Команды:</b>\n"
        manage_rules_icon = "✅" if permissions.get('can_manage_rules', False) else "❌"
        punishhistory_icon = "✅" if permissions.get('can_view_punishhistory', False) else "❌"
        message_text += f"{manage_rules_icon} Управление правилами\n"
        message_text += f"{punishhistory_icon} История наказаний"
        
        builder = InlineKeyboardBuilder()
        
        builder.button(text="⚔️ Команды модерации", callback_data=f"rankconfig_category_{rank}_moderation")
        builder.button(text="👥 Назначение рангов", callback_data=f"rankconfig_category_{rank}_assignment")
        builder.button(text="⚙️ Доступ к настройкам", callback_data=f"rankconfig_category_{rank}_config")
        builder.button(text="📋 Команды", callback_data=f"rankconfig_category_{rank}_commands")
        builder.button(text="🔄 Стандартный конфиг", callback_data=f"rankconfig_reset_{rank}")
        builder.button(text="🔙 Назад", callback_data="rankconfig_back")
        if from_settings:
            builder.button(text="🔙 Назад в настройки", callback_data="settings_main")
        else:
            rank_settings_context.discard((chat_id, message.message_id))

        if from_settings:
            builder.adjust(2, 2, 1, 1, 1, 1)
        else:
            builder.adjust(2, 2, 1, 1)
        
        await message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        error_str = str(e).lower()
        if "message is not modified" in error_str or "exactly the same" in error_str:
            logger.debug(f"Сообщение не изменилось при отображении прав ранга {rank} в чате {chat_id}")
        else:
            logger.error(f"Ошибка при отображении прав ранга {rank} в чате {chat_id}: {e}")
            try:
                await message.answer("❌ Ошибка при отображении прав ранга")
            except Exception:
                pass  # Игнорируем ошибки при отправке сообщения об ошибке


async def show_rank_category_permissions(message, chat_id, rank, category, from_settings: bool = None):
    """Показать права конкретной категории для ранга"""
    try:
        if from_settings is None:
            from_settings = _is_rank_settings_context(chat_id, message.message_id)

        # Получаем права из БД и объединяем с дефолтными
        db_permissions = await db.get_all_rank_permissions(chat_id, rank)
        default_permissions = DEFAULT_RANK_PERMISSIONS.get(rank, {})
        # Используем дефолтные права как основу и перезаписываем значениями из БД
        permissions = {**default_permissions, **db_permissions}
        
        rank_name = get_rank_name(rank)
        emoji = "👑" if rank == 1 else "⚜️" if rank == 2 else "🛡" if rank == 3 else "🔰"
        
        if category == "moderation":
            message_text = f"{emoji} <b>{rank_name} - Команды модерации</b>\n\n"
            message_text += "Выберите право для изменения:\n\n"
            
            builder = InlineKeyboardBuilder()
            
            moderation_perms = [
                ('can_warn', 'Варны'),
                ('can_unwarn', 'Снятие варнов'),
                ('can_mute', 'Муты'),
                ('can_unmute', 'Размуты'),
                ('can_kick', 'Кики'),
                ('can_ban', 'Баны'),
                ('can_unban', 'Разбаны')
            ]
            
            for perm_type, perm_name in moderation_perms:
                current_value = permissions.get(perm_type, False)
                icon = "✅" if current_value else "❌"
                builder.button(text=f"{icon} {perm_name}", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
            
        elif category == "assignment":
            message_text = f"{emoji} <b>{rank_name} - Назначение рангов</b>\n\n"
            message_text += "Выберите право для изменения:\n\n"
            
            builder = InlineKeyboardBuilder()
            
            assignment_perms = [
                ('can_assign_rank_4', 'Младшие модераторы'),
                ('can_assign_rank_3', 'Старшие модераторы'),
                ('can_assign_rank_2', 'Администраторы'),
                ('can_remove_rank', 'Снятие рангов')
            ]
            
            for perm_type, perm_name in assignment_perms:
                current_value = permissions.get(perm_type, False)
                icon = "✅" if current_value else "❌"
                builder.button(text=f"{icon} {perm_name}", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
            
        elif category == "config":
            message_text = f"{emoji} <b>{rank_name} - Доступ к настройкам</b>\n\n"
            message_text += "Выберите право для изменения:\n\n"
            
            builder = InlineKeyboardBuilder()
            
            config_perms = [
                ('can_config_warns', 'Настройки варнов'),
                ('can_config_ranks', 'Настройки рангов')
            ]
            
            for perm_type, perm_name in config_perms:
                current_value = permissions.get(perm_type, False)
                icon = "✅" if current_value else "❌"
                # Для ранга владельца (ранг 1) право can_config_ranks нельзя изменять
                if rank == 1 and perm_type == 'can_config_ranks':
                    builder.button(text=f"{icon} {perm_name} 🔒", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
                else:
                    builder.button(text=f"{icon} {perm_name}", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
            
        elif category == "commands":
            message_text = f"{emoji} <b>{rank_name} - Команды</b>\n\n"
            message_text += "Выберите право для изменения:\n\n"
            
            builder = InlineKeyboardBuilder()
            
            commands_perms = [
                ('can_manage_rules', 'Управление правилами'),
                ('can_view_punishhistory', 'История наказаний')
            ]
            
            for perm_type, perm_name in commands_perms:
                current_value = permissions.get(perm_type, False)
                icon = "✅" if current_value else "❌"
                builder.button(text=f"{icon} {perm_name}", callback_data=f"rankconfig_toggle_{rank}_{perm_type}")
            
        builder.button(text="🔙 Назад", callback_data=f"rankconfig_select_{rank}")
        if from_settings:
            builder.button(text="🔙 Назад в настройки", callback_data="settings_main")
        else:
            rank_settings_context.discard((chat_id, message.message_id))

        if from_settings:
            builder.adjust(2, 2, 1, 1)
        else:
            builder.adjust(2, 2, 1)
        
        await message.edit_text(
            message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup()
        )
        
    except Exception as e:
        error_str = str(e).lower()
        if "message is not modified" in error_str or "exactly the same" in error_str:
            return
        
        logger.error(f"Ошибка при отображении категории {category} для ранга {rank} в чате {chat_id}: {e}")
        await message.answer("❌ Ошибка при отображении категории")


async def rankconfig_category_callback(callback: CallbackQuery):
    """Обработчик выбора категории прав"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 2)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote, show_alert=True)
        return
    
    # Определяем, откуда пришли (из настроек или из команды)
    from_settings = _is_rank_settings_context(chat_id, callback.message.message_id)
    
    # Парсим данные: rankconfig_category_{rank}_{category}
    parts = callback.data.split("_")
    rank = int(parts[2])
    category = parts[3]
    
    await show_rank_category_permissions(callback.message, chat_id, rank, category, from_settings)
    await safe_answer_callback(callback)


async def rankconfig_toggle_callback(callback: CallbackQuery):
    """Обработчик переключения права"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 2)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote, show_alert=True)
        return
    
    parts = callback.data.split("_")
    rank = int(parts[2])
    permission = "_".join(parts[3:])
    
    if rank == 1 and permission == 'can_config_ranks':
        await safe_answer_callback(
            callback,
            "⚠️ Вы не можете изменить право 'Настройки рангов' для ранга владельца, так как потом сами не сможете его вернуть!",
            show_alert=True
        )
        return
    
    try:
        current_value = await db.get_rank_permission(chat_id, rank, permission)
        
        if current_value is None:
            current_value = DEFAULT_RANK_PERMISSIONS.get(rank, {}).get(permission, False)
        
        new_value = not current_value
        
        await db.set_rank_permission(chat_id, rank, permission, new_value)
        
        category = "moderation"
        if permission in ['can_assign_rank_4', 'can_assign_rank_3', 'can_assign_rank_2', 'can_remove_rank']:
            category = "assignment"
        elif permission in ['can_config_warns', 'can_config_ranks']:
            category = "config"
        elif permission in ['can_manage_rules', 'can_view_punishhistory']:
            category = "commands"
        
        if permission not in ['can_view_stats', 'can_view_punishhistory']:
            await show_rank_category_permissions(callback.message, chat_id, rank, category)
        else:
            await show_rank_permissions(callback.message, chat_id, rank)
        
        perm_name_map = {
            'can_warn': 'Варны', 'can_unwarn': 'Снятие варнов',
            'can_mute': 'Муты', 'can_unmute': 'Размуты',
            'can_kick': 'Кики', 'can_ban': 'Баны', 'can_unban': 'Разбаны',
            'can_assign_rank_4': 'Младшие модераторы', 'can_assign_rank_3': 'Старшие модераторы',
            'can_assign_rank_2': 'Администраторы', 'can_remove_rank': 'Снятие рангов',
            'can_config_warns': 'Настройки варнов', 'can_config_ranks': 'Настройки рангов',
            'can_manage_rules': 'Управление правилами',
            'can_view_stats': 'Просмотр статистики',
            'can_view_punishhistory': 'История наказаний'
        }
        
        perm_name = perm_name_map.get(permission, permission)
        status = "включено" if new_value else "выключено"
        await safe_answer_callback(callback, f"✅ {perm_name}: {status}")
        
    except Exception as e:
        logger.error(f"Ошибка при переключении права {permission} для ранга {rank} в чате {chat_id}: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при изменении права", show_alert=True)


async def rankconfig_reset_callback(callback: CallbackQuery):
    """Обработчик сброса прав конкретного ранга"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    
    # Проверяем права
    can_config_ranks = await check_permission(chat_id, user_id, 'can_config_ranks', lambda r: r <= 2)
    if not can_config_ranks:
        quote = await get_philosophical_access_denied_message()
        await safe_answer_callback(callback, quote, show_alert=True)
        return
    
    rank = int(callback.data.split("_")[2])
    
    try:
        # Сбрасываем права для конкретного ранга
        await db.reset_rank_permissions_to_default(chat_id, rank)
        
        rank_name = get_rank_name(rank)
        await safe_answer_callback(callback, f"✅ Права {rank_name} сброшены к стандартным")
        
        # Возвращаемся к просмотру прав ранга
        try:
            await show_rank_permissions(callback.message, chat_id, rank)
        except Exception as e:
            # Ошибки отображения уже обработаны в show_rank_permissions
            error_str = str(e).lower()
            if "message is not modified" not in error_str and "exactly the same" not in error_str:
                logger.error(f"Критическая ошибка при отображении прав ранга {rank} после сброса в чате {chat_id}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе прав ранга {rank} в чате {chat_id}: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при сбросе прав", show_alert=True)



async def build_top_chats_settings_main(chat_id: int):
    """Главное меню настроек показа в топе"""
    from handlers.top_chats import get_top_chat_settings_async
    settings = await get_top_chat_settings_async(chat_id)
    
    builder = InlineKeyboardBuilder()
    
    builder.button(text="👁 Видимость", callback_data="top_settings_visibility")
    builder.adjust(1)
    builder.button(text="🔙 Назад", callback_data="settings_main")
    builder.adjust(1)
    
    visibility_descriptions = {
        "always": "показывать всегда (даже если частный)",
        "public_only": "показывать только если публичный",
        "never": "не показывать в топе"
    }
    
    show_in_top = settings.get('show_in_top', 'public_only')
    
    text = (
        "🏆 <b>Настройки показа в топе</b>\n\n"
        f"Видимость: {visibility_descriptions.get(show_in_top, 'неизвестно')}\n\n"
        "Выберите раздел:"
    )
    
    return text, builder.as_markup()


async def settings_open_top_callback(callback: CallbackQuery):
    """Открыть главное меню настроек показа в топе"""
    if not await _ensure_admin(callback):
        return
    
    text, markup = await build_top_chats_settings_main(callback.message.chat.id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await callback.answer()


async def top_settings_visibility_callback(callback: CallbackQuery):
    """Открыть настройки видимости"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    from handlers.top_chats import get_top_chat_settings_async
    settings = await get_top_chat_settings_async(chat_id)
    show_in_top = settings.get('show_in_top', 'public_only')
    
    builder = InlineKeyboardBuilder()
    builder.button(
        text=("✅ " if show_in_top == "always" else "") + "Показывать всегда",
        callback_data="top_setting_visibility_always"
    )
    builder.button(
        text=("✅ " if show_in_top == "public_only" else "") + "Только публичные",
        callback_data="top_setting_visibility_public_only"
    )
    builder.button(
        text=("✅ " if show_in_top == "never" else "") + "Не показывать",
        callback_data="top_setting_visibility_never"
    )
    builder.adjust(1)
    builder.button(text="🔙 Назад", callback_data="settings_open_top")
    
    text = "👁 <b>Видимость в топе</b>\n\nВыберите режим:"
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def top_setting_visibility_callback(callback: CallbackQuery):
    """Обработчик изменения настройки видимости"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    value = callback.data.replace("top_setting_visibility_", "")
    
    try:
        from handlers.top_chats import get_top_chat_settings_async, set_top_chat_settings_async
        settings = await get_top_chat_settings_async(chat_id)
        settings['show_in_top'] = value
        await set_top_chat_settings_async(chat_id, settings)
        await top_settings_visibility_callback(callback)
    except Exception as e:
        logger.error(f"Ошибка top_setting_visibility: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)



async def settings_initperms_callback(callback: CallbackQuery):
    """Показать предупреждение и подтверждение сброса прав рангов"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    effective_rank = await get_effective_rank(chat_id, user_id)

    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец может инициализировать права", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="initperms_confirm")
    builder.button(text="🔙 Назад", callback_data="settings_main")
    builder.adjust(1, 1)

    text = (
        "⚙️ <b>Сброс прав рангов</b>\n\n"
        "Это сбросит права всех рангов к стандартным настройкам.\n"
        "Продолжить?"
    )

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def initperms_confirm_callback(callback: CallbackQuery):
    """Подтверждение инициализации прав рангов"""
    if not await _ensure_admin(callback):
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    effective_rank = await get_effective_rank(chat_id, user_id)

    if effective_rank != RANK_OWNER:
        await callback.answer("❌ Только владелец может выполнять действие", show_alert=True)
        return

    try:
        success = await db.initialize_rank_permissions(chat_id)
        if success:
            message_text = (
                "✅ <b>Права рангов сброшены</b>\n\n"
                "Все значения возвращены к стандартной конфигурации."
            )
            await callback.answer("Готово")
        else:
            message_text = "❌ Не удалось инициализировать права. Попробуйте позже."
            await callback.answer("❌ Ошибка", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка initperms_confirm_callback в чате {chat_id}: {e}")
        message_text = "❌ Произошла ошибка при инициализации прав"
        await callback.answer("❌ Ошибка", show_alert=True)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="settings_main")
    builder.adjust(1)

    await callback.message.edit_text(message_text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())



async def build_utilities_menu(chat_id: int):
    """Построить главное меню утилит"""
    settings = await utilities_db.get_settings(chat_id)
    
    builder = InlineKeyboardBuilder()
    
    emoji_enabled = settings.get('emoji_spam_enabled', False)
    reaction_enabled = settings.get('reaction_spam_enabled', False)
    fake_commands_enabled = settings.get('fake_commands_enabled', False)
    auto_ban_channels_enabled = settings.get('auto_ban_channels_enabled', False)
    
    builder.button(
        text=f"{'✅' if emoji_enabled else '❌'} Эмодзи спам",
        callback_data="utilities_emoji_spam"
    )
    builder.button(
        text=f"{'✅' if reaction_enabled else '❌'} Спам реакциями",
        callback_data="utilities_reaction_spam"
    )
    builder.button(
        text=f"{'✅' if fake_commands_enabled else '❌'} Ложные команды",
        callback_data="utilities_fake_commands"
    )
    builder.button(
        text=f"{'✅' if auto_ban_channels_enabled else '❌'} Автобан каналов Telegram",
        callback_data="utilities_auto_ban_channels"
    )
    builder.button(text="🔙 Назад", callback_data="settings_main")
    
    builder.adjust(1, 1, 1, 1)
    
    text = (
        "🔧 <b>Утилиты</b>\n\n"
        "Дополнительные настройки защиты чата:\n\n"
        f"• <b>Эмодзи спам:</b> {'✅ Включено' if emoji_enabled else '❌ Выключено'}\n"
        f"• <b>Спам реакциями:</b> {'✅ Включено' if reaction_enabled else '❌ Выключено'}\n"
        f"• <b>Ложные команды:</b> {'✅ Включено' if fake_commands_enabled else '❌ Выключено'}\n"
        f"• <b>Автобан каналов Telegram:</b> {'✅ Включено' if auto_ban_channels_enabled else '❌ Выключено'}\n\n"
        "Выберите раздел:"
    )
    
    return text, builder.as_markup()


async def settings_open_utilities_callback(callback: CallbackQuery):
    """Открыть главное меню утилит"""
    if not await _ensure_admin(callback):
        return
    
    text, markup = await build_utilities_menu(callback.message.chat.id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await callback.answer()


async def utilities_back_callback(callback: CallbackQuery):
    """Вернуться в главное меню утилит"""
    if not await _ensure_admin(callback):
        return
    
    text, markup = await build_utilities_menu(callback.message.chat.id)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    await callback.answer()


async def utilities_emoji_spam_callback(callback: CallbackQuery):
    """Открыть настройки эмодзи спама"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    enabled = settings.get('emoji_spam_enabled', False)
    limit = settings.get('emoji_spam_limit', 10)
    
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text=f"{'✅' if enabled else '❌'} {'Выключить' if enabled else 'Включить'}",
        callback_data="utilities_emoji_spam_toggle"
    )
    builder.button(text="🔢 Лимит", callback_data="utilities_emoji_spam_limit")
    builder.button(text="🔙 Назад", callback_data="utilities_back")
    
    builder.adjust(1, 1, 1)
    
    text = (
        "🔧 <b>Эмодзи спам</b>\n\n"
        f"<b>Статус:</b> {'✅ Включено' if enabled else '❌ Выключено'}\n"
        f"<b>Лимит:</b> {limit} эмодзи\n\n"
        "Бот будет удалять сообщения с количеством эмодзи больше установленного лимита."
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_emoji_spam_toggle_callback(callback: CallbackQuery):
    """Переключить защиту от эмодзи спама"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    current_enabled = settings.get('emoji_spam_enabled', False)
    new_enabled = not current_enabled
    
    await utilities_db.update_setting(chat_id, 'emoji_spam_enabled', new_enabled)
    await utilities_emoji_spam_callback(callback)


async def utilities_emoji_spam_limit_callback(callback: CallbackQuery):
    """Открыть выбор лимита эмодзи"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    current_limit = settings.get('emoji_spam_limit', 10)
    
    builder = InlineKeyboardBuilder()
    
    limits = [5, 10, 15, 20]
    for limit in limits:
        check = "✅ " if limit == current_limit else ""
        builder.button(text=f"{check}{limit}", callback_data=f"utilities_emoji_limit_{limit}")
    
    builder.button(text="🔙 Назад", callback_data="utilities_emoji_spam")
    builder.adjust(2, 2, 1)
    
    text = (
        "🔢 <b>Лимит эмодзи</b>\n\n"
        f"Текущий лимит: <b>{current_limit}</b>\n\n"
        "Выберите максимальное количество кастомных emoji в сообщении:"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_emoji_spam_limit_set_callback(callback: CallbackQuery):
    """Установить лимит эмодзи"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    limit = int(callback.data.split("_")[-1])
    
    await utilities_db.update_setting(chat_id, 'emoji_spam_limit', limit)
    await utilities_emoji_spam_callback(callback)
    await callback.answer(f"✅ Лимит установлен: {limit}")


async def utilities_reaction_spam_callback(callback: CallbackQuery):
    """Открыть настройки спама реакциями"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    enabled = settings.get('reaction_spam_enabled', False)
    limit = settings.get('reaction_spam_limit', 5)
    window = settings.get('reaction_spam_window', 120)
    warning_enabled = settings.get('reaction_spam_warning_enabled', True)
    punishment = settings.get('reaction_spam_punishment', 'kick')
    ban_duration = settings.get('reaction_spam_ban_duration', 300)
    reaction_spam_silent = settings.get('reaction_spam_silent', False)
    
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text=f"{'✅' if enabled else '❌'} {'Выключить' if enabled else 'Включить'}",
        callback_data="utilities_reaction_spam_toggle"
    )
    builder.button(text="🔢 Лимит реакций", callback_data="utilities_reaction_spam_limit")
    builder.button(text="⏱ Временное окно", callback_data="utilities_reaction_spam_window")
    builder.button(
        text=f"{'✅' if warning_enabled else '❌'} Предупреждение",
        callback_data="utilities_reaction_spam_warning"
    )
    builder.button(text="⚡ Наказание", callback_data="utilities_reaction_spam_punishment")
    if punishment == 'ban':
        builder.button(text="⏱ Время бана", callback_data="utilities_reaction_spam_ban_duration")
    builder.button(
        text=f"{'✅' if reaction_spam_silent else '❌'} Наказание без уведомлений",
        callback_data="utilities_reaction_spam_silent"
    )
    builder.button(text="🔙 Назад", callback_data="utilities_back")
    
    builder.adjust(1, 1, 1, 1, 1, 1, 1, 1)
    
    window_min = window // 60
    window_text = f"{window_min} мин" if window_min > 0 else f"{window} сек"
    
    ban_duration_text = format_mute_duration(ban_duration)
    punishment_text = "Кик" if punishment == 'kick' else f"Бан ({ban_duration_text})"
    reaction_spam_silent_text = "✅ Включен" if reaction_spam_silent else "❌ Выключен"
    
    text = (
        "🔧 <b>Спам реакциями</b>\n\n"
        f"<b>Статус:</b> {'✅ Включено' if enabled else '❌ Выключено'}\n"
        f"<b>Лимит:</b> {limit} реакций\n"
        f"<b>Временное окно:</b> {window_text}\n"
        f"<b>Предупреждение:</b> {'✅ Включено' if warning_enabled else '❌ Выключено'}\n"
        f"<b>Наказание:</b> {punishment_text}\n"
        f"<b>Наказание без уведомлений:</b> {reaction_spam_silent_text}\n\n"
        "Бот будет отслеживать избыточные реакции на сообщения и применять наказания."
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_reaction_spam_toggle_callback(callback: CallbackQuery):
    """Переключить защиту от спама реакциями"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    current_enabled = settings.get('reaction_spam_enabled', False)
    new_enabled = not current_enabled
    
    await utilities_db.update_setting(chat_id, 'reaction_spam_enabled', new_enabled)
    await utilities_reaction_spam_callback(callback)


async def utilities_reaction_spam_limit_callback(callback: CallbackQuery):
    """Открыть выбор лимита реакций"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    current_limit = settings.get('reaction_spam_limit', 5)
    
    builder = InlineKeyboardBuilder()
    
    limits = [3, 5, 7, 10, 15, 20]
    for limit in limits:
        check = "✅ " if limit == current_limit else ""
        builder.button(text=f"{check}{limit}", callback_data=f"utilities_reaction_limit_{limit}")
    
    builder.button(text="🔙 Назад", callback_data="utilities_reaction_spam")
    builder.adjust(3, 3, 1)
    
    text = (
        "🔢 <b>Лимит реакций</b>\n\n"
        f"Текущий лимит: <b>{current_limit}</b>\n\n"
        "Выберите максимальное количество реакций за временное окно:"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_reaction_spam_limit_set_callback(callback: CallbackQuery):
    """Установить лимит реакций"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    limit = int(callback.data.split("_")[-1])
    
    await utilities_db.update_setting(chat_id, 'reaction_spam_limit', limit)
    await utilities_reaction_spam_callback(callback)
    await callback.answer(f"✅ Лимит установлен: {limit}")


async def utilities_reaction_spam_window_callback(callback: CallbackQuery):
    """Открыть выбор временного окна"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    current_window = settings.get('reaction_spam_window', 120)
    
    builder = InlineKeyboardBuilder()
    
    windows = [
        (30, "30 сек"),
        (60, "1 мин"),
        (120, "2 мин"),
        (300, "5 мин"),
        (600, "10 мин")
    ]
    
    for window_sec, window_text in windows:
        check = "✅ " if window_sec == current_window else ""
        builder.button(text=f"{check}{window_text}", callback_data=f"utilities_reaction_window_{window_sec}")
    
    builder.button(text="🔙 Назад", callback_data="utilities_reaction_spam")
    builder.adjust(2, 2, 1, 1)
    
    current_window_text = f"{current_window // 60} мин" if current_window >= 60 else f"{current_window} сек"
    
    text = (
        "⏱ <b>Временное окно</b>\n\n"
        f"Текущее окно: <b>{current_window_text}</b>\n\n"
        "Выберите временное окно для подсчета реакций:"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_reaction_spam_window_set_callback(callback: CallbackQuery):
    """Установить временное окно"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    window = int(callback.data.split("_")[-1])
    
    await utilities_db.update_setting(chat_id, 'reaction_spam_window', window)
    await utilities_reaction_spam_callback(callback)
    
    window_text = f"{window // 60} мин" if window >= 60 else f"{window} сек"
    await callback.answer(f"✅ Окно установлено: {window_text}")


async def utilities_reaction_spam_warning_callback(callback: CallbackQuery):
    """Переключить предупреждение"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    current_warning = settings.get('reaction_spam_warning_enabled', True)
    new_warning = not current_warning
    
    await utilities_db.update_setting(chat_id, 'reaction_spam_warning_enabled', new_warning)
    await utilities_reaction_spam_callback(callback)


async def utilities_reaction_spam_punishment_callback(callback: CallbackQuery):
    """Открыть выбор наказания"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    current_punishment = settings.get('reaction_spam_punishment', 'kick')
    
    builder = InlineKeyboardBuilder()
    
    kick_check = "✅ " if current_punishment == 'kick' else ""
    ban_check = "✅ " if current_punishment == 'ban' else ""
    
    builder.button(text=f"{kick_check}Кик", callback_data="utilities_reaction_punishment_kick")
    builder.button(text=f"{ban_check}Бан", callback_data="utilities_reaction_punishment_ban")
    builder.button(text="🔙 Назад", callback_data="utilities_reaction_spam")
    
    builder.adjust(2, 1)
    
    text = (
        "⚡ <b>Наказание</b>\n\n"
        f"Текущее наказание: <b>{'Кик' if current_punishment == 'kick' else 'Бан'}</b>\n\n"
        "Выберите тип наказания за спам реакциями:"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_reaction_spam_punishment_set_callback(callback: CallbackQuery):
    """Установить тип наказания"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    punishment = callback.data.split("_")[-1]
    
    await utilities_db.update_setting(chat_id, 'reaction_spam_punishment', punishment)
    await utilities_reaction_spam_callback(callback)
    
    punishment_text = "Кик" if punishment == 'kick' else "Бан"
    await callback.answer(f"✅ Наказание установлено: {punishment_text}")


async def utilities_reaction_spam_ban_duration_callback(callback: CallbackQuery):
    """Открыть выбор времени бана"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    current_duration = settings.get('reaction_spam_ban_duration', 300)
    
    builder = InlineKeyboardBuilder()
    
    durations = [
        (300, "5 мин"),
        (1800, "30 мин"),
        (3600, "1 час"),
        (7200, "2 часа"),
        (14400, "4 часа"),
        (86400, "1 день")
    ]
    
    for duration_sec, duration_text in durations:
        check = "✅ " if duration_sec == current_duration else ""
        builder.button(text=f"{check}{duration_text}", callback_data=f"utilities_reaction_ban_duration_{duration_sec}")
    
    builder.button(text="🔙 Назад", callback_data="utilities_reaction_spam")
    builder.adjust(2, 2, 1, 1)
    
    current_duration_text = format_mute_duration(current_duration)
    
    text = (
        "⏱ <b>Время бана</b>\n\n"
        f"Текущее время: <b>{current_duration_text}</b>\n\n"
        "Выберите длительность бана:"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_reaction_spam_silent_callback(callback: CallbackQuery):
    """Переключить наказание без уведомлений для реакций"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    current_silent = settings.get('reaction_spam_silent', False)
    new_silent = not current_silent
    
    await utilities_db.update_setting(chat_id, 'reaction_spam_silent', new_silent)
    await utilities_reaction_spam_callback(callback)


async def utilities_reaction_spam_ban_duration_set_callback(callback: CallbackQuery):
    """Установить время бана"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    duration = int(callback.data.split("_")[-1])
    
    await utilities_db.update_setting(chat_id, 'reaction_spam_ban_duration', duration)
    await utilities_reaction_spam_callback(callback)
    
    duration_text = format_mute_duration(duration)
    await callback.answer(f"✅ Время бана установлено: {duration_text}")


async def utilities_fake_commands_callback(callback: CallbackQuery):
    """Открыть настройки защиты от ложных команд"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    enabled = settings.get('fake_commands_enabled', False)
    
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text=f"{'✅' if enabled else '❌'} {'Выключить' if enabled else 'Включить'}",
        callback_data="utilities_fake_commands_toggle"
    )
    builder.button(text="🔙 Назад", callback_data="utilities_back")
    
    builder.adjust(1, 1)
    
    text = (
        "🔧 <b>Ложные команды</b>\n\n"
        f"<b>Статус:</b> {'✅ Включено' if enabled else '❌ Выключено'}\n\n"
        "Бот автоматически удаляет повторные использования команд в течение 60 секунд после первого обнаружения.\n\n"
        "<i>На работу других ботов это не влияет.</i>"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_fake_commands_toggle_callback(callback: CallbackQuery):
    """Переключить защиту от ложных команд"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    current_enabled = settings.get('fake_commands_enabled', False)
    new_enabled = not current_enabled
    
    await utilities_db.update_setting(chat_id, 'fake_commands_enabled', new_enabled)
    
    try:
        await utilities_fake_commands_callback(callback)
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка в utilities_fake_commands_toggle_callback: {e}")
        await callback.answer()


async def utilities_auto_ban_channels_callback(callback: CallbackQuery):
    """Открыть настройки автоматического бана каналов"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    enabled = settings.get('auto_ban_channels_enabled', False)
    duration = settings.get('auto_ban_channels_duration', None)
    
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text=f"{'✅' if enabled else '❌'} {'Выключить' if enabled else 'Включить'}",
        callback_data="utilities_auto_ban_channels_toggle"
    )
    builder.button(text="🔙 Назад", callback_data="utilities_back")
    
    builder.adjust(1, 1)
    
    text = (
        "🔧 <b>Автобан каналов Telegram</b>\n\n"
        f"<b>Статус:</b> {'✅ Включено' if enabled else '❌ Выключено'}\n\n"
        "Бот автоматически банит каналы, которые отправляют сообщения от имени канала в чат, и удаляет их сообщения.\n\n"
        "<i>Пересылка сообщений от каналов не запрещена. Баны применяются только к сообщениям, отправленным от имени канала.</i>\n"
        "<i>Временный бан для каналов не поддерживается - все каналы банятся навсегда.</i>\n"
        "<i>Ручные баны каналов модераторами сохраняются отдельно.</i>"
    )
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
    await callback.answer()


async def utilities_auto_ban_channels_toggle_callback(callback: CallbackQuery):
    """Переключить автоматический бан каналов"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    settings = await utilities_db.get_settings(chat_id)
    
    current_enabled = settings.get('auto_ban_channels_enabled', False)
    new_enabled = not current_enabled
    
    await utilities_db.update_setting(chat_id, 'auto_ban_channels_enabled', new_enabled)
    
    try:
        await utilities_auto_ban_channels_callback(callback)
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка в utilities_auto_ban_channels_toggle_callback: {e}")
        await callback.answer()


@require_bot_admin_rights
async def resetconfig_command(message: Message, **kwargs):
    """Обработчик команды /resetconfig - сброс всех настроек к значениям по умолчанию"""
    chat = message.chat
    user = message.from_user
    
    if chat.type in ['group', 'supergroup']:
        chat_info = await db.get_chat(chat.id)
        if chat_info and (not chat_info.get('is_active', True) or chat_info.get('frozen_at')):
            await message.answer("❌ Бот был удален из этого чата")
            return
    
    effective_rank = await get_effective_rank(chat.id, user.id)
    
    if effective_rank > RANK_ADMIN:
        await message.answer("❌ Только администратор или владелец чата может сбросить настройки!")
        return
    
    text = (
        "⚠️ <b>Сброс всех настроек</b>\n"
        "Вы уверены, что хотите сбросить <b>все настройки</b> чата к значениям по умолчанию?\n"
        "<i>Это действие нельзя отменить!</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Да, сбросить все",
        callback_data="resetconfig_confirm"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="resetconfig_cancel"
    ))
    builder.adjust(1)
    
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


async def resetconfig_confirm_callback(callback: CallbackQuery):
    """Обработчик подтверждения сброса настроек"""
    if not await _ensure_admin(callback):
        return
    
    chat_id = callback.message.chat.id
    
    try:
        # Показываем процесс сброса
        await callback.message.edit_text(
            "⏳ <b>Сброс настроек...</b>\n\n"
            "Пожалуйста, подождите...",
            parse_mode=ParseMode.HTML
        )
        
        await moderation_db.update_warn_settings(
            chat_id,
            warn_limit=3,
            punishment_type='kick',
            mute_duration=None
        )
        
        await db.set_chat_stats_enabled(chat_id, True)
        
        for rank in [1, 2, 3, 4]:
            await db.reset_rank_permissions_to_default(chat_id, rank)
        
        await db.set_russian_commands_prefix_setting(chat_id, False)
        
        await db.set_auto_accept_join_requests(chat_id, False)
        await db.set_auto_accept_notify(chat_id, False)
        
        await raid_protection_db.update_settings(
            chat_id,
            enabled=True,
            gif_limit=RAID_PROTECTION['gif_limit'],
            gif_time_window=RAID_PROTECTION['gif_time_window'],
            sticker_limit=RAID_PROTECTION['sticker_limit'],
            sticker_time_window=RAID_PROTECTION['sticker_time_window'],
            duplicate_text_limit=RAID_PROTECTION['duplicate_text_limit'],
            duplicate_text_window=RAID_PROTECTION['duplicate_text_window'],
            mass_join_limit=RAID_PROTECTION['mass_join_limit'],
            mass_join_window=RAID_PROTECTION['mass_join_window'],
            similarity_threshold=RAID_PROTECTION['similarity_threshold'],
            notification_mode=1,
            auto_mute_duration=0
        )
        
        await utilities_db.update_settings(
            chat_id,
            emoji_spam_enabled=False,
            emoji_spam_limit=10,
            reaction_spam_enabled=False,
            reaction_spam_limit=5,
            reaction_spam_window=120,
            reaction_spam_warning_enabled=True,
            reaction_spam_punishment='kick',
            reaction_spam_ban_duration=300,
            fake_commands_enabled=False
        )
        
        set_gifs_enabled(chat_id, False)
        
        await set_top_chat_settings_async(chat_id, TOP_CHATS_DEFAULTS.copy())
        
        text = (
            "✅ <b>Все настройки сброшены!</b>\n\n"
            "Все настройки чата были успешно сброшены к значениям по умолчанию.\n\n"
            "<b>Сброшены:</b>\n"
            "• Варны, статистика, права рангов\n"
            "• Русский префикс, автодопуск\n"
            "• Анти-спам, утилиты, гифки\n"
            "• Топ чатов\n\n"
            "Используйте <code>/settings</code> для настройки чата заново."
        )
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="⚙️ Открыть настройки",
            callback_data="settings_main"
        ))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer("✅ Настройки сброшены!")
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе настроек для чата {chat_id}: {e}")
        await callback.message.edit_text(
            f"❌ <b>Ошибка при сбросе настроек</b>\n\n"
            f"Произошла ошибка: {str(e)}\n\n"
            f"Попробуйте еще раз.",
            parse_mode=ParseMode.HTML
        )
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def resetconfig_cancel_callback(callback: CallbackQuery):
    """Обработчик отмены сброса настроек"""
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    effective_rank = await get_effective_rank(chat_id, user_id)
    
    settings_text, markup = await build_settings_menu(chat_id, effective_rank)
    await callback.message.edit_text(settings_text, reply_markup=markup, parse_mode=ParseMode.HTML)
    await callback.answer("Сброс отменен")
