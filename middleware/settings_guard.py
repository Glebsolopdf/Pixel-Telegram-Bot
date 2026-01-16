"""
Middleware для защиты настроек от несанкционированного доступа
"""
import logging
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import CallbackQuery

from utils.constants import SETTINGS_CALLBACK_PREFIXES, RANK_OWNER, RANK_ADMIN
from utils.permissions import get_effective_rank
from utils.formatting import get_philosophical_access_denied_message
from databases.database import db

logger = logging.getLogger(__name__)


class SettingsGuardMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            if not isinstance(event, CallbackQuery):
                return await handler(event, data)

            # Проверяем, что чат активен и не заморожен (только для групповых чатов)
            if event.message and event.message.chat:
                chat_id = event.message.chat.id
                if event.message.chat.type in ['group', 'supergroup']:
                    try:
                        chat_info = await db.get_chat(chat_id)
                        if chat_info and (not chat_info.get('is_active', True) or chat_info.get('frozen_at')):
                            logger.debug(f"Попытка использовать callback в неактивном/замороженном чате {chat_id}")
                            try:
                                await event.answer("❌ Бот был удален из этого чата", show_alert=True)
                            except Exception:
                                pass  # Игнорируем ошибки ответа на callback
                            return  # Прерываем обработку
                    except Exception as e:
                        logger.error(f"Ошибка при проверке активности чата в middleware: {e}")
                        # В случае ошибки продолжаем обработку

            cd = (event.data or "")
            # Обрабатываем только кнопки из панелей настроек
            if not cd.startswith(SETTINGS_CALLBACK_PREFIXES):
                return await handler(event, data)

            # Разрешить только владельцу/администратору бота по рангу внутри бота
            chat_id = event.message.chat.id if event.message else None
            user_id = event.from_user.id if event.from_user else None
            if not chat_id or not user_id:
                return await handler(event, data)

            rank = await get_effective_rank(chat_id, user_id)
            if rank not in (RANK_OWNER, RANK_ADMIN):
                quote = await get_philosophical_access_denied_message()
                await event.answer(quote, show_alert=True)
                return

            return await handler(event, data)
        except Exception as e:
            logger.error(f"Ошибка в SettingsGuardMiddleware: {e}")
            # На всякий случай не блокируем обработку при ошибке
            return await handler(event, data)

