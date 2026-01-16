"""
Обработчики команд сетки чатов
"""
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, ChatPermissions
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode

from databases.database import db
from databases.network_db import network_db
from databases.moderation_db import moderation_db
from databases.utilities_db import utilities_db
from databases.raid_protection_db import raid_protection_db
from utils.permissions import get_effective_rank
from utils.constants import RANK_OWNER
from utils.gifs import get_gifs_enabled, set_gifs_enabled
from handlers.common import safe_answer_callback
from handlers.top_chats import get_top_chat_settings_async, set_top_chat_settings_async

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def register_network_handlers(dispatcher: Dispatcher, bot_instance: Bot):
    """Регистрация обработчиков сетки чатов"""
    global bot, dp
    bot = bot_instance
    dp = dispatcher
    
    # Команды
    dp.message.register(net_command, Command("net"))
    dp.message.register(netconnect_command, Command("netconnect"))
    dp.message.register(netadd_command, Command("netadd"))
    
    # Callbacks
    dp.callback_query.register(net_create_callback, F.data == "net_create")
    dp.callback_query.register(net_list_callback, F.data == "net_list")
    dp.callback_query.register(back_to_menu_callback, F.data == "back_to_menu")
    dp.callback_query.register(net_add_chat_callback, F.data == "net_add_chat")
    dp.callback_query.register(net_view_callback, F.data.startswith("net_view_"))
    dp.callback_query.register(net_code_gen_callback, F.data.startswith("net_code_gen_"))
    dp.callback_query.register(net_sync_callback, F.data.startswith("net_sync_"))
    dp.callback_query.register(sync_source_callback, F.data.startswith("sync_source_"))
    dp.callback_query.register(sync_all_callback, F.data.startswith("sync_all_"))
    dp.callback_query.register(net_stats_callback, F.data.startswith("net_stats_"))
    # Регистрируем более специфичные обработчики первыми (порядок важен!)
    dp.callback_query.register(net_moderation_toggle_media_callback, F.data.startswith("net_moderation_toggle_media_"))
    dp.callback_query.register(net_moderation_close_chat_callback, F.data.startswith("net_moderation_close_"))
    dp.callback_query.register(net_moderation_chat_callback, F.data.startswith("net_moderation_chat_"))
    dp.callback_query.register(net_moderation_callback, F.data.startswith("net_moderation_"))
    dp.callback_query.register(net_delete_network_callback, F.data.startswith("net_delete_network_") & ~F.data.startswith("net_delete_network_confirm_"))
    dp.callback_query.register(net_delete_network_confirm_callback, F.data.startswith("net_delete_network_confirm_"))
    dp.callback_query.register(remove_chat_callback, F.data.startswith("remove_chat_") & ~F.data.startswith("remove_chat_confirm_"))
    dp.callback_query.register(remove_chat_confirm_callback, F.data.startswith("remove_chat_confirm_"))


async def net_command(message: Message):
    """Команда управления сеткой чатов"""
    if message.chat.type != 'private':
        await message.answer("❌ Команда /net доступна только в личных сообщениях с ботом!")
        return
    
    try:
        user_id = message.from_user.id
        
        networks = await network_db.get_user_networks(user_id)
        
        text = """🌐 <b>Сетка чатов PIXEL</b>

<blockquote>Сетка чатов позволяет связать до <b>5 чатов</b> для:
• Просмотра общей статистики
• Синхронизации настроек модерации
• Централизованного управления
</blockquote>

<blockquote><code>Важно: Вы должны быть владельцем всех чатов!</code></blockquote>

<blockquote><code>/chatnet update</code> - обновить информацию</blockquote>"""
        
        builder = InlineKeyboardBuilder()
        
        if not networks:
            builder.add(InlineKeyboardButton(
                text="🔗 Связать чаты",
                callback_data="net_create"
            ))
        
        if networks:
            builder.add(InlineKeyboardButton(
                text=f"📋 Моя сетка",
                callback_data="net_list"
            ))
        
        builder.adjust(1)
        
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в команде /net: {e}")
        await message.answer("❌ Произошла ошибка при отображении панели сетки чатов")


