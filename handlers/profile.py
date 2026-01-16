"""
Обработчики команд профилей и статистики
"""
import logging
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from databases.database import db
from databases.reputation_db import reputation_db
from databases.moderation_db import moderation_db
from utils.permissions import get_effective_rank
from utils.formatting import (
    get_user_mention_html, get_reputation_emoji, 
    get_reputation_progress_bar, format_mute_duration
)
from utils.constants import RANK_NAMES
from utils.image_generator import generate_modern_profile_card
from handlers.common import require_admin_rights, parse_user_from_args, safe_answer_callback

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def get_rank_name(rank: int, count: int = 1) -> str:
    """Получить название ранга с учетом множественного числа"""
    return RANK_NAMES[rank][0] if count == 1 else RANK_NAMES[rank][1]


def register_profile_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков команд профилей"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # Команды
    dp.message.register(info_command, Command("info"))
    dp.message.register(myprofile_command, Command("myprofile"))
    dp.message.register(reputation_command, Command("reputation", "rep"))
    dp.message.register(mentionping_command, Command("mentionping"))
    dp.message.register(unmentionping_command, Command("unmentionping"))
    
    # Callbacks - профиль
    dp.callback_query.register(my_profile_private_callback, F.data == "my_profile_private")


@require_admin_rights
async def info_command(message: Message):
    """Обработчик команды /info"""
    chat = message.chat
    
    chat_info = await db.get_chat(chat.id)
    
    if not chat_info:
        owner_id = None
        try:
            admins = await bot.get_chat_administrators(chat.id)
            for admin in admins:
                if admin.status == 'creator':
                    owner_id = admin.user.id
                    break
        except Exception:
            pass
        
        await db.add_chat(
            chat_id=chat.id,
            chat_title=chat.title or "Без названия",
            owner_id=owner_id
        )
        
        chat_info = await db.get_chat(chat.id)
    
    try:
        member_count = await bot.get_chat_member_count(chat.id)
    except Exception:
        member_count = "Неизвестно"
    
    today_count = await db.get_today_message_count(chat.id)
    weekly_stats = await db.get_daily_stats(chat.id, 7)
    
    weekly_text = ""
    total_weekly = 0
    if weekly_stats:
        for stat in weekly_stats:
            date_obj = datetime.strptime(stat['date'], '%Y-%m-%d')
            formatted_date = date_obj.strftime('%d.%m')
            weekly_text += f"• {formatted_date}: {stat['message_count']} сообщений\n"
            total_weekly += stat['message_count']
    
    owner_mention = "Неизвестно"
    try:
        owner_member = await bot.get_chat_member(chat.id, chat_info['owner_id'])
        if owner_member.user.username:
            owner_mention = f"@{owner_member.user.username}"
        elif owner_member.user.first_name:
            owner_mention = f'<a href="tg://user?id={owner_member.user.id}">{owner_member.user.first_name}</a>'
    except Exception:
        pass

    stats_text = f"""
📊 <b>Статистика чата</b>

<b>Основная информация:</b>
• Название: {chat_info['chat_title']}
• ID чата: <code>{chat_info['chat_id']}</code>
• Участников: {member_count}
• Добавлен: {chat_info['added_date'][:10]}
• Владелец: {owner_mention}

<b>Статистика сообщений:</b>
• Сегодня: {today_count} сообщений
• За неделю: {total_weekly} сообщений

<b>По дням:</b>
{weekly_text if weekly_text else '• Данных пока нет'}

<i>Обновляется в реальном времени</i>
    """
    
    await message.answer(stats_text, parse_mode=ParseMode.HTML)


