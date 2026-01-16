"""
Система кулдаунов для защиты от флуд-контроля
"""
import time
import logging

from databases.database import db
from utils.permissions import get_effective_rank

logger = logging.getLogger(__name__)

# Система кулдаунов для защиты от флуд-контроля
user_cooldowns = {}  # {user_id: last_action_time}
moderation_cooldowns = {}  # {user_id: last_moderation_action_time}
chatnet_update_cooldowns = {}  # {user_id: last_update_time}
hints_config_cooldowns = {}  # {user_id: last_hints_config_change_time}

# Константы кулдаунов
COOLDOWN_DURATION = 3  # 3 секунды между действиями
MODERATION_COOLDOWN_DURATION = 4  # 4 секунды между действиями модерации
CHATNET_UPDATE_COOLDOWN_DURATION = 600  # 10 минут между обновлениями /chatnet
HINTS_CONFIG_COOLDOWN_DURATION = 60  # 1 минута между изменениями настроек подсказок


def check_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверяет кулдаун пользователя
    Возвращает (can_act, remaining_seconds)
    """
    current_time = time.time()
    
    if user_id in user_cooldowns:
        last_action = user_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < COOLDOWN_DURATION:
            remaining = int(COOLDOWN_DURATION - time_passed)
            return False, remaining
    
    # Обновляем время последнего действия
    user_cooldowns[user_id] = current_time
    return True, 0


def check_user_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверяет, прошло ли достаточно времени с последнего действия пользователя
    Возвращает (можно_действовать, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in user_cooldowns:
        last_action = user_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < COOLDOWN_DURATION:
            remaining_time = COOLDOWN_DURATION - time_passed
            return False, int(remaining_time) + 1
    
    # Обновляем время последнего действия
    user_cooldowns[user_id] = current_time
    return True, 0


def check_moderation_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверяет, прошло ли достаточно времени с последнего действия модерации
    Возвращает (можно_действовать, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in moderation_cooldowns:
        last_action = moderation_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < MODERATION_COOLDOWN_DURATION:
            remaining_time = MODERATION_COOLDOWN_DURATION - time_passed
            return False, int(remaining_time) + 1
    
    # Обновляем время последнего действия модерации
    moderation_cooldowns[user_id] = current_time
    return True, 0


def check_chatnet_update_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверяет, прошло ли достаточно времени с последнего обновления /chatnet
    Возвращает (можно_выполнить, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in chatnet_update_cooldowns:
        last_action = chatnet_update_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < CHATNET_UPDATE_COOLDOWN_DURATION:
            remaining_time = CHATNET_UPDATE_COOLDOWN_DURATION - time_passed
            return False, int(remaining_time)
    
    chatnet_update_cooldowns[user_id] = current_time
    return True, 0


def check_hints_config_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Проверка кулдауна для изменения настроек подсказок
    Возвращает (можно_действовать, оставшееся_время_в_секундах)
    """
    current_time = time.time()
    
    if user_id in hints_config_cooldowns:
        last_action = hints_config_cooldowns[user_id]
        time_passed = current_time - last_action
        
        if time_passed < HINTS_CONFIG_COOLDOWN_DURATION:
            remaining = int(HINTS_CONFIG_COOLDOWN_DURATION - time_passed)
            return False, remaining
    
    # Обновляем время последнего действия
    hints_config_cooldowns[user_id] = current_time
    return True, 0


async def should_show_hint(chat_id: int, user_id: int) -> bool:
    """
    Проверяет, нужно ли показывать подсказку пользователю
    """
    try:
        # Получаем режим подсказок для чата
        hints_mode = await db.get_hints_mode(chat_id)
        
        # 0 = подсказки для всех
        if hints_mode == 0:
            return True
        
        # 2 = подсказки выключены
        if hints_mode == 2:
            return False
        
        # 1 = подсказки только для модераторов
        if hints_mode == 1:
            # Проверяем ранг пользователя
            user_rank = await get_effective_rank(chat_id, user_id)
            # Показываем подсказки только модераторам (ранги 1-4)
            return user_rank <= 4
        
        return True  # По умолчанию показываем подсказки
        
    except Exception as e:
        logger.error(f"Ошибка при проверке режима подсказок: {e}")
        return True  # В случае ошибки показываем подсказки

