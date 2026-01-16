"""
Middleware для автоматического обнаружения спама командами
Блокирует команды для пользователей, которые спамят (3+ команды за 60 секунд)
"""
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Tuple
from collections import defaultdict

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message, TelegramObject

from databases.database import db
from utils.command_aliases import get_command_alias, is_command_alias

logger = logging.getLogger(__name__)

# Константы для обнаружения спама
SPAM_WINDOW = 60  # Окно времени для обнаружения спама (в секундах)
SPAM_THRESHOLD = 3  # Количество команд для активации кулдауна
COOLDOWN_DURATION = 180  # Длительность кулдауна (3 минуты в секундах)

# Команды модерации, которые всегда разрешены
MODERATION_COMMANDS = {
    'mute', 'unmute',
    'kick', 'ban', 'unban',
    'warn', 'unwarn',
    'ap', 'unap',
    'staff', 'punishhistory'
}


class AutoSpamDetectionMiddleware(BaseMiddleware):
    """Middleware для автоматического обнаружения и блокировки спама командами"""
    
    def __init__(self):
        """Инициализация middleware с хранилищем команд и кулдаунов"""
        # Хранилище истории команд: {(chat_id, user_id): [timestamps]}
        self._command_history: Dict[Tuple[int, int], List[float]] = defaultdict(list)
        # Хранилище активных кулдаунов: {(chat_id, user_id): cooldown_end_timestamp}
        self._active_cooldowns: Dict[Tuple[int, int], float] = {}
        # Время последней очистки
        self._last_cleanup_time = time.time()
        # Интервал очистки старых записей (каждые 5 минут)
        self._cleanup_interval = 300
    
    def _cleanup_old_entries(self):
        """Очистка старых записей для предотвращения утечек памяти"""
        current_time = time.time()
        
        # Проверяем, нужно ли выполнять очистку
        if current_time - self._last_cleanup_time < self._cleanup_interval:
            return
        
        # Удаляем старые записи из истории команд (старше окна спама)
        cutoff_time = current_time - SPAM_WINDOW
        keys_to_clean = []
        
        for key, timestamps in self._command_history.items():
            # Оставляем только записи в пределах окна спама
            filtered_timestamps = [ts for ts in timestamps if ts >= cutoff_time]
            if filtered_timestamps:
                self._command_history[key] = filtered_timestamps
            else:
                keys_to_clean.append(key)
        
        for key in keys_to_clean:
            del self._command_history[key]
        
        # Удаляем истекшие кулдауны
        expired_cooldowns = [
            key for key, end_time in self._active_cooldowns.items()
            if current_time >= end_time
        ]
        
        for key in expired_cooldowns:
            del self._active_cooldowns[key]
        
        if keys_to_clean or expired_cooldowns:
            logger.debug(
                f"AutoSpamDetectionMiddleware: очищено {len(keys_to_clean)} историй команд, "
                f"{len(expired_cooldowns)} истекших кулдаунов"
            )
        
        self._last_cleanup_time = current_time
    
    async def _normalize_command(self, message: Message) -> tuple[str, str]:
        """
        Нормализует команду (извлекает и преобразует в английский эквивалент)
        Возвращает (original_command, normalized_command)
        """
        text = message.text.strip() if message.text else ""
        
        # Проверяем, это английская команда (начинается с /)
        if text.startswith('/'):
            command_text = text.split()[0] if text.split() else text
            normalized = command_text.lstrip('/').lower()
            return command_text, normalized
        
        # Это может быть русский алиас
        # Проверяем настройку префикса
        requires_prefix = False
        try:
            requires_prefix = await db.get_russian_commands_prefix_setting(message.chat.id)
        except Exception as e:
            logger.debug(f"Ошибка при получении настройки префикса: {e}")
        
        if requires_prefix:
            # Если префикс обязателен, проверяем наличие "пиксель"
            if text.lower().startswith("пиксель"):
                text = text[7:].strip()
            else:
                # Префикс обязателен, но отсутствует - не команда
                return "", ""
        
        # Получаем английский эквивалент
        normalized = get_command_alias(text)
        if not normalized:
            # Не удалось определить команду
            return "", ""
        
        command_text = text.split()[0] if text.split() else text
        return command_text, normalized
    
    def _is_moderation_command(self, normalized_command: str) -> bool:
        """Проверяет, является ли команда командой модерации"""
        return normalized_command in MODERATION_COMMANDS
    
    def _check_spam(self, chat_id: int, user_id: int, current_time: float) -> bool:
        """
        Проверяет, является ли текущее использование команды спамом
        Возвращает True, если обнаружен спам
        """
        key = (chat_id, user_id)
        
        # Получаем историю команд пользователя
        command_timestamps = self._command_history[key]
        
        # Фильтруем только команды в пределах окна спама
        window_start = current_time - SPAM_WINDOW
        recent_commands = [ts for ts in command_timestamps if ts >= window_start]
        
        # Если 3 или более команд в окне - это спам
        return len(recent_commands) >= SPAM_THRESHOLD
    
    def _activate_cooldown(self, chat_id: int, user_id: int, current_time: float):
        """Активирует кулдаун для пользователя"""
        key = (chat_id, user_id)
        cooldown_end = current_time + COOLDOWN_DURATION
        self._active_cooldowns[key] = cooldown_end
        logger.info(
            f"AutoSpamDetectionMiddleware: активирован кулдаун для пользователя {user_id} "
            f"в чате {chat_id} до {cooldown_end:.1f}"
        )
    
    def _reset_cooldown(self, chat_id: int, user_id: int, current_time: float):
        """Сбрасывает кулдаун (устанавливает новый таймер)"""
        key = (chat_id, user_id)
        cooldown_end = current_time + COOLDOWN_DURATION
        self._active_cooldowns[key] = cooldown_end
        logger.info(
            f"AutoSpamDetectionMiddleware: кулдаун сброшен для пользователя {user_id} "
            f"в чате {chat_id}, новый таймер до {cooldown_end:.1f}"
        )
    
    def _is_on_cooldown(self, chat_id: int, user_id: int, current_time: float) -> bool:
        """Проверяет, находится ли пользователь на кулдауне"""
        key = (chat_id, user_id)
        if key not in self._active_cooldowns:
            return False
        
        cooldown_end = self._active_cooldowns[key]
        if current_time >= cooldown_end:
            # Кулдаун истек
            del self._active_cooldowns[key]
            return False
        
        return True
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any]
    ) -> Any:
        """Проверка команды на спам перед обработкой"""
        
        # Проверяем, что это сообщение
        if not isinstance(event, Message):
            return await handler(event, data)
        
        message: Message = event
        
        # Проверяем только команды в группах и супергруппах
        if message.chat.type not in ['group', 'supergroup']:
            return await handler(event, data)
        
        # Выполняем периодическую очистку
        self._cleanup_old_entries()
        
        # Проверяем, что это команда (начинается с /) или русский алиас
        is_english_command = message.text and message.text.strip().startswith('/')
        is_russian_alias = False
        
        if message.text and not is_english_command:
            # Проверяем, является ли это русским алиасом
            text = message.text.strip()
            requires_prefix = await db.get_russian_commands_prefix_setting(message.chat.id)
            
            if requires_prefix:
                # Если префикс обязателен, проверяем наличие "пиксель"
                if text.lower().startswith("пиксель"):
                    text_without_prefix = text[7:].strip()
                    is_russian_alias = is_command_alias(text_without_prefix)
            else:
                # Если префикс не обязателен, проверяем с префиксом и без
                is_russian_alias = is_command_alias(text)
        
        # Если это не команда, пропускаем
        if not is_english_command and not is_russian_alias:
            return await handler(event, data)
        
        # Нормализуем команду
        original_command, normalized_command = await self._normalize_command(message)
        
        # Если не удалось определить команду, пропускаем
        if not normalized_command:
            return await handler(event, data)
        
        # Команды модерации всегда разрешены
        if self._is_moderation_command(normalized_command):
            logger.debug(
                f"AutoSpamDetectionMiddleware: команда модерации {normalized_command} "
                f"разрешена для пользователя {message.from_user.id}"
            )
            return await handler(event, data)
        
        user_id = message.from_user.id
        chat_id = message.chat.id
        current_time = time.time()
        key = (chat_id, user_id)
        
        # Добавляем команду в историю (даже если на кулдауне, для отслеживания продолжения спама)
        self._command_history[key].append(current_time)
        
        # Проверяем, находится ли пользователь на кулдауне
        if self._is_on_cooldown(chat_id, user_id, current_time):
            # Пользователь на кулдауне - блокируем команду
            cooldown_end = self._active_cooldowns[key]
            remaining = cooldown_end - current_time
            
            logger.info(
                f"AutoSpamDetectionMiddleware: команда {normalized_command} от пользователя {user_id} "
                f"в чате {chat_id} заблокирована (кулдаун, осталось {remaining:.1f} сек)"
            )
            
            # Если пользователь продолжает спамить во время кулдауна - сбрасываем таймер
            if self._check_spam(chat_id, user_id, current_time):
                self._reset_cooldown(chat_id, user_id, current_time)
                logger.warning(
                    f"AutoSpamDetectionMiddleware: спам продолжается во время кулдауна, "
                    f"таймер сброшен для пользователя {user_id} в чате {chat_id}"
                )
            
            try:
                from aiogram import Bot
                bot: Bot = data.get('bot')
                if bot:
                    # Удаляем сообщение со спам-командой
                    await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                    logger.info(f"Удалена команда {normalized_command} в чате {chat_id} (авто-обнаружение спама)")
            except Exception as e:
                logger.error(f"Ошибка при удалении команды-спама: {e}", exc_info=True)
            
            # Прерываем обработку команды
            return
        
        # Проверяем, является ли это спамом (после добавления команды в историю)
        if self._check_spam(chat_id, user_id, current_time):
            # Активируем кулдаун
            self._activate_cooldown(chat_id, user_id, current_time)
            
            logger.warning(
                f"AutoSpamDetectionMiddleware: обнаружен спам от пользователя {user_id} "
                f"в чате {chat_id}, активирован кулдаун на {COOLDOWN_DURATION} секунд"
            )
            
            try:
                from aiogram import Bot
                bot: Bot = data.get('bot')
                if bot:
                    # Удаляем сообщение со спам-командой
                    await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                    logger.info(f"Удалена команда {normalized_command} в чате {chat_id} (обнаружен спам)")
            except Exception as e:
                logger.error(f"Ошибка при удалении команды-спама: {e}", exc_info=True)
            
            # Прерываем обработку команды
            return
        
        # Команда разрешена, продолжаем обработку
        logger.debug(
            f"AutoSpamDetectionMiddleware: команда {normalized_command} разрешена "
            f"для пользователя {user_id} в чате {chat_id}"
        )
        return await handler(event, data)