async def netconnect_command(message: Message):
    """Команда подключения к сетке чатов"""
    if message.chat.type == 'private':
        await message.answer("❌ Команда /netconnect должна использоваться в чате, который нужно добавить в сетку!")
        return
    
    try:
        command_parts = message.text.split()
        if len(command_parts) != 2:
            await message.answer("❌ Использование: /netconnect <код>\nПример: /netconnect 1234")
            return
        
        code = command_parts[1].strip()
        if not code.isdigit() or len(code) != 4:
            await message.answer("❌ Код должен быть 4-значным числом!\nПример: /netconnect 1234")
            return
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        user_rank = await get_effective_rank(chat_id, user_id)
        if user_rank != RANK_OWNER:
            await message.answer("❌ Только владелец чата может добавлять его в сетку!")
            return
        
        if await network_db.is_chat_in_network(chat_id):
            await message.answer("❌ Этот чат уже находится в сетке чатов!")
            return
        
        code_info = await network_db.validate_code(code)
        if not code_info:
            await message.answer("❌ Неверный или истекший код!")
            return
        
        network_id = code_info['network_id']
        code_type = code_info['code_type']
        
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await message.answer("❌ Вы не можете использовать этот код! Только владелец сети может добавлять чаты.")
            return
        
        chat_count = await network_db.get_network_chat_count(network_id)
        if chat_count >= 5:
            await message.answer("❌ В сетке уже максимальное количество чатов (5)!")
            return
        
        network_chats = await network_db.get_network_chats(network_id)
        is_primary = (code_type == 'create' and len(network_chats) == 0)
        success = await network_db.add_chat_to_network(network_id, chat_id, is_primary)
        if not success:
            await message.answer("❌ Ошибка при добавлении чата в сетку!")
            return
        
        network_chats = await network_db.get_network_chats(network_id)
        
        if code_type == 'create' and len(network_chats) == 1:
            await message.answer(f"""✅ <b>Чат добавлен в новую сетку!</b>

🌐 Сетка создана успешно
Чатов: 1/5

Теперь добавьте второй чат, используя тот же код в другом чате:
<code>/netconnect {code}</code>

Код действует 10 минут.""", parse_mode=ParseMode.HTML)
        elif code_type == 'create' and len(network_chats) == 2:
            await network_db.mark_code_as_used(code)
            await message.answer(f"""✅ <b>Сетка создана!</b>

🌐 Сетка #{network_id} готова к использованию
Чатов: {len(network_chats)}/5

Используйте /net для управления сеткой.""", parse_mode=ParseMode.HTML)
        else:
            await message.answer(f"""✅ <b>Чат добавлен в сетку!</b>

🌐 Сетка обновлена
Чатов: {len(network_chats)}/5

Сетка готова к использованию!""", parse_mode=ParseMode.HTML)
        
        try:
            await bot.send_message(
                user_id,
                f"""🌐 <b>Обновление сетки чатов</b>

Чат "{message.chat.title}" добавлен в сетку #{network_id}

Всего чатов: {len(network_chats)}/5

Используйте /net для управления сеткой.""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления владельцу: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка в команде /netconnect: {e}")
        await message.answer("❌ Произошла ошибка при подключении к сетке!")


async def netadd_command(message: Message):
    """Команда добавления чата в существующую сетку"""
    if message.chat.type == 'private':
        await message.answer("❌ Команда /netadd должна использоваться в чате, который нужно добавить в сетку!")
        return
    
    try:
        command_parts = message.text.split()
        if len(command_parts) != 2:
            await message.answer("❌ Использование: /netadd <код>\nПример: /netadd 42")
            return
        
        code = command_parts[1].strip()
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        
        user_rank = await get_effective_rank(chat_id, user_id)
        if user_rank != RANK_OWNER:
            await message.answer("❌ Только владелец чата может добавлять его в сетку!")
            return
        
        code_info = await network_db.validate_code(code)
        if not code_info:
            await message.answer("❌ Неверный или истекший код!")
            return
        
        network_id = code_info['network_id']
        
        success = await network_db.add_chat_to_network(network_id, chat_id, False)
        if success:
            await message.answer(f"✅ Чат добавлен в сетку #{network_id}!", parse_mode=ParseMode.HTML)
        else:
            await message.answer("❌ Ошибка при добавлении чата в сетку!")
        
    except Exception as e:
        logger.error(f"Ошибка в команде /netadd: {e}")
        await message.answer("❌ Произошла ошибка!")


async def net_create_callback(callback: CallbackQuery):
    """Создание новой сетки"""
    try:
        user_id = callback.from_user.id
        
        # Создаем сетку и код
        network_id = await network_db.create_network(user_id)
        code = await network_db.generate_code(network_id, 'create')
        
        text = f"""✅ <b>Сетка создана!</b>

🆔 ID сетки: <code>#{network_id}</code>

<b>Для добавления чатов:</b>

1️⃣ Перейдите в первый чат
2️⃣ Используйте команду:
<code>/netconnect {code}</code>

3️⃣ Перейдите во второй чат
4️⃣ Используйте ту же команду:
<code>/netconnect {code}</code>

⏰ Код действует 10 минут"""
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="net_list"))
        
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_create_callback: {e}")
        await callback.answer("❌ Ошибка при создании сетки!", show_alert=True)


async def net_list_callback(callback: CallbackQuery):
    """Список чатов в сетке"""
    try:
        user_id = callback.from_user.id
        
        networks = await network_db.get_user_networks(user_id)
        
        if not networks:
            await callback.message.edit_text(
                "📭 У вас пока нет сеток чатов.\n\n"
                "Используйте кнопку ниже чтобы создать новую сетку.",
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(text="🔗 Создать сетку", callback_data="net_create")
                ).as_markup()
            )
            await callback.answer()
            return
        
        # Показываем список всех сеток
        text = "🌐 <b>Мои сетки чатов</b>\n\n"
        text += f"Всего сеток: {len(networks)}\n\n"
        text += "Выберите сетку для управления:\n\n"
        
        builder = InlineKeyboardBuilder()
        
        for i, network in enumerate(networks, 1):
            network_id = network['network_id']
            chats = await network_db.get_network_chats(network_id)
            text += f"{i}. Сетка #{network_id} ({len(chats)}/5 чатов)\n"
            
            builder.add(InlineKeyboardButton(
                text=f"🌐 Сетка #{network_id} ({len(chats)}/5)",
                callback_data=f"net_view_{network_id}"
            ))
        
        builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
        builder.adjust(1)
        
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=builder.as_markup())
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_list_callback: {e}")
        await callback.answer("❌ Ошибка!", show_alert=True)


async def remove_chat_callback(callback: CallbackQuery):
    """Обработчик удаления чата из сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        network_chats = await network_db.get_network_chats(network_id)
        
        if len(network_chats) <= 1:
            await callback.answer("❌ Нельзя удалить последний чат из сетки!")
            return
        
        text = f"🗑️ <b>Удаление чата из сетки #{network_id}</b>\n\n"
        text += "Выберите чат для удаления:\n\n"
        
        builder = InlineKeyboardBuilder()
        
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            
            if chat_info:
                chat_accessible = True
                try:
                    await bot.get_chat(chat_id)
                except Exception:
                    chat_accessible = False
                
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                status_mark = " ❌" if not chat_accessible else ""
                
                text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}{status_mark}\n"
                
                builder.add(InlineKeyboardButton(
                    text=f"{i}. {chat_info['chat_title']}{primary_mark}{status_mark}",
                    callback_data=f"remove_chat_confirm_{network_id}_{chat_id}"
                ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="net_list"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Ошибка в remove_chat_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


async def remove_chat_confirm_callback(callback: CallbackQuery):
    """Обработчик подтверждения удаления чата из сетки"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[3])
        chat_id = int(parts[4])
        user_id = callback.from_user.id
        
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!")
            return
        
        chat_info = await db.get_chat(chat_id)
        chat_title = chat_info['chat_title'] if chat_info else f"Чат {chat_id}"
        
        await network_db.remove_chat_from_network(chat_id)
        
        remaining_chats = await network_db.get_network_chats(network_id)
        
        if len(remaining_chats) == 0:
            await network_db.delete_network(network_id)
            await callback.message.edit_text(
                f"✅ <b>Чат удален из сетки!</b>\n\n"
                f"🗑️ Удален: <b>{chat_title}</b>\n"
                f"🌐 Сетка #{network_id} была удалена (не осталось чатов)\n\n"
                f"Используйте /net для создания новой сетки.",
                parse_mode=ParseMode.HTML
            )
        else:
            await callback.message.edit_text(
                f"✅ <b>Чат удален из сетки!</b>\n\n"
                f"🗑️ Удален: <b>{chat_title}</b>\n"
                f"🌐 Сетка #{network_id} обновлена\n"
                f"Осталось чатов: {len(remaining_chats)}/5\n\n"
                f"Используйте /net для управления сеткой.",
                parse_mode=ParseMode.HTML
            )
        
    except Exception as e:
        logger.error(f"Ошибка в remove_chat_confirm_callback: {e}")
        await callback.answer("❌ Произошла ошибка!")
    
    await callback.answer()


async def back_to_menu_callback(callback: CallbackQuery):
    """Возврат в главное меню /net"""
    try:
        user_id = callback.from_user.id
        
        networks = await network_db.get_user_networks(user_id)
        
        text = """🌐 <b>Сетка чатов PIXEL</b>

<blockquote>Сетка чатов позволяет связать до <b>5 чатов</b> для:
• Просмотра общей статистики
• Синхронизации настроек модерации
• Централизованного управления
</blockquote>

<blockquote><code>Важно: Вы должны быть владельцем всех чатов!</code></blockquote>

<blockquote><code>/chatnet update</code> - обновить информацию</blockquote>"""
        
        builder = InlineKeyboardBuilder()
        
        if not networks:
            builder.add(InlineKeyboardButton(
                text="🔗 Связать чаты",
                callback_data="net_create"
            ))
        
        if networks:
            builder.add(InlineKeyboardButton(
                text=f"📋 Моя сетка",
                callback_data="net_list"
            ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в back_to_menu_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_add_chat_callback(callback: CallbackQuery):
    """Обработчик добавления чата в сетку"""
    try:
        user_id = callback.from_user.id
        
        networks = await network_db.get_user_networks(user_id)
        
        if not networks:
            await callback.answer("❌ У вас нет сеток! Создайте сетку сначала.", show_alert=True)
            return
        
        # Если у пользователя несколько сеток, показываем список для выбора
        if len(networks) > 1:
            text = "➕ <b>Добавление чата в сетку</b>\n\n"
            text += "Выберите сетку, в которую хотите добавить чат:\n\n"
            
            builder = InlineKeyboardBuilder()
            
            for network in networks:
                network_id = network['network_id']
                chats = await network_db.get_network_chats(network_id)
                if len(chats) < 5:
                    builder.add(InlineKeyboardButton(
                        text=f"🌐 Сетка #{network_id} ({len(chats)}/5)",
                        callback_data=f"net_code_gen_{network_id}"
                    ))
            
            builder.add(InlineKeyboardButton(
                text="🔙 Назад",
                callback_data="net_list"
            ))
            builder.adjust(1)
            
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            await callback.answer()
        else:
            # Если одна сетка, сразу генерируем код
            network_id = networks[0]['network_id']
            # Создаем временный callback с правильным data
            from aiogram.types import CallbackQuery as CallbackQueryType
            temp_callback = callback
            temp_callback.data = f"net_code_gen_{network_id}"
            await net_code_gen_callback(temp_callback)
        
    except Exception as e:
        logger.error(f"Ошибка в net_add_chat_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_view_callback(callback: CallbackQuery):
    """Обработчик просмотра конкретной сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        text = f"🌐 <b>Управление сеткой #{network_id}</b>\n\n"
        text += f"📊 Чатов в сетке: {len(network_chats)}/5\n\n"
        
        # Информация о чатах
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}\n"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопки управления
        if len(network_chats) < 5:
            builder.add(InlineKeyboardButton(
                text="➕ Добавить чат",
                callback_data=f"net_code_gen_{network_id}"
            ))
        
        builder.add(InlineKeyboardButton(
            text="⚙️ Синхронизировать настройки",
            callback_data=f"net_sync_{network_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="📊 Статистика",
            callback_data=f"net_stats_{network_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🛡️ Модерация",
            callback_data=f"net_moderation_{network_id}"
        ))
        
        # Кнопка удаления чатов (только если больше одного чата)
        if len(network_chats) > 1:
            builder.add(InlineKeyboardButton(
                text="🗑️ Удалить чат из сетки",
                callback_data=f"remove_chat_{network_id}"
            ))
        
        builder.add(InlineKeyboardButton(
            text="🗑️ Удалить сетку",
            callback_data=f"net_delete_network_{network_id}"
        ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="net_list"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_view_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_code_gen_callback(callback: CallbackQuery):
    """Обработчик генерации кода для добавления чата"""
    try:
        user_id = callback.from_user.id
        
        # Парсим network_id из callback_data
        parts = callback.data.split("_")
        if len(parts) >= 4:
            network_id = int(parts[3])
        else:
            # Если network_id не указан, используем первую сетку пользователя
            networks = await network_db.get_user_networks(user_id)
            if not networks:
                await callback.answer("❌ У вас нет сеток!", show_alert=True)
                return
            network_id = networks[0]['network_id']
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Проверяем лимит чатов
        chat_count = await network_db.get_network_chat_count(network_id)
        if chat_count >= 5:
            await callback.answer("❌ В сетке уже максимальное количество чатов!", show_alert=True)
            return
        
        # Генерируем код
        code = await network_db.generate_code(network_id, 'add')
        if not code:
            await callback.answer("❌ Ошибка при генерации кода! Попробуйте позже.", show_alert=True)
            return
        
        text = f"""➕ <b>Добавление чата в сетку #{network_id}</b>

📝 <b>Инструкция:</b>
1. Скопируйте код: <code>{code}</code>
2. Перейдите в чат, который нужно добавить
3. Выполните команду: <code>/netadd {code}</code>

⏰ Код действует 10 минут и одноразовый"""
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_code_gen_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_sync_callback(callback: CallbackQuery):
    """Обработчик синхронизации настроек между чатами в сетке"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        if len(network_chats) < 2:
            await callback.answer("❌ Для синхронизации нужно минимум 2 чата в сетке!", show_alert=True)
            return
        
        text = f"⚙️ <b>Синхронизация настроек сетки #{network_id}</b>\n\n"
        text += "Выберите исходный чат (откуда копировать настройки):\n\n"
        
        builder = InlineKeyboardBuilder()
        
        for i, chat_data in enumerate(network_chats):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                builder.add(InlineKeyboardButton(
                    text=f"{i+1}. {chat_info['chat_title']}{primary_mark}",
                    callback_data=f"sync_source_{network_id}_{chat_id}"
                ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_sync_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def sync_source_callback(callback: CallbackQuery):
    """Обработчик выбора исходного чата для синхронизации"""
    try:
        # Парсим данные: sync_source_{network_id}_{source_chat_id}
        parts = callback.data.split("_")
        network_id = int(parts[2])
        source_chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        if len(network_chats) < 2:
            await callback.answer("❌ Для синхронизации нужно минимум 2 чата в сетке!", show_alert=True)
            return
        
        # Находим исходный чат
        source_chat_info = None
        for chat_data in network_chats:
            if chat_data['chat_id'] == source_chat_id:
                chat_info = await db.get_chat(chat_data['chat_id'])
                if chat_info:
                    source_chat_info = {
                        'chat_id': chat_data['chat_id'],
                        'title': chat_info['chat_title'],
                        'is_primary': chat_data['is_primary']
                    }
                break
        
        if not source_chat_info:
            await callback.answer("❌ Исходный чат не найден!", show_alert=True)
            return
        
        # Получаем целевые чаты (все кроме исходного)
        target_chats = [chat for chat in network_chats if chat['chat_id'] != source_chat_id]
        
        text = f"⚙️ <b>Синхронизация настроек</b>\n\n"
        text += f"📤 <b>Исходный чат:</b> {source_chat_info['title']}\n"
        text += f"📥 <b>Целевые чаты:</b> {len(target_chats)}\n\n"
        text += "Будут синхронизированы <b>все настройки</b>:\n"
        text += "• Настройки варнов\n"
        text += "• Настройки статистики\n"
        text += "• Права рангов\n"
        text += "• Русский префикс\n"
        text += "• Автодопуск\n"
        text += "• Настройки анти-спама\n"
        text += "• Настройки утилит\n"
        text += "• Настройки гифок\n"
        text += "• Настройки топ чатов\n\n"
        text += "⚠️ <i>Это действие перезапишет все настройки в целевых чатах!</i>"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="✅ Синхронизировать все настройки",
            callback_data=f"sync_all_{network_id}_{source_chat_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_sync_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в sync_source_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def sync_all_callback(callback: CallbackQuery):
    """Обработчик синхронизации всех настроек"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[2])
        source_chat_id = int(parts[3])
        user_id = callback.from_user.id
        
        # Проверяем права
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Получаем целевые чаты
        network_chats = await network_db.get_network_chats(network_id)
        target_chats = [chat for chat in network_chats if chat['chat_id'] != source_chat_id]
        
        if not target_chats:
            await callback.answer("❌ Нет целевых чатов для синхронизации!", show_alert=True)
            return
        
        source_chat_info = await db.get_chat(source_chat_id)
        if not source_chat_info:
            await callback.answer("❌ Исходный чат не найден!", show_alert=True)
            return
        
        # Показываем процесс синхронизации
        await callback.message.edit_text(
            f"⏳ <b>Синхронизация настроек...</b>\n\n"
            f"📤 Исходный чат: {source_chat_info['chat_title']}\n"
            f"📥 Целевых чатов: {len(target_chats)}\n\n"
            f"Пожалуйста, подождите...",
            parse_mode=ParseMode.HTML
        )
        
        synced_count = 0
        errors = []
        
        # Получаем все настройки из исходного чата
        # 1. Настройки варнов
        warn_settings = await moderation_db.get_warn_settings(source_chat_id)
        
        # 2. Настройки статистики
        stat_settings = await db.get_chat_stat_settings(source_chat_id)
        
        # 3. Права рангов
        rank_permissions = {}
        for rank in [1, 2, 3, 4]:
            permissions = await db.get_all_rank_permissions(source_chat_id, rank)
            rank_permissions[rank] = permissions
        
        # 4. Русский префикс
        russian_prefix = await db.get_russian_commands_prefix_setting(source_chat_id)
        
        # 5. Автодопуск
        auto_accept = await db.get_auto_accept_join_requests(source_chat_id)
        auto_accept_notify = await db.get_auto_accept_notify(source_chat_id)
        
        # 6. Настройки анти-спама
        raid_settings = await raid_protection_db.get_settings(source_chat_id)
        
        # 7. Настройки утилит
        utilities_settings = await utilities_db.get_settings(source_chat_id)
        
        # 8. Настройки гифок
        gifs_enabled = get_gifs_enabled(source_chat_id)
        
        # 9. Настройки топ чатов
        top_chat_settings = await get_top_chat_settings_async(source_chat_id)
        
        # Синхронизируем настройки для каждого целевого чата
        for chat_data in target_chats:
            try:
                target_chat_id = chat_data['chat_id']
                
                # 1. Синхронизация варнов
                await moderation_db.update_warn_settings(
                    target_chat_id,
                    warn_limit=warn_settings['warn_limit'],
                    punishment_type=warn_settings['punishment_type'],
                    mute_duration=warn_settings['mute_duration']
                )
                
                # 2. Синхронизация статистики
                await db.set_chat_stats_enabled(target_chat_id, stat_settings.get('stats_enabled', True))
                
                # 3. Синхронизация прав рангов
                for rank, permissions in rank_permissions.items():
                    for permission_name, permission_value in permissions.items():
                        await db.set_rank_permission(target_chat_id, rank, permission_name, permission_value)
                
                # 4. Синхронизация русского префикса
                await db.set_russian_commands_prefix_setting(target_chat_id, russian_prefix)
                
                # 5. Синхронизация автодопуска
                await db.set_auto_accept_join_requests(target_chat_id, auto_accept)
                await db.set_auto_accept_notify(target_chat_id, auto_accept_notify)
                
                # 6. Синхронизация анти-спама
                await raid_protection_db.update_settings(
                    target_chat_id,
                    enabled=raid_settings.get('enabled', True),
                    gif_limit=raid_settings.get('gif_limit', 3),
                    gif_time_window=raid_settings.get('gif_time_window', 5),
                    sticker_limit=raid_settings.get('sticker_limit', 5),
                    sticker_time_window=raid_settings.get('sticker_time_window', 10),
                    duplicate_text_limit=raid_settings.get('duplicate_text_limit', 3),
                    duplicate_text_window=raid_settings.get('duplicate_text_window', 30),
                    mass_join_limit=raid_settings.get('mass_join_limit', 10),
                    mass_join_window=raid_settings.get('mass_join_window', 60),
                    similarity_threshold=raid_settings.get('similarity_threshold', 0.7),
                    notification_mode=raid_settings.get('notification_mode', 1),
                    auto_mute_duration=raid_settings.get('auto_mute_duration', 0)
                )
                
                # 7. Синхронизация утилит
                await utilities_db.update_settings(
                    target_chat_id,
                    emoji_spam_enabled=utilities_settings.get('emoji_spam_enabled', False),
                    emoji_spam_limit=utilities_settings.get('emoji_spam_limit', 10),
                    reaction_spam_enabled=utilities_settings.get('reaction_spam_enabled', False),
                    reaction_spam_limit=utilities_settings.get('reaction_spam_limit', 5),
                    reaction_spam_window=utilities_settings.get('reaction_spam_window', 120),
                    reaction_spam_warning_enabled=utilities_settings.get('reaction_spam_warning_enabled', True),
                    reaction_spam_punishment=utilities_settings.get('reaction_spam_punishment', 'kick'),
                    reaction_spam_ban_duration=utilities_settings.get('reaction_spam_ban_duration', 300),
                    fake_commands_enabled=utilities_settings.get('fake_commands_enabled', False)
                )
                
                # 8. Синхронизация гифок
                set_gifs_enabled(target_chat_id, gifs_enabled)
                
                # 9. Синхронизация топ чатов
                await set_top_chat_settings_async(target_chat_id, top_chat_settings)
                
                synced_count += 1
                
            except Exception as e:
                logger.error(f"Ошибка при синхронизации настроек для чата {chat_data['chat_id']}: {e}")
                chat_info = await db.get_chat(chat_data['chat_id'])
                chat_title = chat_info['chat_title'] if chat_info else f"Чат {chat_data['chat_id']}"
                errors.append(f"{chat_title}: {str(e)}")
        
        # Формируем результат
        text = f"✅ <b>Синхронизация завершена!</b>\n\n"
        text += f"📤 <b>Исходный чат:</b> {source_chat_info['chat_title']}\n"
        text += f"📥 <b>Синхронизировано:</b> {synced_count}/{len(target_chats)} чатов\n\n"
        
        if errors:
            text += f"⚠️ <b>Ошибки ({len(errors)}):</b>\n"
            for error in errors[:5]:  # Показываем максимум 5 ошибок
                text += f"• {error}\n"
            if len(errors) > 5:
                text += f"• ... и еще {len(errors) - 5} ошибок\n"
        
        text += "\n<b>Синхронизированные настройки:</b>\n"
        text += "• Варны, статистика, права рангов\n"
        text += "• Русский префикс, автодопуск\n"
        text += "• Анти-спам, утилиты, гифки\n"
        text += "• Топ чатов"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔙 Назад к сетке",
            callback_data=f"net_view_{network_id}"
        ))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer("✅ Синхронизация завершена!")
        
    except Exception as e:
        logger.error(f"Ошибка в sync_all_callback: {e}")
        await callback.answer("❌ Произошла ошибка при синхронизации!", show_alert=True)
        await callback.message.edit_text(
            f"❌ <b>Ошибка синхронизации</b>\n\n"
            f"Произошла ошибка: {str(e)}\n\n"
            f"Попробуйте еще раз.",
            parse_mode=ParseMode.HTML
        )


async def net_stats_callback(callback: CallbackQuery):
    """Обработчик подробной статистики сетки"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        text = f"📊 <b>Подробная статистика сетки #{network_id}</b>\n\n"
        
        # Общая статистика
        total_messages_today = 0
        total_messages_week = 0
        total_members = 0
        active_users_today = set()
        
        for chat_data in network_chats:
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if not chat_info:
                continue
            
            # Статистика за сегодня
            messages_today = await db.get_today_message_count(chat_id)
            total_messages_today += messages_today
            
            # Статистика за неделю
            week_stats = await db.get_daily_stats(chat_id, 7)
            messages_week = sum(stat['message_count'] for stat in week_stats)
            total_messages_week += messages_week
            
            # Активные пользователи за сегодня
            top_users = await db.get_top_users_today(chat_id, 100)
            for user in top_users:
                active_users_today.add(user['user_id'])
            
            # Количество участников
            try:
                member_count = await bot.get_chat_member_count(chat_id)
                total_members += member_count
            except:
                pass
        
        text += f"📈 <b>Общая статистика:</b>\n"
        text += f"• Сообщений сегодня: {total_messages_today}\n"
        text += f"• Сообщений за неделю: {total_messages_week}\n"
        text += f"• Активных пользователей сегодня: {len(active_users_today)}\n"
        text += f"• Всего участников: {total_members if total_members > 0 else '?'}\n\n"
        
        # Статистика по чатам
        text += f"📋 <b>По чатам:</b>\n"
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                messages_today = await db.get_today_message_count(chat_id)
                week_stats = await db.get_daily_stats(chat_id, 7)
                messages_week = sum(stat['message_count'] for stat in week_stats)
                
                try:
                    member_count = await bot.get_chat_member_count(chat_id)
                except:
                    member_count = "?"
                
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                text += f"\n{i}. <b>{chat_info['chat_title']}</b>{primary_mark}\n"
                text += f"   📊 Сегодня: {messages_today} | За неделю: {messages_week}\n"
                text += f"   👥 Участников: {member_count}\n"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_stats_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_moderation_callback(callback: CallbackQuery):
    """Обработчик модерации чатов в сетке"""
    try:
        network_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        if len(network_chats) == 0:
            await callback.answer("❌ В сетке нет чатов!", show_alert=True)
            return
        
        text = f"🛡️ <b>Модерация чатов сетки #{network_id}</b>\n\n"
        text += "Выберите чат для управления:\n\n"
        
        builder = InlineKeyboardBuilder()
        
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                primary_mark = " 👑" if chat_data['is_primary'] else ""
                text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}\n"
                
                builder.add(InlineKeyboardButton(
                    text=f"{i}. {chat_info['chat_title']}{primary_mark}",
                    callback_data=f"net_moderation_chat_{network_id}_{chat_id}"
                ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_view_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_moderation_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_moderation_chat_callback(callback: CallbackQuery):
    """Обработчик выбора действий модерации для конкретного чата"""
    try:
        # Формат: net_moderation_chat_{network_id}_{chat_id}
        # Проверяем, что это именно наш формат, а не net_moderation_toggle_media_
        if callback.data.startswith("net_moderation_toggle_media_") or callback.data.startswith("net_moderation_close_"):
            # Это не наш callback, пропускаем
            return
        
        parts = callback.data.split("_")
        if len(parts) < 5:
            await callback.answer("❌ Ошибка в данных!", show_alert=True)
            return
        
        # Проверяем, что parts[2] это "chat", а не "toggle" или что-то еще
        if parts[2] != "chat":
            logger.warning(f"Неожиданный формат callback_data в net_moderation_chat_callback: {callback.data}")
            return
        
        network_id = int(parts[3])
        chat_id = int(parts[4])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Проверяем, что чат все еще находится в этой сети
        network_chats = await network_db.get_network_chats(network_id)
        chat_in_network = any(chat['chat_id'] == chat_id for chat in network_chats)
        if not chat_in_network:
            await callback.answer("❌ Этот чат больше не находится в сетке!", show_alert=True)
            # Возвращаемся к списку модерации - обновляем сообщение напрямую
            network_chats_list = await network_db.get_network_chats(network_id)
            if len(network_chats_list) == 0:
                await callback.message.edit_text(
                    "❌ В сетке нет чатов!",
                    reply_markup=InlineKeyboardBuilder().add(
                        InlineKeyboardButton(text="🔙 Назад", callback_data=f"net_view_{network_id}")
                    ).as_markup()
                )
                return
            
            text = f"🛡️ <b>Модерация чатов сетки #{network_id}</b>\n\n"
            text += "Выберите чат для управления:\n\n"
            
            builder = InlineKeyboardBuilder()
            
            for i, chat_data in enumerate(network_chats_list, 1):
                chat_id_item = chat_data['chat_id']
                chat_info = await db.get_chat(chat_id_item)
                if chat_info:
                    primary_mark = " 👑" if chat_data['is_primary'] else ""
                    text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}\n"
                    
                    builder.add(InlineKeyboardButton(
                        text=f"{i}. {chat_info['chat_title']}{primary_mark}",
                        callback_data=f"net_moderation_chat_{network_id}_{chat_id_item}"
                    ))
            
            builder.add(InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"net_view_{network_id}"
            ))
            builder.adjust(1)
            
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            return
        
        chat_info = await db.get_chat(chat_id)
        chat_title = chat_info['chat_title'] if chat_info else f"Чат {chat_id}"
        
        # Получаем текущие права чата
        try:
            chat_obj = await bot.get_chat(chat_id)
            current_permissions = getattr(chat_obj, 'permissions', None)
            
            can_send_messages = True
            can_send_media = True
            
            if current_permissions:
                can_send_messages = getattr(current_permissions, 'can_send_messages', True)
                can_send_media = getattr(current_permissions, 'can_send_media_messages', True)
        except Exception as e:
            logger.error(f"Ошибка при получении прав чата {chat_id}: {e}")
            # Показываем статус с дефолтными значениями, если не удалось получить права
            can_send_messages = True
            can_send_media = True
            # Пытаемся обновить сообщение с доступной информацией
            try:
                text = f"🛡️ <b>Модерация: {chat_title}</b>\n\n"
                text += f"📊 Текущее состояние:\n"
                text += f"• Сообщения: {'✅ Включены' if can_send_messages else '❌ Отключены'}\n"
                text += f"• Медиа: {'✅ Включено' if can_send_media else '❌ Отключено'}\n\n"
                text += "⚠️ <i>Не удалось получить актуальный статус чата</i>\n\n"
                text += "Выберите действие:"
                
                builder = InlineKeyboardBuilder()
                
                # Кнопка закрыть/открыть чат
                builder.add(InlineKeyboardButton(
                    text="🔒 Закрыть чат",
                    callback_data=f"net_moderation_close_{network_id}_{chat_id}_close"
                ))
                
                # Кнопка включить/отключить медиа
                builder.add(InlineKeyboardButton(
                    text="🚫 Отключить медиа",
                    callback_data=f"net_moderation_toggle_media_{network_id}_{chat_id}_disable"
                ))
                
                builder.add(InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data=f"net_moderation_{network_id}"
                ))
                builder.adjust(1)
                
                await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
                await callback.answer("⚠️ Не удалось получить актуальный статус чата", show_alert=True)
            except Exception as edit_error:
                logger.error(f"Ошибка при обновлении сообщения: {edit_error}")
                await callback.answer("❌ Не удалось получить информацию о чате!", show_alert=True)
            return
        
        text = f"🛡️ <b>Модерация: {chat_title}</b>\n\n"
        text += f"📊 Текущее состояние:\n"
        text += f"• Сообщения: {'✅ Включены' if can_send_messages else '❌ Отключены'}\n"
        text += f"• Медиа: {'✅ Включено' if can_send_media else '❌ Отключено'}\n\n"
        text += "Выберите действие:"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопка закрыть/открыть чат
        if can_send_messages:
            builder.add(InlineKeyboardButton(
                text="🔒 Закрыть чат",
                callback_data=f"net_moderation_close_{network_id}_{chat_id}_close"
            ))
        else:
            builder.add(InlineKeyboardButton(
                text="🔓 Открыть чат",
                callback_data=f"net_moderation_close_{network_id}_{chat_id}_open"
            ))
        
        # Кнопка включить/отключить медиа
        # Не показываем кнопку включения медиа, если чат закрыт
        if can_send_media:
            builder.add(InlineKeyboardButton(
                text="🚫 Отключить медиа",
                callback_data=f"net_moderation_toggle_media_{network_id}_{chat_id}_disable"
            ))
        elif can_send_messages:
            # Медиа отключено, но сообщения включены - можно включить медиа
            builder.add(InlineKeyboardButton(
                text="✅ Включить медиа",
                callback_data=f"net_moderation_toggle_media_{network_id}_{chat_id}_enable"
            ))
        # Если чат закрыт (can_send_messages=False), не показываем кнопку включения медиа
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_moderation_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_moderation_chat_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_moderation_close_chat_callback(callback: CallbackQuery):
    """Обработчик закрытия/открытия чата"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[3])
        chat_id = int(parts[4])
        action = parts[5]  # 'close' или 'open'
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Проверяем, что чат все еще находится в этой сети
        network_chats = await network_db.get_network_chats(network_id)
        chat_in_network = any(chat['chat_id'] == chat_id for chat in network_chats)
        if not chat_in_network:
            await callback.answer("❌ Этот чат больше не находится в сетке!", show_alert=True)
            # Возвращаемся к списку модерации - обновляем сообщение напрямую
            network_chats_list = await network_db.get_network_chats(network_id)
            if len(network_chats_list) == 0:
                await callback.message.edit_text(
                    "❌ В сетке нет чатов!",
                    reply_markup=InlineKeyboardBuilder().add(
                        InlineKeyboardButton(text="🔙 Назад", callback_data=f"net_view_{network_id}")
                    ).as_markup()
                )
                return
            
            text = f"🛡️ <b>Модерация чатов сетки #{network_id}</b>\n\n"
            text += "Выберите чат для управления:\n\n"
            
            builder = InlineKeyboardBuilder()
            
            for i, chat_data in enumerate(network_chats_list, 1):
                chat_id_item = chat_data['chat_id']
                chat_info = await db.get_chat(chat_id_item)
                if chat_info:
                    primary_mark = " 👑" if chat_data['is_primary'] else ""
                    text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}\n"
                    
                    builder.add(InlineKeyboardButton(
                        text=f"{i}. {chat_info['chat_title']}{primary_mark}",
                        callback_data=f"net_moderation_chat_{network_id}_{chat_id_item}"
                    ))
            
            builder.add(InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"net_view_{network_id}"
            ))
            builder.adjust(1)
            
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            return
        
        chat_info = await db.get_chat(chat_id)
        chat_title = chat_info['chat_title'] if chat_info else f"Чат {chat_id}"
        
        # Проверяем права бота в чате
        try:
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await callback.answer("❌ Бот не является администратором в этом чате!", show_alert=True)
                return
        except Exception as e:
            logger.error(f"Ошибка при проверке прав бота в чате {chat_id}: {e}")
            await callback.answer("❌ Не удалось проверить права бота в чате!", show_alert=True)
            return
        
        # Получаем текущие права для сохранения других настроек
        try:
            chat_obj = await bot.get_chat(chat_id)
            current_permissions = getattr(chat_obj, 'permissions', None)
        except Exception as e:
            logger.error(f"Ошибка при получении прав чата {chat_id}: {e}")
            current_permissions = None
        
        # Создаем новые права
        if action == 'close':
            # Закрываем чат
            new_permissions = ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True
            )
            success_message = "✅ Чат закрыт!"
        else:
            # Открываем чат
            new_permissions = ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True
            )
            success_message = "✅ Чат открыт!"
        
        try:
            await bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=new_permissions,
                use_independent_chat_permissions=True
            )
            await callback.answer(success_message)
        except Exception as e:
            error_str = str(e).lower()
            # Обрабатываем ошибку CHAT_NOT_MODIFIED - это нормально, права уже установлены
            if "chat_not_modified" in error_str:
                await callback.answer("ℹ️ Права уже установлены в этом состоянии", show_alert=False)
            else:
                logger.error(f"Ошибка при изменении прав чата {chat_id}: {e}")
                await callback.answer("❌ Ошибка при изменении прав чата!", show_alert=True)
                return
        
        # Обновляем сообщение с актуальным статусом напрямую
        chat_info = await db.get_chat(chat_id)
        chat_title = chat_info['chat_title'] if chat_info else f"Чат {chat_id}"
        
        # Получаем текущие права чата для отображения актуального статуса
        try:
            chat_obj = await bot.get_chat(chat_id)
            current_permissions = getattr(chat_obj, 'permissions', None)
            
            can_send_messages = True
            can_send_media = True
            
            if current_permissions:
                can_send_messages = getattr(current_permissions, 'can_send_messages', True)
                can_send_media = getattr(current_permissions, 'can_send_media_messages', True)
        except Exception as e:
            logger.error(f"Ошибка при получении прав чата {chat_id} для обновления статуса: {e}")
            can_send_messages = True
            can_send_media = True
        
        text = f"🛡️ <b>Модерация: {chat_title}</b>\n\n"
        text += f"📊 Текущее состояние:\n"
        text += f"• Сообщения: {'✅ Включены' if can_send_messages else '❌ Отключены'}\n"
        text += f"• Медиа: {'✅ Включено' if can_send_media else '❌ Отключено'}\n\n"
        text += "Выберите действие:"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопка закрыть/открыть чат
        if can_send_messages:
            builder.add(InlineKeyboardButton(
                text="🔒 Закрыть чат",
                callback_data=f"net_moderation_close_{network_id}_{chat_id}_close"
            ))
        else:
            builder.add(InlineKeyboardButton(
                text="🔓 Открыть чат",
                callback_data=f"net_moderation_close_{network_id}_{chat_id}_open"
            ))
        
        # Кнопка включить/отключить медиа
        if can_send_media:
            builder.add(InlineKeyboardButton(
                text="🚫 Отключить медиа",
                callback_data=f"net_moderation_toggle_media_{network_id}_{chat_id}_disable"
            ))
        elif can_send_messages:
            builder.add(InlineKeyboardButton(
                text="✅ Включить медиа",
                callback_data=f"net_moderation_toggle_media_{network_id}_{chat_id}_enable"
            ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_moderation_{network_id}"
        ))
        builder.adjust(1)
        
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        except Exception as edit_error:
            error_str = str(edit_error).lower()
            # Обрабатываем ошибку "message is not modified" - это нормально, сообщение уже актуально
            if "message is not modified" in error_str or "not modified" in error_str:
                # Сообщение уже актуально, просто игнорируем
                pass
            else:
                logger.error(f"Ошибка при обновлении сообщения в net_moderation_close_chat_callback: {edit_error}")
        
    except Exception as e:
        logger.error(f"Ошибка в net_moderation_close_chat_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_moderation_toggle_media_callback(callback: CallbackQuery):
    """Обработчик включения/отключения медиа в чате"""
    try:
        parts = callback.data.split("_")
        network_id = int(parts[4])
        chat_id = int(parts[5])
        action = parts[6]  # 'enable' или 'disable'
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Проверяем, что чат все еще находится в этой сети
        network_chats = await network_db.get_network_chats(network_id)
        chat_in_network = any(chat['chat_id'] == chat_id for chat in network_chats)
        if not chat_in_network:
            await callback.answer("❌ Этот чат больше не находится в сетке!", show_alert=True)
            # Возвращаемся к списку модерации - обновляем сообщение напрямую
            network_chats_list = await network_db.get_network_chats(network_id)
            if len(network_chats_list) == 0:
                await callback.message.edit_text(
                    "❌ В сетке нет чатов!",
                    reply_markup=InlineKeyboardBuilder().add(
                        InlineKeyboardButton(text="🔙 Назад", callback_data=f"net_view_{network_id}")
                    ).as_markup()
                )
                return
            
            text = f"🛡️ <b>Модерация чатов сетки #{network_id}</b>\n\n"
            text += "Выберите чат для управления:\n\n"
            
            builder = InlineKeyboardBuilder()
            
            for i, chat_data in enumerate(network_chats_list, 1):
                chat_id_item = chat_data['chat_id']
                chat_info = await db.get_chat(chat_id_item)
                if chat_info:
                    primary_mark = " 👑" if chat_data['is_primary'] else ""
                    text += f"{i}. <b>{chat_info['chat_title']}</b>{primary_mark}\n"
                    
                    builder.add(InlineKeyboardButton(
                        text=f"{i}. {chat_info['chat_title']}{primary_mark}",
                        callback_data=f"net_moderation_chat_{network_id}_{chat_id_item}"
                    ))
            
            builder.add(InlineKeyboardButton(
                text="🔙 Назад",
                callback_data=f"net_view_{network_id}"
            ))
            builder.adjust(1)
            
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            return
        
        chat_info = await db.get_chat(chat_id)
        chat_title = chat_info['chat_title'] if chat_info else f"Чат {chat_id}"
        
        # Проверяем права бота в чате
        try:
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await callback.answer("❌ Бот не является администратором в этом чате!", show_alert=True)
                return
        except Exception as e:
            logger.error(f"Ошибка при проверке прав бота в чате {chat_id}: {e}")
            await callback.answer("❌ Не удалось проверить права бота в чате!", show_alert=True)
            return
        
        # Получаем текущие права
        try:
            chat_obj = await bot.get_chat(chat_id)
            current_permissions = getattr(chat_obj, 'permissions', None)
            
            can_send_messages = True
            if current_permissions:
                can_send_messages = getattr(current_permissions, 'can_send_messages', True)
        except Exception as e:
            logger.error(f"Ошибка при получении прав чата {chat_id}: {e}")
            can_send_messages = True
        
        # Проверяем, что чат не закрыт перед включением медиа
        if action == 'enable' and not can_send_messages:
            await callback.answer("❌ Нельзя включить медиа, если чат закрыт! Сначала откройте чат.", show_alert=True)
            return
        
        # Создаем новые права
        if action == 'disable':
            # Отключаем медиа (но оставляем сообщения как есть)
            new_permissions = ChatPermissions(
                can_send_messages=can_send_messages,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True
            )
            success_message = "✅ Медиа отключено!"
        else:
            # Включаем медиа (только если сообщения включены)
            new_permissions = ChatPermissions(
                can_send_messages=True,  # Убеждаемся, что сообщения включены
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,  # Включаем предпросмотр ссылок
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True
            )
            success_message = "✅ Медиа включено!"
        
        try:
            await bot.set_chat_permissions(
                chat_id=chat_id,
                permissions=new_permissions,
                use_independent_chat_permissions=True
            )
            await callback.answer(success_message)
        except Exception as e:
            error_str = str(e).lower()
            # Обрабатываем ошибку CHAT_NOT_MODIFIED - это нормально, права уже установлены
            if "chat_not_modified" in error_str:
                await callback.answer("ℹ️ Права уже установлены в этом состоянии", show_alert=False)
            else:
                logger.error(f"Ошибка при изменении прав медиа в чате {chat_id}: {e}")
                await callback.answer("❌ Ошибка при изменении прав медиа!", show_alert=True)
                return
        
        # Обновляем сообщение с актуальным статусом напрямую
        chat_info = await db.get_chat(chat_id)
        chat_title = chat_info['chat_title'] if chat_info else f"Чат {chat_id}"
        
        # Получаем текущие права чата для отображения актуального статуса
        try:
            chat_obj = await bot.get_chat(chat_id)
            current_permissions = getattr(chat_obj, 'permissions', None)
            
            can_send_messages = True
            can_send_media = True
            
            if current_permissions:
                can_send_messages = getattr(current_permissions, 'can_send_messages', True)
                can_send_media = getattr(current_permissions, 'can_send_media_messages', True)
        except Exception as e:
            logger.error(f"Ошибка при получении прав чата {chat_id} для обновления статуса: {e}")
            can_send_messages = True
            can_send_media = True
        
        text = f"🛡️ <b>Модерация: {chat_title}</b>\n\n"
        text += f"📊 Текущее состояние:\n"
        text += f"• Сообщения: {'✅ Включены' if can_send_messages else '❌ Отключены'}\n"
        text += f"• Медиа: {'✅ Включено' if can_send_media else '❌ Отключено'}\n\n"
        text += "Выберите действие:"
        
        builder = InlineKeyboardBuilder()
        
        # Кнопка закрыть/открыть чат
        if can_send_messages:
            builder.add(InlineKeyboardButton(
                text="🔒 Закрыть чат",
                callback_data=f"net_moderation_close_{network_id}_{chat_id}_close"
            ))
        else:
            builder.add(InlineKeyboardButton(
                text="🔓 Открыть чат",
                callback_data=f"net_moderation_close_{network_id}_{chat_id}_open"
            ))
        
        # Кнопка включить/отключить медиа
        if can_send_media:
            builder.add(InlineKeyboardButton(
                text="🚫 Отключить медиа",
                callback_data=f"net_moderation_toggle_media_{network_id}_{chat_id}_disable"
            ))
        elif can_send_messages:
            builder.add(InlineKeyboardButton(
                text="✅ Включить медиа",
                callback_data=f"net_moderation_toggle_media_{network_id}_{chat_id}_enable"
            ))
        
        builder.add(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"net_moderation_{network_id}"
        ))
        builder.adjust(1)
        
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        except Exception as edit_error:
            error_str = str(edit_error).lower()
            # Обрабатываем ошибку "message is not modified" - это нормально, сообщение уже актуально
            if "message is not modified" in error_str or "not modified" in error_str:
                # Сообщение уже актуально, просто игнорируем
                pass
            else:
                logger.error(f"Ошибка при обновлении сообщения в net_moderation_toggle_media_callback: {edit_error}")
        
    except Exception as e:
        logger.error(f"Ошибка в net_moderation_toggle_media_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_delete_network_callback(callback: CallbackQuery):
    """Обработчик подтверждения удаления сетки"""
    try:
        network_id = int(callback.data.split("_")[3])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Получаем чаты в сети
        network_chats = await network_db.get_network_chats(network_id)
        
        text = f"🗑️ <b>Удаление сетки #{network_id}</b>\n\n"
        text += f"⚠️ <b>Внимание!</b> Это действие нельзя отменить!\n\n"
        text += f"Из сетки будет удалено <b>{len(network_chats)}</b> чат(ов):\n\n"
        
        for i, chat_data in enumerate(network_chats, 1):
            chat_id = chat_data['chat_id']
            chat_info = await db.get_chat(chat_id)
            if chat_info:
                text += f"{i}. <b>{chat_info['chat_title']}</b>\n"
        
        text += "\nВы уверены, что хотите удалить сетку?"
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"net_delete_network_confirm_{network_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"net_view_{network_id}"
        ))
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в net_delete_network_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)


async def net_delete_network_confirm_callback(callback: CallbackQuery):
    """Обработчик подтверждения удаления сетки"""
    try:
        network_id = int(callback.data.split("_")[4])
        user_id = callback.from_user.id
        
        # Проверяем, что пользователь - владелец сети
        network_owner = await network_db.get_network_owner(network_id)
        if network_owner != user_id:
            await callback.answer("❌ У вас нет прав для управления этой сеткой!", show_alert=True)
            return
        
        # Получаем чаты в сети для информации
        network_chats = await network_db.get_network_chats(network_id)
        chat_count = len(network_chats)
        
        # Удаляем сетку
        success = await network_db.delete_network(network_id)
        
        if success:
            text = f"✅ <b>Сетка #{network_id} удалена!</b>\n\n"
            text += f"Из сетки было удалено <b>{chat_count}</b> чат(ов).\n\n"
            text += "Используйте /net для управления сетками."
            
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(
                text="🔙 Главное меню",
                callback_data="back_to_menu"
            ))
            
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
            await callback.answer("✅ Сетка удалена!")
        else:
            await callback.answer("❌ Ошибка при удалении сетки!", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка в net_delete_network_confirm_callback: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)
