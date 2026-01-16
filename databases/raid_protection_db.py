"""
Модуль для работы с базой данных защиты от рейдов
Отдельная БД для отслеживания активности и настроек
"""
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Импортируем BASE_PATH из config, если доступен
try:
    from config import BASE_PATH
except ImportError:
    # Если файл в databases/, то корень проекта на уровень выше
    BASE_PATH = Path(__file__).parent.parent.absolute()

class RaidProtectionDatabase:
    """Класс для работы с базой данных защиты от рейдов"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(BASE_PATH / 'data' / 'raid_protection.db')
        self.db_path = db_path
        # Создаем директорию data если её нет
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        def _init_sync():
            with sqlite3.connect(self.db_path) as db:
                # Таблица настроек защиты от рейдов для каждого чата
                db.execute("""
                    CREATE TABLE IF NOT EXISTS raid_protection_settings (
                        chat_id INTEGER PRIMARY KEY,
                        enabled BOOLEAN DEFAULT 1,
                        gif_limit INTEGER DEFAULT 3,
                        gif_time_window INTEGER DEFAULT 5,
                        sticker_limit INTEGER DEFAULT 5,
                        sticker_time_window INTEGER DEFAULT 10,
                        duplicate_text_limit INTEGER DEFAULT 3,
                        duplicate_text_window INTEGER DEFAULT 30,
                        mass_join_limit INTEGER DEFAULT 10,
                        mass_join_window INTEGER DEFAULT 60,
                        similarity_threshold REAL DEFAULT 0.7,
                        notification_mode INTEGER DEFAULT 1
                    )
                """)
                
                # Добавляем колонку notification_mode если её нет
                try:
                    db.execute("ALTER TABLE raid_protection_settings ADD COLUMN notification_mode INTEGER DEFAULT 1")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку last_notification_time если её нет
                try:
                    db.execute("ALTER TABLE raid_protection_settings ADD COLUMN last_notification_time TEXT")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку auto_mute_duration если её нет
                try:
                    db.execute("ALTER TABLE raid_protection_settings ADD COLUMN auto_mute_duration INTEGER DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку auto_mute_enabled если её нет
                try:
                    db.execute("ALTER TABLE raid_protection_settings ADD COLUMN auto_mute_enabled BOOLEAN DEFAULT 1")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку mute_silent если её нет
                try:
                    db.execute("ALTER TABLE raid_protection_settings ADD COLUMN mute_silent BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку mute_duration если её нет
                try:
                    db.execute("ALTER TABLE raid_protection_settings ADD COLUMN mute_duration INTEGER DEFAULT 300")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Таблица для отслеживания недавней активности пользователей
                db.execute("""
                    CREATE TABLE IF NOT EXISTS recent_activity (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        activity_type TEXT,
                        content_hash TEXT,
                        timestamp TEXT,
                        message_id INTEGER
                    )
                """)
                
                # Таблица для отслеживания новых участников
                db.execute("""
                    CREATE TABLE IF NOT EXISTS recent_joins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        timestamp TEXT
                    )
                """)
                
                # Таблица для отслеживания удаленных сообщений (для подсчета количества атакующих пользователей)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS recent_deleted_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        incident_type TEXT,
                        timestamp TEXT
                    )
                """)
                
                # Таблица инцидентов рейдов
                db.execute("""
                    CREATE TABLE IF NOT EXISTS raid_incidents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        incident_type TEXT,
                        details TEXT,
                        message_id INTEGER,
                        timestamp TEXT,
                        action_taken TEXT
                    )
                """)
                
                # Создаем индексы для оптимизации
                db.execute("CREATE INDEX IF NOT EXISTS idx_recent_activity_chat_user ON recent_activity (chat_id, user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_recent_activity_type ON recent_activity (activity_type)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_recent_activity_timestamp ON recent_activity (timestamp)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_recent_joins_chat ON recent_joins (chat_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_recent_joins_timestamp ON recent_joins (timestamp)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_recent_deleted_chat_timestamp ON recent_deleted_messages (chat_id, timestamp)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_raid_incidents_chat ON raid_incidents (chat_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_raid_incidents_timestamp ON raid_incidents (timestamp)")
                
                db.commit()
                logger.info("База данных защиты от рейдов инициализирована")
        
        await asyncio.get_event_loop().run_in_executor(None, _init_sync)
    
    async def get_settings(self, chat_id: int) -> Dict[str, Any]:
        """Получить настройки защиты от рейдов для чата"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT enabled, gif_limit, gif_time_window, sticker_limit, sticker_time_window,
                               duplicate_text_limit, duplicate_text_window, mass_join_limit, mass_join_window,
                               similarity_threshold, notification_mode, auto_mute_duration,
                               auto_mute_enabled, mute_silent, mute_duration
                        FROM raid_protection_settings WHERE chat_id = ?
                    """, (chat_id,))
                    row = cursor.fetchone()
                    
                    if row:
                        return {
                            'enabled': bool(row[0]),
                            'gif_limit': row[1],
                            'gif_time_window': row[2],
                            'sticker_limit': row[3],
                            'sticker_time_window': row[4],
                            'duplicate_text_limit': row[5],
                            'duplicate_text_window': row[6],
                            'mass_join_limit': row[7],
                            'mass_join_window': row[8],
                            'similarity_threshold': row[9],
                            'notification_mode': row[10] if len(row) > 10 else 1,
                            'auto_mute_duration': row[11] if len(row) > 11 else 0,
                            'auto_mute_enabled': bool(row[12]) if len(row) > 12 else True,
                            'mute_silent': bool(row[13]) if len(row) > 13 else False,
                            'mute_duration': row[14] if len(row) > 14 else 300
                        }
                    else:
                        # Возвращаем настройки по умолчанию
                        from config import RAID_PROTECTION
                        return {
                            'enabled': True,
                            'gif_limit': RAID_PROTECTION['gif_limit'],
                            'gif_time_window': RAID_PROTECTION['gif_time_window'],
                            'sticker_limit': RAID_PROTECTION['sticker_limit'],
                            'sticker_time_window': RAID_PROTECTION['sticker_time_window'],
                            'duplicate_text_limit': RAID_PROTECTION['duplicate_text_limit'],
                            'duplicate_text_window': RAID_PROTECTION['duplicate_text_window'],
                            'mass_join_limit': RAID_PROTECTION['mass_join_limit'],
                            'mass_join_window': RAID_PROTECTION['mass_join_window'],
                            'similarity_threshold': RAID_PROTECTION['similarity_threshold'],
                            'notification_mode': 1,
                            'auto_mute_duration': 0,
                            'auto_mute_enabled': True,
                            'mute_silent': False,
                            'mute_duration': 300
                        }
            except Exception as e:
                logger.error(f"Ошибка при получении настроек защиты от рейдов для чата {chat_id}: {e}")
                from config import RAID_PROTECTION
                return {
                    'enabled': True,
                    'gif_limit': RAID_PROTECTION['gif_limit'],
                    'gif_time_window': RAID_PROTECTION['gif_time_window'],
                    'sticker_limit': RAID_PROTECTION['sticker_limit'],
                    'sticker_time_window': RAID_PROTECTION['sticker_time_window'],
                    'duplicate_text_limit': RAID_PROTECTION['duplicate_text_limit'],
                    'duplicate_text_window': RAID_PROTECTION['duplicate_text_window'],
                    'mass_join_limit': RAID_PROTECTION['mass_join_limit'],
                    'mass_join_window': RAID_PROTECTION['mass_join_window'],
                    'similarity_threshold': RAID_PROTECTION['similarity_threshold'],
                    'notification_mode': 1,
                    'auto_mute_duration': 0,
                    'auto_mute_enabled': True,
                    'mute_silent': False,
                    'mute_duration': 300
                }
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def update_setting(self, chat_id: int, setting_name: str, value: Any) -> bool:
        """Обновить настройку защиты от рейдов для чата"""
        def _update_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Конвертируем bool в int если нужно
                    db_value = value
                    if isinstance(value, bool):
                        db_value = 1 if value else 0
                    
                    # Проверяем, существуют ли настройки для этого чата
                    cursor = db.execute("SELECT chat_id FROM raid_protection_settings WHERE chat_id = ?", (chat_id,))
                    exists = cursor.fetchone() is not None
                    
                    if exists:
                        # Обновляем существующие настройки
                        db.execute(f"UPDATE raid_protection_settings SET {setting_name} = ? WHERE chat_id = ?", 
                                  (db_value, chat_id))
                    else:
                        # Создаем новые настройки
                        from config import RAID_PROTECTION
                        defaults = RAID_PROTECTION.copy()
                        defaults['chat_id'] = chat_id
                        defaults[setting_name] = db_value
                        
                        db.execute("""
                            INSERT INTO raid_protection_settings 
                            (chat_id, enabled, gif_limit, gif_time_window, sticker_limit, sticker_time_window,
                             duplicate_text_limit, duplicate_text_window, mass_join_limit, mass_join_window,
                             similarity_threshold, notification_mode, auto_mute_duration, auto_mute_enabled, 
                             mute_silent, mute_duration)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            chat_id, 
                            defaults.get('enabled', 1), 
                            defaults.get('gif_limit', 3), 
                            defaults.get('gif_time_window', 5),
                            defaults.get('sticker_limit', 5),
                            defaults.get('sticker_time_window', 10),
                            defaults.get('duplicate_text_limit', 3),
                            defaults.get('duplicate_text_window', 30),
                            defaults.get('mass_join_limit', 10),
                            defaults.get('mass_join_window', 60),
                            defaults.get('similarity_threshold', 0.7),
                            defaults.get('notification_mode', 1),
                            defaults.get('auto_mute_duration', 0),
                            1 if defaults.get('auto_mute_enabled', True) else 0,
                            1 if defaults.get('mute_silent', False) else 0,
                            defaults.get('mute_duration', 300)
                        ))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении настройки {setting_name} для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_sync)
    
    async def update_settings(self, chat_id: int, **kwargs) -> bool:
        """Обновить несколько настроек защиты от рейдов для чата"""
        success = True
        for setting_name, value in kwargs.items():
            result = await self.update_setting(chat_id, setting_name, value)
            if not result:
                success = False
        return success
    
    async def add_activity(self, chat_id: int, user_id: int, activity_type: str, content_hash: str = None, 
                          message_id: int = None) -> bool:
        """Добавить запись о активности пользователя"""
        def _add_activity_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO recent_activity 
                        (chat_id, user_id, activity_type, content_hash, timestamp, message_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (chat_id, user_id, activity_type, content_hash, datetime.now().isoformat(), message_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении активности: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_activity_sync)
    
    async def get_recent_activity(self, chat_id: int, user_id: int, activity_type: str, 
                                  time_window_seconds: int) -> List[Dict[str, Any]]:
        """Получить недавнюю активность пользователя определенного типа"""
        def _get_recent_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(seconds=time_window_seconds)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT id, content_hash, timestamp, message_id
                        FROM recent_activity
                        WHERE chat_id = ? AND user_id = ? AND activity_type = ? AND timestamp >= ?
                        ORDER BY timestamp DESC
                    """, (chat_id, user_id, activity_type, cutoff_time))
                    
                    rows = cursor.fetchall()
                    return [
                        {
                            'id': row[0],
                            'content_hash': row[1],
                            'timestamp': row[2],
                            'message_id': row[3]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении недавней активности: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_recent_sync)
    
    async def add_recent_join(self, chat_id: int, user_id: int, username: str = None, 
                             first_name: str = None, last_name: str = None) -> bool:
        """Добавить запись о недавнем присоединении"""
        def _add_join_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO recent_joins 
                        (chat_id, user_id, username, first_name, last_name, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (chat_id, user_id, username, first_name, last_name, datetime.now().isoformat()))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении записи о присоединении: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_join_sync)
    
    async def get_recent_joins(self, chat_id: int, time_window_seconds: int) -> List[Dict[str, Any]]:
        """Получить недавние присоединения в чате"""
        def _get_joins_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(seconds=time_window_seconds)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT id, user_id, username, first_name, last_name, timestamp
                        FROM recent_joins
                        WHERE chat_id = ? AND timestamp >= ?
                        ORDER BY timestamp DESC
                    """, (chat_id, cutoff_time))
                    
                    rows = cursor.fetchall()
                    return [
                        {
                            'id': row[0],
                            'user_id': row[1],
                            'username': row[2],
                            'first_name': row[3],
                            'last_name': row[4],
                            'timestamp': row[5]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении недавних присоединений: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_joins_sync)
    
    async def log_raid_incident(self, chat_id: int, user_id: int, incident_type: str, details: str = None,
                               message_id: int = None, action_taken: str = None) -> bool:
        """Записать инцидент рейда"""
        def _log_incident_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO raid_incidents 
                        (chat_id, user_id, incident_type, details, message_id, timestamp, action_taken)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (chat_id, user_id, incident_type, details, message_id, datetime.now().isoformat(), action_taken))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при записи инцидента рейда: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _log_incident_sync)
    
    async def cleanup_old_activity(self, days_to_keep: int = 1) -> bool:
        """Очистить старые записи активности"""
        def _cleanup_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(days=days_to_keep)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM recent_activity WHERE timestamp < ?
                    """, (cutoff_time,))
                    deleted_count = cursor.rowcount
                    db.commit()
                    if deleted_count > 0:
                        logger.info(f"Удалено {deleted_count} старых записей активности")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке старых записей активности: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def cleanup_old_joins(self, hours_to_keep: int = 2) -> bool:
        """Очистить старые записи о присоединениях"""
        def _cleanup_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(hours=hours_to_keep)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM recent_joins WHERE timestamp < ?
                    """, (cutoff_time,))
                    deleted_count = cursor.rowcount
                    db.commit()
                    if deleted_count > 0:
                        logger.info(f"Удалено {deleted_count} старых записей о присоединениях")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке старых записей о присоединениях: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def add_deleted_message(self, chat_id: int, user_id: int, incident_type: str) -> bool:
        """Добавить запись об удаленном сообщении"""
        def _add_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO recent_deleted_messages 
                        (chat_id, user_id, incident_type, timestamp)
                        VALUES (?, ?, ?, ?)
                    """, (chat_id, user_id, incident_type, datetime.now().isoformat()))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении записи об удаленном сообщении: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_sync)
    
    async def get_recent_deleted_count(self, chat_id: int, minutes: int = 1) -> int:
        """Получить количество уникальных пользователей с удаленными сообщениями за последние N минут"""
        def _get_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(minutes=minutes)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT COUNT(DISTINCT user_id)
                        FROM recent_deleted_messages
                        WHERE chat_id = ? AND timestamp >= ?
                    """, (chat_id, cutoff_time))
                    result = cursor.fetchone()
                    return result[0] if result else 0
            except Exception as e:
                logger.error(f"Ошибка при получении количества удаленных сообщений: {e}")
                return 0
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def cleanup_old_deleted_messages(self, minutes_to_keep: int = 5) -> bool:
        """Очистить старые записи об удаленных сообщениях"""
        def _cleanup_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(minutes=minutes_to_keep)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM recent_deleted_messages WHERE timestamp < ?
                    """, (cutoff_time,))
                    deleted_count = cursor.rowcount
                    db.commit()
                    if deleted_count > 0:
                        logger.debug(f"Удалено {deleted_count} старых записей об удаленных сообщениях")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке старых записей об удаленных сообщениях: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def get_last_notification_time(self, chat_id: int) -> Optional[str]:
        """Получить время последнего уведомления о рейде для чата"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT last_notification_time 
                        FROM raid_protection_settings 
                        WHERE chat_id = ?
                    """, (chat_id,))
                    result = cursor.fetchone()
                    return result[0] if result and result[0] else None
            except Exception as e:
                logger.error(f"Ошибка при получении времени последнего уведомления: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def update_last_notification_time(self, chat_id: int, timestamp: str) -> bool:
        """Обновить время последнего уведомления о рейде"""
        def _update_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем, существуют ли настройки для этого чата
                    cursor = db.execute("SELECT chat_id FROM raid_protection_settings WHERE chat_id = ?", (chat_id,))
                    exists = cursor.fetchone() is not None
                    
                    if exists:
                        # Обновляем
                        db.execute(f"UPDATE raid_protection_settings SET last_notification_time = ? WHERE chat_id = ?", 
                                  (timestamp, chat_id))
                    else:
                        # Создаем новые настройки с временем уведомления
                        from config import RAID_PROTECTION
                        defaults = RAID_PROTECTION.copy()
                        
                        db.execute("""
                            INSERT INTO raid_protection_settings 
                            (chat_id, enabled, gif_limit, gif_time_window, sticker_limit, sticker_time_window,
                             duplicate_text_limit, duplicate_text_window, mass_join_limit, mass_join_window,
                             similarity_threshold, notification_mode, last_notification_time)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            chat_id, 
                            1, 
                            3, 5, 5, 10, 3, 30, 10, 60, 0.7, 1, timestamp
                        ))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении времени последнего уведомления: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_sync)
    
    async def delete_chat_data(self, chat_id: int) -> bool:
        """Удалить все данные чата из базы защиты от рейдов"""
        def _delete_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("DELETE FROM raid_protection_settings WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM recent_activity WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM recent_joins WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM recent_deleted_messages WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM raid_incidents WHERE chat_id = ?", (chat_id,))
                    db.commit()
                    logger.info(f"Данные чата {chat_id} удалены из raid_protection_db")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении данных чата {chat_id} из raid_protection_db: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_sync)


# Глобальный экземпляр базы данных защиты от рейдов
raid_protection_db = RaidProtectionDatabase()

