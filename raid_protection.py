"""
Модуль защиты от рейдов
Реализует алгоритмы обнаружения и предотвращения рейдов
"""
import hashlib
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from difflib import SequenceMatcher
from aiogram.types import Message
from aiogram import Bot
from databases.raid_protection_db import raid_protection_db
import logging

logger = logging.getLogger(__name__)


class RaidProtection:
    """Класс для защиты от рейдов"""
    
    def __init__(self):
        self.bot: Optional[Bot] = None
    
    def set_bot(self, bot: Bot):
        """Установить бота для отправки сообщений"""
        self.bot = bot
    
    async def check_message(self, message: Message) -> Tuple[bool, str, Optional[int]]:
        """
        Проверить сообщение на признаки рейда
        
        Returns:
            Tuple[bool, str, Optional[int]]: (is_raid, raid_type, message_id_to_delete)
            - is_raid: True если обнаружен рейд
            - raid_type: тип рейда (gif_spam, sticker_spam, duplicate_text, etc.)
            - message_id_to_delete: ID сообщения для удаления
        """
        # Проверяем, включена ли защита для чата
        settings = await raid_protection_db.get_settings(message.chat.id)
        if not settings.get('enabled', True):
            return False, None, None
        
        # Проверяем тип сообщения
        if message.animation:
            return await self._check_gif_spam(message, settings)
        elif message.sticker:
            return await self._check_sticker_spam(message, settings)
        elif message.text:
            return await self._check_duplicate_text(message, settings)
        
        return False, None, None
    
    async def _check_gif_spam(self, message: Message, settings: Dict[str, Any]) -> Tuple[bool, str, Optional[int]]:
        """Проверить на спам GIF-анимаций"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        message_id = message.message_id
        
        limit = settings.get('gif_limit', 3)
        time_window = settings.get('gif_time_window', 5)
        
        # Получаем хеш GIF-файла для отслеживания повторений
        gif_hash = await self._get_gif_hash(message)
        
        # Добавляем запись о активности
        await raid_protection_db.add_activity(chat_id, user_id, 'gif', gif_hash, message_id)
        
        # Проверяем недавнюю активность
        recent_activity = await raid_protection_db.get_recent_activity(chat_id, user_id, 'gif', time_window)
        
        if len(recent_activity) >= limit:
            # Обнаружен рейд GIF-спама
            await raid_protection_db.log_raid_incident(
                chat_id, user_id, 'gif_spam',
                f"Отправлено {len(recent_activity)} GIF за {time_window} секунд",
                message_id, "delete_message"
            )
            return True, 'gif_spam', message_id
        
        return False, None, None
    
    async def _check_sticker_spam(self, message: Message, settings: Dict[str, Any]) -> Tuple[bool, str, Optional[int]]:
        """Проверить на спам стикеров"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        message_id = message.message_id
        
        limit = settings.get('sticker_limit', 5)
        time_window = settings.get('sticker_time_window', 10)
        
        # Получаем ID стикера для отслеживания
        sticker_id = message.sticker.file_unique_id if message.sticker else None
        
        # Добавляем запись о активности
        await raid_protection_db.add_activity(chat_id, user_id, 'sticker', sticker_id, message_id)
        
        # Проверяем недавнюю активность
        recent_activity = await raid_protection_db.get_recent_activity(chat_id, user_id, 'sticker', time_window)
        
        if len(recent_activity) >= limit:
            # Обнаружен рейд стикер-спама
            await raid_protection_db.log_raid_incident(
                chat_id, user_id, 'sticker_spam',
                f"Отправлено {len(recent_activity)} стикеров за {time_window} секунд",
                message_id, "delete_message"
            )
            return True, 'sticker_spam', message_id
        
        return False, None, None
    
    async def _check_duplicate_text(self, message: Message, settings: Dict[str, Any]) -> Tuple[bool, str, Optional[int]]:
        """Проверить на дублирующиеся/похожие текстовые сообщения"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        message_id = message.message_id
        
        limit = settings.get('duplicate_text_limit', 3)
        time_window = settings.get('duplicate_text_window', 30)
        similarity_threshold = settings.get('similarity_threshold', 0.7)
        
        # Нормализуем текст
        normalized_text = self._normalize_text(message.text)
        text_hash = self._hash_text(normalized_text)
        
        # Добавляем запись о активности
        await raid_protection_db.add_activity(chat_id, user_id, 'text', text_hash, message_id)
        
        # Получаем недавние текстовые сообщения
        recent_activity = await raid_protection_db.get_recent_activity(chat_id, user_id, 'text', time_window)
        
        if len(recent_activity) >= limit:
            # Проверяем похожесть текстов
            similar_count = 0
            for activity in recent_activity:
                if activity['content_hash'] == text_hash:
                    similar_count += 1
            
            # Если есть похожие сообщения, это рейд
            if similar_count >= limit:
                await raid_protection_db.log_raid_incident(
                    chat_id, user_id, 'duplicate_text',
                    f"Обнаружено {similar_count} похожих сообщений за {time_window} секунд",
                    message_id, "delete_message"
                )
                return True, 'duplicate_text', message_id
        
        return False, None, None
    
    async def check_mass_join(self, chat_id: int, settings: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Проверить на массовое присоединение участников
        
        Returns:
            Tuple[bool, List[Dict]]: (is_mass_join, recent_joins)
        """
        limit = settings.get('mass_join_limit', 10)
        time_window = settings.get('mass_join_window', 60)
        
        recent_joins = await raid_protection_db.get_recent_joins(chat_id, time_window)
        
        if len(recent_joins) >= limit:
            await raid_protection_db.log_raid_incident(
                chat_id, None, 'mass_join',
                f"Присоединилось {len(recent_joins)} участников за {time_window} секунд",
                None, "notify_owner"
            )
            return True, recent_joins
        
        return False, recent_joins
    
    def _normalize_text(self, text: str) -> str:
        """Нормализовать текст для сравнения"""
        # Приводим к нижнему регистру
        text = text.lower()
        
        # Удаляем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        
        # Удаляем знаки препинания (но сохраняем пробелы)
        text = re.sub(r'[^\w\s]', '', text)
        
        return text.strip()
    
    def _hash_text(self, text: str) -> str:
        """Получить хеш текста"""
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    async def _get_gif_hash(self, message: Message) -> str:
        """Получить хеш GIF файла"""
        if message.animation:
            # Используем file_unique_id для уникальной идентификации
            return message.animation.file_unique_id
        return ""
    
    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        """Удалить сообщение"""
        try:
            if self.bot:
                await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.info(f"Сообщение {message_id} удалено в чате {chat_id}")
                return True
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения {message_id}: {e}")
            return False
        return False
    
    async def warn_user(self, chat_id: int, user_id: int, warning_message: str) -> bool:
        """Предупредить пользователя"""
        try:
            if self.bot:
                # Отправляем предупреждение от имени бота
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ {warning_message}",
                    parse_mode=None
                )
                logger.info(f"Пользователь {user_id} получил предупреждение в чате {chat_id}")
                return True
        except Exception as e:
            logger.error(f"Ошибка при отправке предупреждения пользователю {user_id}: {e}")
            return False
        return False
    
    async def notify_owner(self, chat_id: int, raid_type: str, user_id: int = None, 
                          details: str = None, recent_joins: List[Dict[str, Any]] = None) -> bool:
        """Уведомить владельца чата о рейде"""
        try:
            if not self.bot:
                return False
            
            # Получаем владельца чата из базы данных
            from database import db
            owner_id = await db.get_chat_owner(chat_id)
            
            # Если владелец не найден в БД, пытаемся определить через Telegram API
            if not owner_id:
                try:
                    admins = await self.bot.get_chat_administrators(chat_id)
                    for admin in admins:
                        if admin.status == 'creator':
                            owner_id = admin.user.id
                            # Обновляем базу данных с правильным владельцем
                            await db.add_chat(
                                chat_id=chat_id,
                                chat_title=(await self.bot.get_chat(chat_id)).title or "Без названия",
                                owner_id=owner_id
                            )
                            break
                except Exception as e:
                    logger.warning(f"Не удалось определить владельца чата {chat_id} через API: {e}")
            
            if not owner_id:
                logger.warning(f"Не удалось найти владельца чата {chat_id} для уведомления о рейде")
                return False
            
            # Проверяем, что владелец действительно является создателем чата
            try:
                owner_member = await self.bot.get_chat_member(chat_id, owner_id)
                if owner_member.status != 'creator':
                    logger.warning(f"Пользователь {owner_id} не является создателем чата {chat_id}, уведомление не отправлено")
                    return False
            except Exception as e:
                logger.warning(f"Не удалось проверить статус владельца {owner_id} в чате {chat_id}: {e}")
                # Если не можем проверить, все равно отправляем (может быть временная проблема с API)
            
            # Формируем сообщение для владельца
            message_lines = [
                "🚨 Обнаружен рейд!",
                "",
                f"Чат: {chat_id}",
                f"Тип рейда: {self._get_raid_type_name(raid_type)}",
            ]
            
            if user_id:
                message_lines.append(f"Пользователь: {user_id}")
            
            if details:
                message_lines.append(f"Детали: {details}")
            
            if recent_joins:
                message_lines.append("")
                message_lines.append("Участники рейда:")
                for join in recent_joins[:20]:  # Показываем первых 20
                    username = join.get('username', 'N/A')
                    first_name = join.get('first_name', 'N/A')
                    user_id_join = join.get('user_id', 'N/A')
                    message_lines.append(f"  - {first_name} (@{username}) [{user_id_join}]")
                
                if len(recent_joins) > 20:
                    message_lines.append(f"  ... и еще {len(recent_joins) - 20}")
            
            message_text = "\n".join(message_lines)
            
            await self.bot.send_message(
                chat_id=owner_id,
                text=message_text,
                parse_mode=None
            )
            
            logger.info(f"Владелец чата {owner_id} уведомлен о рейде типа {raid_type} в чате {chat_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при уведомлении владельца о рейде: {e}")
            return False
    
    def _get_raid_type_name(self, raid_type: str) -> str:
        """Получить читаемое название типа рейда"""
        names = {
            'gif_spam': 'GIF спам',
            'sticker_spam': 'Стикер спам',
            'duplicate_text': 'Дублирующиеся сообщения',
            'mass_join': 'Массовое присоединение'
        }
        return names.get(raid_type, raid_type)


# Глобальный экземпляр защиты от рейдов
raid_protection = RaidProtection()

