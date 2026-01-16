"""
Модуль для работы с базой данных утилит
Хранение настроек защиты от эмодзи спама и спама реакциями
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

class UtilitiesDatabase:
    """Класс для работы с базой данных утилит"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(BASE_PATH / 'data' / 'utilities.db')
        self.db_path = db_path
        # Создаем директорию data если её нет
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        def _init_sync():
            with sqlite3.connect(self.db_path) as db:
                # Таблица настроек утилит для каждого чата
                db.execute("""
                    CREATE TABLE IF NOT EXISTS utilities_settings (
                        chat_id INTEGER PRIMARY KEY,
                        emoji_spam_enabled BOOLEAN DEFAULT 0,
                        emoji_spam_limit INTEGER DEFAULT 10,
                        reaction_spam_enabled BOOLEAN DEFAULT 0,
                        reaction_spam_limit INTEGER DEFAULT 5,
                        reaction_spam_window INTEGER DEFAULT 120,
                        reaction_spam_warning_enabled BOOLEAN DEFAULT 1,
                        reaction_spam_punishment TEXT DEFAULT 'kick',
                        reaction_spam_ban_duration INTEGER DEFAULT 300,
                        fake_commands_enabled BOOLEAN DEFAULT 0
                    )
                """)
                
                # Добавляем колонку fake_commands_enabled если её нет
                try:
                    db.execute("ALTER TABLE utilities_settings ADD COLUMN fake_commands_enabled BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку reaction_spam_silent если её нет
                try:
                    db.execute("ALTER TABLE utilities_settings ADD COLUMN reaction_spam_silent BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку auto_ban_channels_enabled если её нет
                try:
                    db.execute("ALTER TABLE utilities_settings ADD COLUMN auto_ban_channels_enabled BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку auto_ban_channels_duration если её нет
                try:
                    db.execute("ALTER TABLE utilities_settings ADD COLUMN auto_ban_channels_duration INTEGER DEFAULT NULL")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Таблица для отслеживания реакций пользователей
                db.execute("""
                    CREATE TABLE IF NOT EXISTS reaction_activity (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        timestamp TEXT,
                        message_id INTEGER
                    )
                """)
                
                # Таблица для отслеживания предупреждений пользователей
                db.execute("""
                    CREATE TABLE IF NOT EXISTS reaction_warnings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        timestamp TEXT
                    )
                """)
                
                # Таблица для отслеживания примененных наказаний (защита от дублирования)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS reaction_punishments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        punishment_type TEXT,
                        timestamp TEXT
                    )
                """)
                
                # Таблица для отслеживания команд в сообщениях (защита от спама командами)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS command_tracking (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        command_text TEXT,
                        first_detected_time TEXT,
                        last_used_time TEXT,
                        usage_count INTEGER DEFAULT 0,
                        is_active BOOLEAN DEFAULT 1,
                        UNIQUE(chat_id, command_text)
                    )
                """)
                
                # Создаем индексы для оптимизации
                db.execute("CREATE INDEX IF NOT EXISTS idx_reaction_activity_chat_user ON reaction_activity (chat_id, user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_reaction_activity_timestamp ON reaction_activity (timestamp)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_reaction_warnings_chat_user ON reaction_warnings (chat_id, user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_reaction_punishments_chat_user ON reaction_punishments (chat_id, user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_reaction_punishments_timestamp ON reaction_punishments (timestamp)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_command_tracking_chat_command ON command_tracking (chat_id, command_text)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_command_tracking_last_used ON command_tracking (last_used_time)")
                
                db.commit()
                logger.info("База данных утилит инициализирована")
        
        await asyncio.get_event_loop().run_in_executor(None, _init_sync)
    
    async def get_settings(self, chat_id: int) -> Dict[str, Any]:
        """Получить настройки утилит для чата"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем наличие колонок в схеме
                    cursor_columns = db.execute("PRAGMA table_info(utilities_settings)")
                    columns = [col[1] for col in cursor_columns.fetchall()]
                    has_silent = 'reaction_spam_silent' in columns
                    has_auto_ban = 'auto_ban_channels_enabled' in columns
                    has_auto_ban_duration = 'auto_ban_channels_duration' in columns
                    
                    # Формируем запрос в зависимости от наличия колонок
                    select_fields = [
                        'emoji_spam_enabled', 'emoji_spam_limit',
                        'reaction_spam_enabled', 'reaction_spam_limit',
                        'reaction_spam_window', 'reaction_spam_warning_enabled',
                        'reaction_spam_punishment', 'reaction_spam_ban_duration',
                        'fake_commands_enabled'
                    ]
                    if has_silent:
                        select_fields.append('reaction_spam_silent')
                    if has_auto_ban:
                        select_fields.append('auto_ban_channels_enabled')
                    if has_auto_ban_duration:
                        select_fields.append('auto_ban_channels_duration')
                    
                    query = f"SELECT {', '.join(select_fields)} FROM utilities_settings WHERE chat_id = ?"
                    cursor = db.execute(query, (chat_id,))
                    row = cursor.fetchone()
                    
                    if row:
                        result = {
                            'emoji_spam_enabled': bool(row[0]),
                            'emoji_spam_limit': row[1],
                            'reaction_spam_enabled': bool(row[2]),
                            'reaction_spam_limit': row[3],
                            'reaction_spam_window': row[4],
                            'reaction_spam_warning_enabled': bool(row[5]),
                            'reaction_spam_punishment': row[6],
                            'reaction_spam_ban_duration': row[7],
                            'fake_commands_enabled': bool(row[8]) if len(row) > 8 else False,
                        }
                        idx = 9
                        if has_silent:
                            result['reaction_spam_silent'] = bool(row[idx]) if len(row) > idx else False
                            idx += 1
                        if has_auto_ban:
                            result['auto_ban_channels_enabled'] = bool(row[idx]) if len(row) > idx else False
                            idx += 1
                        if has_auto_ban_duration:
                            result['auto_ban_channels_duration'] = row[idx] if len(row) > idx else None
                        return result
                    else:
                        # Возвращаем настройки по умолчанию
                        return {
                            'emoji_spam_enabled': False,
                            'emoji_spam_limit': 10,
                            'reaction_spam_enabled': False,
                            'reaction_spam_limit': 5,
                            'reaction_spam_window': 120,
                            'reaction_spam_warning_enabled': True,
                            'reaction_spam_punishment': 'kick',
                            'reaction_spam_ban_duration': 300,
                            'fake_commands_enabled': False,
                            'reaction_spam_silent': False,
                            'auto_ban_channels_enabled': False,
                            'auto_ban_channels_duration': None
                        }
            except Exception as e:
                logger.error(f"Ошибка при получении настроек утилит для чата {chat_id}: {e}")
                return {
                    'emoji_spam_enabled': False,
                    'emoji_spam_limit': 10,
                    'reaction_spam_enabled': False,
                    'reaction_spam_limit': 5,
                    'reaction_spam_window': 120,
                    'reaction_spam_warning_enabled': True,
                    'reaction_spam_punishment': 'kick',
                    'reaction_spam_ban_duration': 3600,
                    'fake_commands_enabled': False,
                    'reaction_spam_silent': False,
                    'auto_ban_channels_enabled': False,
                    'auto_ban_channels_duration': None
                }
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def update_setting(self, chat_id: int, setting_name: str, value: Any) -> bool:
        """Обновить настройку утилит для чата"""
        def _update_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Конвертируем bool в int если нужно
                    db_value = value
                    if isinstance(value, bool):
                        db_value = 1 if value else 0
                    
                    # Проверяем, существуют ли настройки для этого чата
                    cursor = db.execute("SELECT chat_id FROM utilities_settings WHERE chat_id = ?", (chat_id,))
                    exists = cursor.fetchone() is not None
                    
                    if exists:
                        # Обновляем существующие настройки
                        db.execute(f"UPDATE utilities_settings SET {setting_name} = ? WHERE chat_id = ?", 
                                  (db_value, chat_id))
                    else:
                        # Создаем новые настройки с дефолтными значениями
                        defaults = {
                            'emoji_spam_enabled': 0,
                            'emoji_spam_limit': 10,
                            'reaction_spam_enabled': 0,
                            'reaction_spam_limit': 5,
                            'reaction_spam_window': 120,
                            'reaction_spam_warning_enabled': 1,
                            'reaction_spam_punishment': 'kick',
                            'reaction_spam_ban_duration': 300,
                            'fake_commands_enabled': 0,
                            'reaction_spam_silent': 0,
                            'auto_ban_channels_enabled': 0,
                            'auto_ban_channels_duration': None
                        }
                        defaults[setting_name] = db_value
                        
                        db.execute("""
                            INSERT INTO utilities_settings 
                            (chat_id, emoji_spam_enabled, emoji_spam_limit,
                             reaction_spam_enabled, reaction_spam_limit, reaction_spam_window,
                             reaction_spam_warning_enabled, reaction_spam_punishment, reaction_spam_ban_duration,
                             fake_commands_enabled)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            chat_id,
                            defaults.get('emoji_spam_enabled', 0),
                            defaults.get('emoji_spam_limit', 10),
                            defaults.get('reaction_spam_enabled', 0),
                            defaults.get('reaction_spam_limit', 5),
                            defaults.get('reaction_spam_window', 120),
                            defaults.get('reaction_spam_warning_enabled', 1),
                            defaults.get('reaction_spam_punishment', 'kick'),
                            defaults.get('reaction_spam_ban_duration', 300),
                            defaults.get('fake_commands_enabled', 0)
                        ))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении настройки {setting_name} для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_sync)
    
    async def update_settings(self, chat_id: int, **kwargs) -> bool:
        """Обновить несколько настроек утилит для чата"""
        def _update_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем, существуют ли настройки для этого чата
                    cursor = db.execute("SELECT chat_id FROM utilities_settings WHERE chat_id = ?", (chat_id,))
                    exists = cursor.fetchone() is not None
                    
                    if not exists:
                        # Если настроек нет, создаем их с дефолтными значениями
                        defaults = {
                            'emoji_spam_enabled': 0,
                            'emoji_spam_limit': 10,
                            'reaction_spam_enabled': 0,
                            'reaction_spam_limit': 5,
                            'reaction_spam_window': 120,
                            'reaction_spam_warning_enabled': 1,
                            'reaction_spam_punishment': 'kick',
                            'reaction_spam_ban_duration': 300,
                            'fake_commands_enabled': 0,
                            'reaction_spam_silent': 0,
                            'auto_ban_channels_enabled': 0,
                            'auto_ban_channels_duration': None
                        }
                        
                        # Применяем переданные kwargs к дефолтным значениям
                        for key, value in kwargs.items():
                            if isinstance(value, bool):
                                defaults[key] = 1 if value else 0
                            else:
                                defaults[key] = value
                        
                        db.execute("""
                            INSERT INTO utilities_settings 
                            (chat_id, emoji_spam_enabled, emoji_spam_limit,
                             reaction_spam_enabled, reaction_spam_limit, reaction_spam_window,
                             reaction_spam_warning_enabled, reaction_spam_punishment, reaction_spam_ban_duration,
                             fake_commands_enabled)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            chat_id,
                            defaults.get('emoji_spam_enabled', 0),
                            defaults.get('emoji_spam_limit', 10),
                            defaults.get('reaction_spam_enabled', 0),
                            defaults.get('reaction_spam_limit', 5),
                            defaults.get('reaction_spam_window', 120),
                            defaults.get('reaction_spam_warning_enabled', 1),
                            defaults.get('reaction_spam_punishment', 'kick'),
                            defaults.get('reaction_spam_ban_duration', 300),
                            defaults.get('fake_commands_enabled', 0)
                        ))
                    else:
                        # Обновляем существующие настройки
                        update_parts = []
                        update_values = []
                        for key, value in kwargs.items():
                            update_parts.append(f"{key} = ?")
                            if isinstance(value, bool):
                                update_values.append(1 if value else 0)
                            else:
                                update_values.append(value)
                        
                        if update_parts:
                            query = f"UPDATE utilities_settings SET {', '.join(update_parts)} WHERE chat_id = ?"
                            db.execute(query, (*update_values, chat_id))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении настроек для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_sync)
    
    async def add_reaction_activity(self, chat_id: int, user_id: int, message_id: int = None) -> bool:
        """Добавить запись о реакции пользователя"""
        def _add_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO reaction_activity 
                        (chat_id, user_id, timestamp, message_id)
                        VALUES (?, ?, ?, ?)
                    """, (chat_id, user_id, datetime.now().isoformat(), message_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении активности реакции: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_sync)
    
    async def get_recent_reactions(self, chat_id: int, user_id: int, time_window_seconds: int) -> List[Dict[str, Any]]:
        """Получить недавние реакции пользователя"""
        def _get_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(seconds=time_window_seconds)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT id, timestamp, message_id
                        FROM reaction_activity
                        WHERE chat_id = ? AND user_id = ? AND timestamp >= ?
                        ORDER BY timestamp DESC
                    """, (chat_id, user_id, cutoff_time))
                    
                    rows = cursor.fetchall()
                    return [
                        {
                            'id': row[0],
                            'timestamp': row[1],
                            'message_id': row[2]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении недавних реакций: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def add_reaction_warning(self, chat_id: int, user_id: int) -> bool:
        """Добавить запись о предупреждении пользователя за спам реакциями"""
        def _add_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO reaction_warnings 
                        (chat_id, user_id, timestamp)
                        VALUES (?, ?, ?)
                    """, (chat_id, user_id, datetime.now().isoformat()))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении предупреждения: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_sync)
    
    async def has_recent_warning(self, chat_id: int, user_id: int, time_window_seconds: int = 300) -> bool:
        """Проверить, есть ли у пользователя недавнее предупреждение"""
        def _check_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(seconds=time_window_seconds)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT COUNT(*) FROM reaction_warnings
                        WHERE chat_id = ? AND user_id = ? AND timestamp >= ?
                    """, (chat_id, user_id, cutoff_time))
                    result = cursor.fetchone()
                    return result[0] > 0 if result else False
            except Exception as e:
                logger.error(f"Ошибка при проверке предупреждения: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _check_sync)
    
    async def cleanup_old_reactions(self, hours_to_keep: int = 1) -> bool:
        """Очистить старые записи о реакциях"""
        def _cleanup_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(hours=hours_to_keep)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM reaction_activity WHERE timestamp < ?
                    """, (cutoff_time,))
                    deleted_count = cursor.rowcount
                    db.commit()
                    if deleted_count > 0:
                        logger.debug(f"Удалено {deleted_count} старых записей о реакциях")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке старых записей о реакциях: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def cleanup_old_warnings(self, hours_to_keep: int = 1) -> bool:
        """Очистить старые записи о предупреждениях"""
        def _cleanup_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(hours=hours_to_keep)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM reaction_warnings WHERE timestamp < ?
                    """, (cutoff_time,))
                    deleted_count = cursor.rowcount
                    db.commit()
                    if deleted_count > 0:
                        logger.debug(f"Удалено {deleted_count} старых записей о предупреждениях")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке старых записей о предупреждениях: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def add_reaction_punishment(self, chat_id: int, user_id: int, punishment_type: str) -> bool:
        """Добавить запись о примененном наказании"""
        def _add_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO reaction_punishments 
                        (chat_id, user_id, punishment_type, timestamp)
                        VALUES (?, ?, ?, ?)
                    """, (chat_id, user_id, punishment_type, datetime.now().isoformat()))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении записи о наказании: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_sync)
    
    async def has_recent_punishment(self, chat_id: int, user_id: int, time_window_seconds: int = 60) -> bool:
        """Проверить, было ли применено наказание недавно (защита от дублирования)"""
        def _check_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(seconds=time_window_seconds)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT COUNT(*) FROM reaction_punishments
                        WHERE chat_id = ? AND user_id = ? AND timestamp >= ?
                    """, (chat_id, user_id, cutoff_time))
                    result = cursor.fetchone()
                    return result[0] > 0 if result else False
            except Exception as e:
                logger.error(f"Ошибка при проверке недавних наказаний: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _check_sync)
    
    async def cleanup_old_punishments(self, hours_to_keep: int = 1) -> bool:
        """Очистить старые записи о наказаниях"""
        def _cleanup_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(hours=hours_to_keep)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM reaction_punishments WHERE timestamp < ?
                    """, (cutoff_time,))
                    deleted_count = cursor.rowcount
                    db.commit()
                    if deleted_count > 0:
                        logger.debug(f"Удалено {deleted_count} старых записей о наказаниях")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке старых записей о наказаниях: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def add_command_detection(self, chat_id: int, command_text: str) -> bool:
        """Запомнить обнаруженную команду в сообщении"""
        def _add_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    now = datetime.now().isoformat()
                    # Используем INSERT OR REPLACE для обновления существующей записи
                    db.execute("""
                        INSERT OR REPLACE INTO command_tracking 
                        (chat_id, command_text, first_detected_time, last_used_time, usage_count, is_active)
                        VALUES (?, ?, ?, ?, 0, 1)
                    """, (chat_id, command_text, now, now))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении обнаруженной команды: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_sync)
    
    async def get_command_tracking(self, chat_id: int, command_text: str) -> Optional[Dict[str, Any]]:
        """Получить информацию об отслеживании команды"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT first_detected_time, last_used_time, usage_count, is_active
                        FROM command_tracking
                        WHERE chat_id = ? AND command_text = ?
                    """, (chat_id, command_text))
                    row = cursor.fetchone()
                    
                    if row:
                        return {
                            'first_detected_time': row[0],
                            'last_used_time': row[1],
                            'usage_count': row[2],
                            'is_active': bool(row[3])
                        }
                    return None
            except Exception as e:
                logger.error(f"Ошибка при получении информации о команде: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def increment_command_usage(self, chat_id: int, command_text: str) -> bool:
        """Увеличить счетчик использования команды и обновить время"""
        def _increment_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    now = datetime.now().isoformat()
                    # Обновляем счетчик и время последнего использования
                    db.execute("""
                        UPDATE command_tracking 
                        SET usage_count = usage_count + 1,
                            last_used_time = ?,
                            is_active = 1
                        WHERE chat_id = ? AND command_text = ?
                    """, (now, chat_id, command_text))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении использования команды: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _increment_sync)
    
    async def cleanup_expired_commands(self, seconds_threshold: int = 60) -> bool:
        """Очистить истекшие команды (не использовались более указанного времени)"""
        def _cleanup_sync():
            try:
                cutoff_time = (datetime.now() - timedelta(seconds=seconds_threshold)).isoformat()
                with sqlite3.connect(self.db_path) as db:
                    # Деактивируем команды, которые не использовались более указанного времени
                    cursor = db.execute("""
                        UPDATE command_tracking 
                        SET is_active = 0
                        WHERE is_active = 1 AND last_used_time < ?
                    """, (cutoff_time,))
                    updated_count = cursor.rowcount
                    db.commit()
                    
                    # Удаляем старые записи (старше 1 часа)
                    old_cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
                    cursor = db.execute("""
                        DELETE FROM command_tracking 
                        WHERE last_used_time < ?
                    """, (old_cutoff,))
                    deleted_count = cursor.rowcount
                    db.commit()
                    
                    if updated_count > 0 or deleted_count > 0:
                        logger.debug(f"Очищено команд: деактивировано {updated_count}, удалено {deleted_count}")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке истекших команд: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def delete_chat_data(self, chat_id: int) -> bool:
        """Удалить все данные чата из базы утилит"""
        def _delete_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("DELETE FROM utilities_settings WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM reaction_activity WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM reaction_warnings WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM reaction_punishments WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM command_tracking WHERE chat_id = ?", (chat_id,))
                    db.commit()
                    logger.info(f"Данные чата {chat_id} удалены из utilities_db")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении данных чата {chat_id} из utilities_db: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_sync)


# Глобальный экземпляр базы данных утилит
utilities_db = UtilitiesDatabase()