async def send_private_profile(message: Message, user: types.User):
    """Урезанный профиль для личных сообщений"""
    try:
        global_activity = await db.get_user_global_activity(user.id)
        reputation = await reputation_db.get_user_reputation(user.id)
        reputation_emoji = get_reputation_emoji(reputation)
        
        user_name = get_user_mention_html(user)
        
        profile_lines = [
            f"👤 <b>Профиль: {user_name}</b>",
            "",
            f"<b>Репутация:</b> {reputation}/100 {reputation_emoji}",
            "",
            "<b>Глобальная статистика:</b>"
        ]
        
        if global_activity and (global_activity.get('today', 0) > 0 or global_activity.get('week', 0) > 0):
            today_count = global_activity.get('today', 0)
            week_count = global_activity.get('week', 0)
            
            profile_lines.extend([
                f"Сегодня: {today_count} сообщений",
                f"За неделю: {week_count} сообщений"
            ])
        else:
            profile_lines.append("Начните общение в чатах для статистики")
        
        profile_lines.extend([
            "",
            "<i>Полный профиль с графиком доступен в чатах</i>"
        ])
        
        await message.answer("\n".join(profile_lines), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при создании урезанного профиля: {e}")
        await message.answer("❌ Ошибка при создании профиля")


async def my_profile_private_callback(callback: CallbackQuery):
    """Обработчик кнопки 'Мой профиль' в личных сообщениях"""
    try:
        user = callback.from_user
        
        # Проверяем, что это личное сообщение
        if callback.message.chat.type != 'private':
            await safe_answer_callback(callback, "❌ Эта функция доступна только в личных сообщениях")
            return
        
        global_activity = await db.get_user_global_activity(user.id)
        reputation = await reputation_db.get_user_reputation(user.id)
        reputation_emoji = get_reputation_emoji(reputation)
        
        user_name = get_user_mention_html(user)
        
        profile_lines = [
            f"👤 <b>Профиль: {user_name}</b>",
            "",
            f"<b>Репутация:</b> {reputation}/100 {reputation_emoji}",
            "",
            "<b>Глобальная статистика:</b>"
        ]
        
        if global_activity and (global_activity.get('today', 0) > 0 or global_activity.get('week', 0) > 0):
            today_count = global_activity.get('today', 0)
            week_count = global_activity.get('week', 0)
            
            profile_lines.extend([
                f"Сегодня: {today_count} сообщений",
                f"За неделю: {week_count} сообщений"
            ])
        else:
            profile_lines.append("Начните общение в чатах для статистики")
        
        profile_lines.extend([
            "",
            "<i>Полный профиль с графиком доступен в чатах</i>"
        ])
        
        text = "\n".join(profile_lines)
        
        # Добавляем кнопку "Назад"
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="back_to_menu"
        ))
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode=ParseMode.HTML
            )
        except Exception as edit_error:
            # Игнорируем ошибку "message is not modified"
            error_str = str(edit_error).lower()
            if "message is not modified" not in error_str:
                raise
        
        await safe_answer_callback(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в my_profile_private_callback: {e}")
        await safe_answer_callback(callback, "❌ Ошибка при загрузке профиля", show_alert=True)


@require_admin_rights
async def myprofile_command(message: Message):
    """Профиль пользователя: полный в чатах, урезанный в ЛС"""
    chat_id = message.chat.id
    user = message.from_user
    target_user = user
    
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif message.text and len(message.text.split()) > 1:
        args = message.text.split()
        target_user = await parse_user_from_args(message, args, 1)
        
        if not target_user:
            await message.answer("❌ Пользователь не найден в этом чате")
            return

    if message.chat.type == 'private':
        await send_private_profile(message, user)
        return

    stat_settings = await db.get_chat_stat_settings(chat_id)
    if not stat_settings.get('profile_enabled', True):
        await message.answer("📊 Команда профиля отключена для этого чата")
        return
    
    # Проверяем, является ли пользователь ботом
    if target_user.is_bot:
        # Показываем упрощенную информацию о боте
        bot_info_lines = []
        
        # Получаем mention бота
        user_name = get_user_mention_html(target_user)
        bot_info_lines.append(f"🤖 Это бот: {user_name}")
        bot_info_lines.append("")
        
        # Основная информация из Telegram API
        bot_info_lines.append(f"🆔 ID: <code>{target_user.id}</code>")
        
        if target_user.username:
            bot_info_lines.append(f"📝 Username: @{target_user.username}")
        
        bot_info_text = "\n".join(bot_info_lines)
        await message.answer(bot_info_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return
    
    await db.ensure_user_first_seen(chat_id, target_user.id)

    first_seen = await db.get_user_first_seen(chat_id, target_user.id)
    monthly_stats = await db.get_user_30d_stats(chat_id, target_user.id)
    best_day = await db.get_user_best_day(chat_id, target_user.id)
    global_activity = await db.get_user_global_activity(target_user.id)

    today = datetime.now().strftime('%Y-%m-%d')
    today_stats = await db.get_user_daily_stats(chat_id, target_user.id, today)
    today_count = today_stats.get('message_count', 0) if today_stats else 0
    
    user_rank = await get_effective_rank(chat_id, target_user.id)
    rank_name = get_rank_name(user_rank)
    
    rank_emojis = {
        1: "👑", 2: "⚜️", 3: "🛡", 4: "🔰", 5: "👤"
    }
    rank_emoji = rank_emojis.get(user_rank, "👤")

    try:
        chart_buf = generate_modern_profile_card({}, monthly_stats, None)
        
        user_name = get_user_mention_html(target_user)
        
        caption_lines = []
        caption_lines.append(f"👤 <b>{user_name}</b> ({rank_emoji} {rank_name})")
        caption_lines.append("")
        
        if first_seen:
            try:
                fs = datetime.strptime(first_seen, '%Y-%m-%d').strftime('%d.%m.%Y')
            except Exception:
                fs = first_seen
            caption_lines.append(f"В чате с: {fs}")
        
        caption_lines.append(f"Сегодня: {today_count} сообщений")
        
        if best_day:
            try:
                bd = datetime.strptime(best_day['date'], '%Y-%m-%d').strftime('%d.%m')
            except Exception:
                bd = best_day['date']
            caption_lines.append(f"Лучший день: {bd} ({best_day['message_count']})")
        
        caption_lines.append("")
        caption_lines.append(f"Глобально: {global_activity['today']} сегодня, {global_activity['week']} за неделю")
        
        reputation = await reputation_db.get_user_reputation(target_user.id)
        reputation_emoji = get_reputation_emoji(reputation)
        caption_lines.append(f"Репутация: {reputation}/100 {reputation_emoji}")
        
        # Добавляем информацию о варнах, если они есть
        warn_count = await moderation_db.get_user_warn_count(chat_id, target_user.id)
        if warn_count > 0:
            caption_lines.append(f"⚠️ Варны: {warn_count}")

        caption = "\n".join(caption_lines)

        await message.answer_photo(
            types.input_file.BufferedInputFile(chart_buf.read(), filename="profile.png"),
            caption=caption, 
            parse_mode=ParseMode.HTML, 
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Ошибка при генерации графика профиля: {e}")
        await message.answer("❌ Ошибка при создании графика профиля")


async def reputation_command(message: Message):
    """Команда просмотра репутации пользователя"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    target_user = None
    
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    else:
        args = message.text.split()
        if len(args) == 2:
            target_user = await parse_user_from_args(message, args, 1)
            if not target_user:
                await message.answer(
                    "❌ <b>Пользователь не найден</b>\n\n"
                    "Использование:\n"
                    "• <code>/reputation</code> - показать свою репутацию\n"
                    "• <code>/reputation @username</code> или упоминание",
                    parse_mode=ParseMode.HTML
                )
                return
        elif len(args) == 1:
            target_user = message.from_user
        else:
            await message.answer(
                "❌ <b>Некорректный формат команды</b>\n\n"
                "Использование:\n"
                "• <code>/reputation</code> - показать свою репутацию\n"
                "• <code>/reputation @username</code>",
                parse_mode=ParseMode.HTML
            )
            return
    
    if not target_user:
        await message.answer("❌ Пользователь не найден")
        return
    
    try:
        reputation = await reputation_db.get_user_reputation(target_user.id)
        reputation_emoji = get_reputation_emoji(reputation)
        progress_bar = get_reputation_progress_bar(reputation)
        
        stats = await reputation_db.get_recent_punishment_stats(target_user.id, days=7)
        recent_punishments = await reputation_db.get_recent_punishments(target_user.id, days=7)
        
        username_display = get_user_mention_html(target_user)
        
        message_text = f"🎯 <b>Репутация:</b> {reputation}/100\n"
        message_text += f"[{progress_bar}] {reputation_emoji}\n\n"
        
        message_text += f"👤 <b>Пользователь:</b> {username_display}\n\n"
        
        # Добавляем информацию об активных варнах
        active_warn_count = await moderation_db.get_user_warn_count(chat_id, target_user.id)
        if active_warn_count > 0:
            message_text += f"⚠️ <b>Активные варны:</b> {active_warn_count}\n\n"
        
        message_text += "📋 <b>Наказания (последние 7 дней):</b>\n"
        message_text += f"⚠️ Варны: {stats['warn']}\n"
        message_text += f"🔇 Муты: {stats['mute']}\n"
        message_text += f"💨 Кики: {stats['kick']}\n"
        message_text += f"🚫 Баны: {stats['ban']}\n\n"
        
        if recent_punishments:
            message_text += "📜 <b>История наказаний:</b>\n"
            for punishment in recent_punishments[:5]:
                try:
                    date_obj = datetime.fromisoformat(punishment['punishment_date'])
                    date_str = date_obj.strftime('%d.%m %H:%M')
                except:
                    date_str = punishment['punishment_date']
                
                punishment_type = punishment['punishment_type']
                duration = punishment['duration_seconds']
                
                duration_text = ""
                if duration:
                    duration_text = f" ({format_mute_duration(duration)})"
                
                message_text += f"• {date_str} - {punishment_type}{duration_text}\n"
        else:
            message_text += "📜 <b>История наказаний:</b> Нет нарушений за последние 3 дня ✅"
        
        await message.answer(message_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка при получении репутации пользователя {target_user.id}: {e}")
        await message.answer("❌ Ошибка при получении информации о репутации")


async def mentionping_command(message: Message):
    """Включить кликабельные упоминания"""
    user_id = message.from_user.id
    
    try:
        success = await db.set_user_mention_ping_enabled(user_id, True)
        if success:
            await message.answer(
                "✅ <b>Кликабельные упоминания включены</b>\n\n"
                "Теперь ваше имя в статистике будет кликабельным (ping) во всех чатах.",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer("❌ Ошибка при изменении настройки")
    except Exception as e:
        logger.error(f"Ошибка при включении упоминаний: {e}")
        await message.answer("❌ Ошибка при изменении настройки")


async def unmentionping_command(message: Message):
    """Выключить кликабельные упоминания"""
    user_id = message.from_user.id
    
    try:
        success = await db.set_user_mention_ping_enabled(user_id, False)
        if success:
            await message.answer(
                "✅ <b>Кликабельные упоминания выключены</b>\n\n"
                "Теперь ваше имя в статистике не будет кликабельным (без ping).",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer("❌ Ошибка при изменении настройки")
    except Exception as e:
        logger.error(f"Ошибка при выключении упоминаний: {e}")
        await message.answer("❌ Ошибка при изменении настройки")
