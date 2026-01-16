"""
Middleware для защиты от спама командами
"""
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message, TelegramObject

from databases.utilities_db import utilities_db
from databases.database import db
from utils.permissions import get_effective_rank
from utils.constants import RANK_OWNER, RANK_ADMIN, RANK_SENIOR_MOD, RANK_JUNIOR_MOD
from utils.command_aliases import get_command_alias, is_command_alias

logger = logging.getLogger(__name__)

# Константа кулдауна команд (в секундах)
COMMAND_COOLDOWN_DURATION = 10  # 10 секунд между использованием одной и той же команды


class CommandSpamMiddleware(BaseMiddleware):
    """Middleware для проверки команд на спам перед их обработкой"""
    
    def __init__(self):
        """Инициализация middleware с хранилищем кулдаунов"""
        # Хранилище кулдаунов: {(chat_id, user_id, command_text): last_used_timestamp}
        self._command_cooldowns: Dict[Tuple[int, int, str], float] = {}
        # Время последней очистки
        self._last_cleanup_time = time.time()
        # Интервал очистки старых записей (каждые 5 минут)
        self._cleanup_interval = 300
    
    def _cleanup_old_cooldowns(self):
        """Очистка старых записей кулдаунов для предотвращения утечек памяти"""
        current_time = time.time()
        
        # Проверяем, нужно ли выполнять очистку
        if current_time - self._last_cleanup_time < self._cleanup_interval:
            return
        
        # Удаляем записи, которые старше чем кулдаун + небольшой запас (30 секунд)
        cutoff_time = current_time - (COMMAND_COOLDOWN_DURATION + 30)
        keys_to_remove = [
            key for key, timestamp in self._command_cooldowns.items()
            if timestamp < cutoff_time
        ]
        
        for key in keys_to_remove:
            del self._command_cooldowns[key]
        
        if keys_to_remove:
            logger.debug(f"CommandSpamMiddleware: очищено {len(keys_to_remove)} старых записей кулдаунов")
        
        self._last_cleanup_time = current_time
    
    def _check_command_cooldown(self, chat_id: int, user_id: int, command_text: str) -> tuple[bool, float]:
        """
        Проверяет, может ли пользователь использовать команду (не на кулдауне)
        Возвращает (can_use, remaining_seconds)
        """
        current_time = time.time()
        cooldown_key = (chat_id, user_id, command_text)
        
        if cooldown_key in self._command_cooldowns:
            last_used = self._command_cooldowns[cooldown_key]
            time_passed = current_time - last_used
            
            if time_passed < COMMAND_COOLDOWN_DURATION:
                remaining = COMMAND_COOLDOWN_DURATION - time_passed
                return False, remaining
        
        # Обновляем время последнего использования
        self._command_cooldowns[cooldown_key] = current_time
        return True, 0.0
    
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
        
        # Проверяем, что это команда (начинается с /) или русский алиас
        is_english_command = message.text and message.text.strip().startswith('/')
        
        # Для русских алиасов проверяем также настройку префикса
        is_russian_alias = False
        if message.text and not is_english_command:
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
        
        if not is_english_command and not is_russian_alias:
            # Но если в сообщении есть команды через entities - обнаруживаем их
            if message.text and message.entities:
                utilities_settings = await utilities_db.get_settings(message.chat.id)
                if utilities_settings.get('fake_commands_enabled', False):
                    # Ищем команды через entities (type == "bot_command")
                    for entity in message.entities:
                        if entity.type == "bot_command":
                            # Извлекаем текст команды из сообщения
                            command_text = message.text[entity.offset:entity.offset + entity.length]
                            # Записываем обнаруженную команду в БД
                            await utilities_db.add_command_detection(message.chat.id, command_text)
                            logger.debug(f"Обнаружена команда {command_text} в сообщении от пользователя {message.from_user.id} в чате {message.chat.id}")
            
            logger.debug(f"CommandSpamMiddleware: не команда, пропускаем")
            return await handler(event, data)
        
        logger.debug(f"CommandSpamMiddleware: обрабатываем команду")
        
        # Извлекаем команду из текста и нормализуем её
        if is_english_command:
            # Английская команда: извлекаем первое слово (например, "/top" -> "/top")
            command_text = message.text.split()[0] if message.text.split() else message.text.strip()
            # Нормализуем: убираем / и приводим к нижнему регистру для кулдауна
            normalized_command = command_text.lstrip('/').lower()
        else:
            # Русский алиас: получаем английский эквивалент
            text = message.text.strip()
            # Учитываем префикс "пиксель" если он есть
            if text.lower().startswith("пиксель"):
                text = text[7:].strip()
            normalized_command = get_command_alias(text)
            if not normalized_command:
                # Если не удалось определить команду, используем оригинальный текст
                normalized_command = text.split()[0].lower() if text.split() else text.lower()
            command_text = message.text.split()[0] if message.text.split() else message.text.strip()
        
        logger.debug(f"CommandSpamMiddleware: обрабатываем команду {command_text} (нормализовано: {normalized_command}) в чате {message.chat.id}")
        
        # Выполняем периодическую очистку старых записей
        self._cleanup_old_cooldowns()
        
        # Проверяем ранг пользователя - модераторы и админы (ранги 1-4) освобождаются от кулдауна
        user_id = message.from_user.id
        chat_id = message.chat.id
        user_rank = await get_effective_rank(chat_id, user_id)
        
        # Если пользователь модератор или админ (ранг <= 4), пропускаем проверку кулдауна
        if user_rank <= RANK_JUNIOR_MOD:
            logger.debug(f"CommandSpamMiddleware: пользователь {user_id} имеет ранг {user_rank}, пропускаем проверку кулдауна")
        else:
            # Проверяем кулдаун для обычных пользователей (используем нормализованную команду)
            can_use, remaining = self._check_command_cooldown(chat_id, user_id, normalized_command)
            
            if not can_use:
                logger.info(
                    f"CommandSpamMiddleware: команда {command_text} (нормализовано: {normalized_command}) "
                    f"от пользователя {user_id} в чате {chat_id} заблокирована (кулдаун, осталось {remaining:.1f} сек)"
                )
                try:
                    from aiogram import Bot
                    bot: Bot = data.get('bot')
                    if bot:
                        # Удаляем сообщение со спам-командой
                        await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                        logger.info(f"Удалена команда {command_text} в чате {chat_id} (кулдаун команды)")
                except Exception as e:
                    logger.error(f"Ошибка при удалении команды на кулдауне: {e}", exc_info=True)
                
                # Прерываем обработку команды - не выполняем её
                return
        
        # Старая система отслеживания команд (только если fake_commands_enabled включен)
        utilities_settings = await utilities_db.get_settings(message.chat.id)
        
        if utilities_settings.get('fake_commands_enabled', False):
            # СНАЧАЛА проверяем tracking команды (до записи/обновления)
            tracking = await utilities_db.get_command_tracking(message.chat.id, command_text)
            
            if tracking and tracking.get('is_active', False):
                from datetime import datetime
                # Проверяем, прошло ли менее 60 секунд с последнего использования
                last_used_time = datetime.fromisoformat(tracking['last_used_time'])
                time_since_last_use = (datetime.now() - last_used_time).total_seconds()
                
                # Если команда использовалась ранее (usage_count >= 1) и прошло менее 60 секунд - удаляем
                if tracking.get('usage_count', 0) >= 1 and time_since_last_use < 60:
                    logger.info(f"CommandSpamMiddleware: команда {command_text} считается спамом, удаляем сообщение")
                    try:
                        from aiogram import Bot
                        bot: Bot = data.get('bot')
                        if bot:
                            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
                            logger.info(f"Удалена команда {command_text} в чате {message.chat.id} (спам командами)")
                            # НЕ прерываем обработку - пусть команда обработается, просто удалим сообщение
                            # return  # Прерываем обработку команды
                        else:
                            logger.warning(f"Bot не найден в data для удаления команды {command_text}")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении команды-спама: {e}", exc_info=True)
            
            # Обнаруживаем команду в сообщении (если есть entities) и записываем в БД
            if message.entities:
                for entity in message.entities:
                    if entity.type == "bot_command":
                        detected_command = message.text[entity.offset:entity.offset + entity.length]
                        # Записываем обнаруженную команду в БД
                        await utilities_db.add_command_detection(message.chat.id, detected_command)
            
            # Также записываем команду, если её нет в entities (на случай если это команда без @bot)
            await utilities_db.add_command_detection(message.chat.id, command_text)
            
            # Обновляем счетчик использования команды ПОСЛЕ проверки
            await utilities_db.increment_command_usage(message.chat.id, command_text)
        
        # Продолжаем обработку команды (кулдаун уже проверен выше)
        logger.debug(f"CommandSpamMiddleware: передаем команду {command_text} дальше в обработчик")
        return await handler(event, data)

