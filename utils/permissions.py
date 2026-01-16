"""
Функции для работы с правами и рангами
"""
import logging
from typing import Optional
from aiogram import Bot

from databases.database import db
from utils.constants import RANK_OWNER, RANK_USER, RANK_NAMES

logger = logging.getLogger(__name__)

# Глобальная переменная bot будет установлена при инициализации
bot: Optional[Bot] = None

def set_bot_instance(bot_instance: Bot):
    """Устанавливает экземпляр бота для использования в модуле"""
    global bot
    bot = bot_instance


def get_rank_name(rank: int, count: int = 1) -> str:
    """Получить название ранга с учетом множественного числа"""
    return RANK_NAMES[rank][0] if count == 1 else RANK_NAMES[rank][1]


async def get_effective_rank(chat_id: int, user_id: int) -> int:
    """
    Получить эффективный ранг пользователя:
    - Проверяет ранг в БД бота
    - Исключение: владелец чата автоматически получает ранг владельца
    - Не учитывает Telegram-статус других пользователей
    """
    try:
        # Проверяем, является ли пользователь владельцем чата
        try:
            if bot:
                member = await bot.get_chat_member(chat_id, user_id)
                if member.status == 'creator':
                    return RANK_OWNER  # Владелец чата всегда имеет ранг владельца
        except Exception:
            pass  # Игнорируем ошибки при проверке статуса
        
        # Проверяем ранг в БД
        db_rank = await db.get_user_rank(chat_id, user_id)
        
        # Возвращаем ранг из БД или обычного пользователя
        if db_rank is not None:
            return db_rank
        else:
            return RANK_USER  # Обычный пользователь по умолчанию
            
    except Exception as e:
        logger.error(f"Ошибка при получении ранга пользователя {user_id} в чате {chat_id}: {e}")
        # В случае ошибки возвращаем обычного пользователя
        return RANK_USER


async def check_permission(chat_id: int, user_id: int, permission_type: str, fallback_rank_check=None) -> bool:
    """
    Проверяет права с fallback на старую систему рангов
    """
    # Пытаемся получить из новой системы
    has_perm = await db.has_permission(chat_id, user_id, permission_type)
    if has_perm is not None:
        # Если право найдено в БД (даже если False), используем его
        return has_perm
    
    # Если права не настроены в БД, используем fallback на старую систему
    # Но только если fallback предоставлен
    if fallback_rank_check:
        rank = await get_effective_rank(chat_id, user_id)
        return fallback_rank_check(rank)
    
    return False


async def check_admin_rights(bot: Bot, chat_id: int) -> bool:
    """Проверка прав администратора бота в чате"""
    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        has_admin = bot_member.status in ['administrator', 'creator']
        
        # Обновляем информацию в базе данных
        try:
            await db.update_admin_rights(chat_id, has_admin)
        except Exception as db_error:
            logger.warning(f"Ошибка при обновлении прав администратора в БД для чата {chat_id}: {db_error}")
        
        return has_admin
    except Exception as e:
        error_str = str(e).lower()
        # Если чат был мигрирован, обновляем ID в базе данных
        if "group chat was upgraded to a supergroup" in error_str:
            # Извлекаем новый ID из ошибки
            import re
            match = re.search(r'with id (-?\d+)', str(e))
            if match:
                new_chat_id = int(match.group(1))
                await db.update_chat_id(chat_id, new_chat_id)
                # Рекурсивно вызываем функцию с новым ID
                return await check_admin_rights(bot, new_chat_id)
        
        # Если бот не является участником чата или нет прав - это нормально, просто возвращаем False
        if "chat not found" in error_str or "user not found" in error_str or "not a member" in error_str:
            logger.debug(f"Бот не является участником чата {chat_id} или чат не найден: {e}")
        else:
            logger.warning(f"Ошибка при проверке прав администратора для чата {chat_id}: {e}")
        return False

