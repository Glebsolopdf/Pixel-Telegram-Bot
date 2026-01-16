"""
Модуль для работы с базой данных модерации (наказания)
Отдельная БД для изоляции данных модерации от основной статистики
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

class ModerationDatabase:
    """Класс для работы с базой данных модерации"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(BASE_PATH / 'data' / 'moderation.db')
        self.db_path = db_path
        # Создаем директорию data если её нет
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        def _init_sync():
            with sqlite3.connect(self.db_path) as db:
                # Таблица истории наказаний
                db.execute("""
                    CREATE TABLE IF NOT EXISTS punishments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        moderator_id INTEGER,
                        punishment_type TEXT,
                        reason TEXT,
                        duration_seconds INTEGER,
                        punishment_date TEXT,
                        expiry_date TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        user_username TEXT,
                        user_first_name TEXT,
                        user_last_name TEXT,
                        moderator_username TEXT,
                        moderator_first_name TEXT,
                        moderator_last_name TEXT
                    )
                """)
                
                # Таблица варнов
                db.execute("""
                    CREATE TABLE IF NOT EXISTS warns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        moderator_id INTEGER,
                        reason TEXT,
                        warn_date TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        user_username TEXT,
                        user_first_name TEXT,
                        user_last_name TEXT,
                        moderator_username TEXT,
                        moderator_first_name TEXT,
                        moderator_last_name TEXT
                    )
                """)
                
                # Таблица настроек варнов
                db.execute("""
                    CREATE TABLE IF NOT EXISTS warn_settings (
                        chat_id INTEGER PRIMARY KEY,
                        warn_limit INTEGER DEFAULT 3,
                        punishment_type TEXT DEFAULT 'kick',
                        mute_duration INTEGER DEFAULT NULL
                    )
                """)
                
                # Миграция: добавляем поле reason в таблицу warns, если его нет
                try:
                    db.execute("ALTER TABLE warns ADD COLUMN reason TEXT")
                    logger.info("Добавлено поле reason в таблицу warns")
                except sqlite3.OperationalError:
                    # Поле уже существует
                    pass
                
                # Миграция: добавляем поле channel_id в таблицу punishments, если его нет
                try:
                    db.execute("ALTER TABLE punishments ADD COLUMN channel_id INTEGER")
                    logger.info("Добавлено поле channel_id в таблицу punishments")
                except sqlite3.OperationalError:
                    # Поле уже существует
                    pass
                
                # Таблица для хранения ручных банов каналов модераторами
                db.execute("""
                    CREATE TABLE IF NOT EXISTS banned_channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        channel_id INTEGER,
                        channel_username TEXT,
                        channel_title TEXT,
                        moderator_id INTEGER,
                        moderator_username TEXT,
                        moderator_first_name TEXT,
                        moderator_last_name TEXT,
                        reason TEXT,
                        ban_date TEXT,
                        is_active BOOLEAN DEFAULT 1
                    )
                """)
                
                # Создаем индексы для оптимизации
                db.execute("CREATE INDEX IF NOT EXISTS idx_punishments_chat_user ON punishments (chat_id, user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_punishments_chat_channel ON punishments (chat_id, channel_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_punishments_chat_type ON punishments (chat_id, punishment_type)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_punishments_active ON punishments (is_active)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_punishments_expiry ON punishments (expiry_date)")
                
                # Индексы для варнов
                db.execute("CREATE INDEX IF NOT EXISTS idx_warns_chat_user ON warns (chat_id, user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_warns_active ON warns (is_active)")
                
                # Индексы для banned_channels
                db.execute("CREATE INDEX IF NOT EXISTS idx_banned_channels_chat_channel ON banned_channels (chat_id, channel_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_banned_channels_active ON banned_channels (is_active)")
                
                db.commit()
                logger.info("База данных модерации инициализирована")
        
        await asyncio.get_event_loop().run_in_executor(None, _init_sync)
    
    async def add_punishment(self, chat_id: int, user_id: int = None, moderator_id: int = None, 
                           punishment_type: str = None, reason: str = None, 
                           duration_seconds: int = None, expiry_date: str = None,
                           user_username: str = None, user_first_name: str = None, user_last_name: str = None,
                           moderator_username: str = None, moderator_first_name: str = None, moderator_last_name: str = None,
                           channel_id: int = None) -> bool:
        """Добавление записи о наказании (для пользователей или каналов)"""
        def _add_punishment_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем наличие channel_id в схеме
                    cursor_columns = db.execute("PRAGMA table_info(punishments)")
                    columns = [col[1] for col in cursor_columns.fetchall()]
                    has_channel_id = 'channel_id' in columns
                    
                    if has_channel_id:
                        db.execute("""
                            INSERT INTO punishments 
                            (chat_id, user_id, channel_id, moderator_id, punishment_type, reason, 
                             duration_seconds, punishment_date, expiry_date,
                             user_username, user_first_name, user_last_name,
                             moderator_username, moderator_first_name, moderator_last_name)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (chat_id, user_id, channel_id, moderator_id, punishment_type, reason,
                              duration_seconds, datetime.now().isoformat(), expiry_date,
                              user_username, user_first_name, user_last_name,
                              moderator_username, moderator_first_name, moderator_last_name))
                    else:
                        # Fallback для старых схем без channel_id
                        db.execute("""
                            INSERT INTO punishments 
                            (chat_id, user_id, moderator_id, punishment_type, reason, 
                             duration_seconds, punishment_date, expiry_date,
                             user_username, user_first_name, user_last_name,
                             moderator_username, moderator_first_name, moderator_last_name)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (chat_id, user_id if user_id else channel_id, moderator_id, punishment_type, reason,
                              duration_seconds, datetime.now().isoformat(), expiry_date,
                              user_username, user_first_name, user_last_name,
                              moderator_username, moderator_first_name, moderator_last_name))
                    db.commit()
                    return True
            except Exception as e:
                target = f"канала {channel_id}" if channel_id else f"пользователя {user_id}"
                logger.error(f"Ошибка при добавлении наказания для {target} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_punishment_sync)
    
    async def get_user_punishments(self, chat_id: int, user_id: int, active_only: bool = True) -> List[Dict[str, Any]]:
        """Получение истории наказаний пользователя"""
        def _get_user_punishments_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    query = """
                        SELECT id, punishment_type, reason, duration_seconds, 
                               punishment_date, expiry_date, is_active,
                               moderator_username, moderator_first_name, moderator_last_name
                        FROM punishments
                        WHERE chat_id = ? AND user_id = ?
                    """
                    if active_only:
                        query += " AND is_active = 1"
                    query += " ORDER BY punishment_date DESC"
                    
                    cursor = db.execute(query, (chat_id, user_id))
                    rows = cursor.fetchall()
                    return [
                        {
                            'id': row[0],
                            'punishment_type': row[1],
                            'reason': row[2],
                            'duration_seconds': row[3],
                            'punishment_date': row[4],
                            'expiry_date': row[5],
                            'is_active': bool(row[6]),
                            'moderator_username': row[7],
                            'moderator_first_name': row[8],
                            'moderator_last_name': row[9]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении наказаний пользователя {user_id} в чате {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_punishments_sync)
    
    async def deactivate_punishment(self, punishment_id: int) -> bool:
        """Деактивация наказания (например, при размуте). Возвращает True только если наказание было активно и успешно деактивировано."""
        def _deactivate_punishment_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Атомарно деактивируем только если наказание еще активно (защита от дублирования)
                    cursor = db.execute("""
                        UPDATE punishments SET is_active = 0 
                        WHERE id = ? AND is_active = 1
                    """, (punishment_id,))
                    db.commit()
                    # Возвращаем True только если была затронута хотя бы одна строка
                    return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Ошибка при деактивации наказания {punishment_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _deactivate_punishment_sync)
    
    async def get_active_punishments(self, chat_id: int, punishment_type: str = None) -> List[Dict[str, Any]]:
        """Получение активных наказаний в чате"""
        def _get_active_punishments_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем наличие channel_id в схеме
                    cursor_columns = db.execute("PRAGMA table_info(punishments)")
                    columns = [col[1] for col in cursor_columns.fetchall()]
                    has_channel_id = 'channel_id' in columns
                    
                    if has_channel_id:
                        query = """
                            SELECT id, user_id, channel_id, punishment_type, reason, 
                                   duration_seconds, punishment_date, expiry_date,
                                   user_username, user_first_name, user_last_name
                            FROM punishments
                            WHERE chat_id = ? AND is_active = 1
                        """
                    else:
                        query = """
                            SELECT id, user_id, NULL as channel_id, punishment_type, reason, 
                                   duration_seconds, punishment_date, expiry_date,
                                   user_username, user_first_name, user_last_name
                            FROM punishments
                            WHERE chat_id = ? AND is_active = 1
                        """
                    
                    params = [chat_id]
                    
                    if punishment_type:
                        query += " AND punishment_type = ?"
                        params.append(punishment_type)
                    
                    query += " ORDER BY punishment_date DESC"
                    
                    cursor = db.execute(query, params)
                    rows = cursor.fetchall()
                    return [
                        {
                            'id': row[0],
                            'user_id': row[1],
                            'channel_id': row[2] if has_channel_id else None,
                            'punishment_type': row[3],
                            'reason': row[4],
                            'duration_seconds': row[5],
                            'punishment_date': row[6],
                            'expiry_date': row[7],
                            'user_username': row[8],
                            'user_first_name': row[9],
                            'user_last_name': row[10]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении активных наказаний в чате {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_active_punishments_sync)
    
    async def cleanup_expired_punishments(self) -> int:
        """Очистка истекших наказаний"""
        def _cleanup_expired_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        UPDATE punishments 
                        SET is_active = 0 
                        WHERE is_active = 1 
                        AND expiry_date IS NOT NULL 
                        AND expiry_date < datetime('now')
                    """)
                    db.commit()
                    return cursor.rowcount
            except Exception as e:
                logger.error(f"Ошибка при очистке истекших наказаний: {e}")
                return 0
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_expired_sync)
    
    async def cleanup_old_records(self, days_to_keep: int = 7) -> bool:
        """Автоматическая очистка старых записей (по умолчанию старше 7 дней)"""
        def _cleanup_old_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Вычисляем дату, старше которой удаляем записи
                    cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).isoformat()
                    logger.info(f"🧹 Начало очистки записей модерации старше {cutoff_date} (сейчас {datetime.now().isoformat()})")
                    
                    # Сначала подсчитываем, сколько записей будет удалено
                    cursor = db.execute("""
                        SELECT COUNT(*) FROM punishments 
                        WHERE punishment_date < ?
                    """, (cutoff_date,))
                    old_punishments_count = cursor.fetchone()[0]
                    
                    cursor = db.execute("""
                        SELECT COUNT(*) FROM warns 
                        WHERE warn_date < ?
                    """, (cutoff_date,))
                    old_warns_count = cursor.fetchone()[0]
                    
                    logger.info(f"🧹 Найдено {old_punishments_count} старых наказаний и {old_warns_count} старых варнов для удаления")
                    
                    # Если нет старых записей, не делаем ничего
                    if old_punishments_count == 0 and old_warns_count == 0:
                        logger.info("Нет старых записей для очистки")
                        return True
                    
                    # Удаляем все старые наказания (и активные, и завершенные)
                    cursor = db.execute("""
                        DELETE FROM punishments 
                        WHERE punishment_date < ?
                    """, (cutoff_date,))
                    deleted_punishments = cursor.rowcount
                    
                    # Удаляем все старые варны (и активные, и завершенные)
                    cursor = db.execute("""
                        DELETE FROM warns 
                        WHERE warn_date < ?
                    """, (cutoff_date,))
                    deleted_warns = cursor.rowcount
                    
                    db.commit()
                    
                    # Логируем результат
                    total_deleted = deleted_punishments + deleted_warns
                    if total_deleted > 0:
                        logger.info(f"🧹 Автоматическая очистка: удалено {deleted_punishments} наказаний и {deleted_warns} варнов (старше {days_to_keep} дней)")
                    else:
                        logger.warning(f"Автоматическая очистка: ожидалось удаление {old_punishments_count + old_warns_count} записей, но удалено {total_deleted}")
                    
                    return True
            except Exception as e:
                logger.error(f"Ошибка при автоматической очистке старых записей: {e}", exc_info=True)
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_old_sync)
    
    async def get_bans_last_days(self, days: int = 3) -> List[Dict[str, Any]]:
        """Получить список банов за последние N дней по всем чатам."""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute(
                        """
                        SELECT chat_id, user_id, reason, punishment_date, expiry_date, user_username, user_first_name, user_last_name
                        FROM punishments
                        WHERE punishment_type = 'ban' AND punishment_date >= datetime('now', ?)
                        ORDER BY punishment_date DESC
                        """,
                        (f'-{days} days',)
                    )
                    rows = cursor.fetchall()
                    return [
                        {
                            'chat_id': r[0],
                            'user_id': r[1],
                            'reason': r[2],
                            'punishment_date': r[3],
                            'expiry_date': r[4],
                            'user_username': r[5],
                            'user_first_name': r[6],
                            'user_last_name': r[7],
                        }
                        for r in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении банов за {days} дней: {e}")
                return []
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    # ========== МЕТОДЫ ДЛЯ РАБОТЫ С ВАРНАМИ ==========
    
    async def add_warn(self, chat_id: int, user_id: int, moderator_id: int, reason: str = None,
                      user_username: str = None, user_first_name: str = None, user_last_name: str = None,
                      moderator_username: str = None, moderator_first_name: str = None, moderator_last_name: str = None) -> bool:
        """Добавление варна пользователю"""
        def _add_warn_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO warns 
                        (chat_id, user_id, moderator_id, reason, warn_date,
                         user_username, user_first_name, user_last_name,
                         moderator_username, moderator_first_name, moderator_last_name)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (chat_id, user_id, moderator_id, reason, datetime.now().isoformat(),
                          user_username, user_first_name, user_last_name,
                          moderator_username, moderator_first_name, moderator_last_name))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении варна для пользователя {user_id} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_warn_sync)
    
    async def remove_warn(self, chat_id: int, user_id: int) -> bool:
        """Удаление последнего варна пользователя"""
        def _remove_warn_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Находим последний активный варн
                    cursor = db.execute("""
                        SELECT id FROM warns 
                        WHERE chat_id = ? AND user_id = ? AND is_active = 1
                        ORDER BY warn_date DESC LIMIT 1
                    """, (chat_id, user_id))
                    row = cursor.fetchone()
                    
                    if row:
                        # Деактивируем варн
                        db.execute("""
                            UPDATE warns SET is_active = 0 
                            WHERE id = ?
                        """, (row[0],))
                        db.commit()
                        return True
                    return False
            except Exception as e:
                logger.error(f"Ошибка при удалении варна для пользователя {user_id} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _remove_warn_sync)
    
    async def get_user_warns(self, chat_id: int, user_id: int, active_only: bool = True) -> List[Dict[str, Any]]:
        """Получение истории варнов пользователя"""
        def _get_user_warns_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    query = """
                        SELECT id, reason, warn_date, is_active,
                               moderator_username, moderator_first_name, moderator_last_name
                        FROM warns
                        WHERE chat_id = ? AND user_id = ?
                    """
                    if active_only:
                        query += " AND is_active = 1"
                    query += " ORDER BY warn_date DESC"
                    
                    cursor = db.execute(query, (chat_id, user_id))
                    rows = cursor.fetchall()
                    return [
                        {
                            'id': row[0],
                            'reason': row[1],
                            'warn_date': row[2],
                            'is_active': bool(row[3]),
                            'moderator_username': row[4],
                            'moderator_first_name': row[5],
                            'moderator_last_name': row[6]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении варнов пользователя {user_id} в чате {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_warns_sync)
    
    async def get_user_warn_count(self, chat_id: int, user_id: int) -> int:
        """Получение количества активных варнов пользователя"""
        def _get_user_warn_count_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT COUNT(*) FROM warns 
                        WHERE chat_id = ? AND user_id = ? AND is_active = 1
                    """, (chat_id, user_id))
                    return cursor.fetchone()[0]
            except Exception as e:
                logger.error(f"Ошибка при получении количества варнов пользователя {user_id} в чате {chat_id}: {e}")
                return 0
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_warn_count_sync)
    
    async def clear_user_warns(self, chat_id: int, user_id: int) -> bool:
        """Очистка всех варнов пользователя"""
        def _clear_user_warns_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE warns SET is_active = 0 
                        WHERE chat_id = ? AND user_id = ? AND is_active = 1
                    """, (chat_id, user_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке варнов пользователя {user_id} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _clear_user_warns_sync)
    
    async def get_warn_settings(self, chat_id: int) -> Dict[str, Any]:
        """Получение настроек варнов для чата"""
        def _get_warn_settings_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT warn_limit, punishment_type, mute_duration
                        FROM warn_settings WHERE chat_id = ?
                    """, (chat_id,))
                    row = cursor.fetchone()
                    
                    if row:
                        return {
                            'warn_limit': row[0],
                            'punishment_type': row[1],
                            'mute_duration': row[2]
                        }
                    else:
                        # Возвращаем настройки по умолчанию
                        return {
                            'warn_limit': 3,
                            'punishment_type': 'kick',
                            'mute_duration': None
                        }
            except Exception as e:
                logger.error(f"Ошибка при получении настроек варнов для чата {chat_id}: {e}")
                return {
                    'warn_limit': 3,
                    'punishment_type': 'kick',
                    'mute_duration': None
                }
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_warn_settings_sync)
    
    async def update_warn_settings(self, chat_id: int, warn_limit: int = None, 
                                 punishment_type: str = None, mute_duration: int = None) -> bool:
        """Обновление настроек варнов для чата"""
        def _update_warn_settings_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем, есть ли уже настройки для этого чата
                    cursor = db.execute("SELECT chat_id FROM warn_settings WHERE chat_id = ?", (chat_id,))
                    exists = cursor.fetchone() is not None
                    
                    if exists:
                        # Обновляем существующие настройки
                        update_fields = []
                        params = []
                        
                        if warn_limit is not None:
                            update_fields.append("warn_limit = ?")
                            params.append(warn_limit)
                        if punishment_type is not None:
                            update_fields.append("punishment_type = ?")
                            params.append(punishment_type)
                        if mute_duration is not None:
                            update_fields.append("mute_duration = ?")
                            params.append(mute_duration)
                        
                        if update_fields:
                            params.append(chat_id)
                            query = f"UPDATE warn_settings SET {', '.join(update_fields)} WHERE chat_id = ?"
                            db.execute(query, params)
                    else:
                        # Создаем новые настройки
                        db.execute("""
                            INSERT INTO warn_settings (chat_id, warn_limit, punishment_type, mute_duration)
                            VALUES (?, ?, ?, ?)
                        """, (chat_id, 
                              warn_limit if warn_limit is not None else 3,
                              punishment_type if punishment_type is not None else 'kick',
                              mute_duration))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении настроек варнов для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_warn_settings_sync)
    
    async def delete_chat_data(self, chat_id: int) -> bool:
        """Удалить все данные чата из базы модерации"""
        def _delete_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("DELETE FROM punishments WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM warns WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM warn_settings WHERE chat_id = ?", (chat_id,))
                    db.execute("DELETE FROM banned_channels WHERE chat_id = ?", (chat_id,))
                    db.commit()
                    logger.info(f"Данные чата {chat_id} удалены из moderation_db")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении данных чата {chat_id} из moderation_db: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_sync)
    
    # ========== МЕТОДЫ ДЛЯ РАБОТЫ С БАНАМИ КАНАЛОВ ==========
    
    async def add_channel_ban(self, chat_id: int, channel_id: int, moderator_id: int,
                             channel_username: str = None, channel_title: str = None,
                             reason: str = None,
                             moderator_username: str = None, moderator_first_name: str = None, moderator_last_name: str = None) -> bool:
        """Добавление ручного бана канала модератором (сохраняется в banned_channels и punishments)"""
        def _add_channel_ban_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Добавляем в таблицу banned_channels
                    db.execute("""
                        INSERT INTO banned_channels 
                        (chat_id, channel_id, channel_username, channel_title, moderator_id,
                         moderator_username, moderator_first_name, moderator_last_name,
                         reason, ban_date, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """, (chat_id, channel_id, channel_username, channel_title, moderator_id,
                          moderator_username, moderator_first_name, moderator_last_name,
                          reason, datetime.now().isoformat()))
                    
                    # Также добавляем в punishments для истории
                    cursor_columns = db.execute("PRAGMA table_info(punishments)")
                    columns = [col[1] for col in cursor_columns.fetchall()]
                    has_channel_id = 'channel_id' in columns
                    
                    if has_channel_id:
                        db.execute("""
                            INSERT INTO punishments 
                            (chat_id, user_id, channel_id, moderator_id, punishment_type, reason,
                             duration_seconds, punishment_date, expiry_date,
                             user_username, user_first_name, user_last_name,
                             moderator_username, moderator_first_name, moderator_last_name)
                            VALUES (?, NULL, ?, ?, 'ban', ?, NULL, ?, NULL,
                                    ?, ?, ?,
                                    ?, ?, ?)
                        """, (chat_id, channel_id, moderator_id, reason,
                              datetime.now().isoformat(),
                              channel_username, channel_title, None,
                              moderator_username, moderator_first_name, moderator_last_name))
                    else:
                        # Fallback для старых схем
                        db.execute("""
                            INSERT INTO punishments 
                            (chat_id, user_id, moderator_id, punishment_type, reason,
                             duration_seconds, punishment_date, expiry_date,
                             user_username, user_first_name, user_last_name,
                             moderator_username, moderator_first_name, moderator_last_name)
                            VALUES (?, ?, ?, 'ban', ?, NULL, ?, NULL,
                                    ?, ?, ?,
                                    ?, ?, ?)
                        """, (chat_id, channel_id, moderator_id, reason,
                              datetime.now().isoformat(),
                              channel_username, channel_title, None,
                              moderator_username, moderator_first_name, moderator_last_name))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении бана канала {channel_id} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_channel_ban_sync)
    
    async def is_channel_banned(self, chat_id: int, channel_id: int) -> bool:
        """Проверить, забанен ли канал вручную модератором (проверяет только banned_channels)"""
        def _is_channel_banned_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT COUNT(*) FROM banned_channels
                        WHERE chat_id = ? AND channel_id = ? AND is_active = 1
                    """, (chat_id, channel_id))
                    return cursor.fetchone()[0] > 0
            except Exception as e:
                logger.error(f"Ошибка при проверке бана канала {channel_id} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _is_channel_banned_sync)
    
    async def get_banned_channels(self, chat_id: int) -> List[Dict[str, Any]]:
        """Получить список забаненных каналов в чате"""
        def _get_banned_channels_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT id, channel_id, channel_username, channel_title,
                               moderator_username, moderator_first_name, moderator_last_name,
                               reason, ban_date
                        FROM banned_channels
                        WHERE chat_id = ? AND is_active = 1
                        ORDER BY ban_date DESC
                    """, (chat_id,))
                    rows = cursor.fetchall()
                    return [
                        {
                            'id': row[0],
                            'channel_id': row[1],
                            'channel_username': row[2],
                            'channel_title': row[3],
                            'moderator_username': row[4],
                            'moderator_first_name': row[5],
                            'moderator_last_name': row[6],
                            'reason': row[7],
                            'ban_date': row[8]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении списка забаненных каналов в чате {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_banned_channels_sync)
    
    async def remove_channel_ban(self, chat_id: int, channel_id: int) -> bool:
        """Удалить ручной бан канала (деактивировать в banned_channels)"""
        def _remove_channel_ban_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        UPDATE banned_channels SET is_active = 0
                        WHERE chat_id = ? AND channel_id = ? AND is_active = 1
                    """, (chat_id, channel_id))
                    db.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Ошибка при удалении бана канала {channel_id} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _remove_channel_ban_sync)
    
    async def get_punishments_paginated(self, chat_id: int, page: int = 1, per_page: int = 10, 
                                       punishment_type: str = None, active_only: Optional[bool] = None) -> Dict[str, Any]:
        """
        Получение наказаний с пагинацией (объединяет punishments и warns)
        
        Args:
            chat_id: ID чата
            page: Номер страницы (начинается с 1)
            per_page: Количество записей на странице
            punishment_type: Тип наказания ('ban', 'mute', 'kick', 'warn') или None для всех
            active_only: True - только активные, False - только завершенные, None - все
        
        Returns:
            dict с ключами: 'punishments' (список), 'total_count' (int), 'total_pages' (int), 'page' (int)
        """
        def _get_paginated_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Выполняем запросы отдельно и объединяем результаты
                    all_punishments = []
                    
                    # Определяем, какие таблицы использовать
                    use_punishments = True
                    use_warns = True
                    
                    if punishment_type:
                        if punishment_type == 'warn':
                            use_punishments = False
                        else:
                            use_warns = False
                    
                    # Запрос для punishments
                    if use_punishments:
                        punishments_where = ["chat_id = ?"]
                        params = [chat_id]
                        
                        if punishment_type:
                            punishments_where.append("punishment_type = ?")
                            params.append(punishment_type)
                        
                        if active_only is not None:
                            punishments_where.append("is_active = ?")
                            params.append(1 if active_only else 0)
                        
                        where_clause = " AND ".join(punishments_where)
                        punishments_query = (
                            "SELECT id, user_id, punishment_type, reason, duration_seconds, "
                            "punishment_date as date, expiry_date, is_active, "
                            "user_username, user_first_name, user_last_name, "
                            "moderator_id, moderator_username, moderator_first_name, moderator_last_name, "
                            "'punishment' as source_table "
                            "FROM punishments WHERE " + where_clause
                        )
                        
                        cursor = db.execute(punishments_query, params)
                        rows = cursor.fetchall()
                        for row in rows:
                            all_punishments.append({
                                'id': row[0],
                                'user_id': row[1],
                                'punishment_type': row[2],
                                'reason': row[3],
                                'duration_seconds': row[4],
                                'date': row[5],
                                'expiry_date': row[6],
                                'is_active': bool(row[7]),
                                'user_username': row[8],
                                'user_first_name': row[9],
                                'user_last_name': row[10],
                                'moderator_id': row[11],
                                'moderator_username': row[12],
                                'moderator_first_name': row[13],
                                'moderator_last_name': row[14],
                                'source_table': row[15]
                            })
                    
                    # Запрос для warns
                    if use_warns:
                        warns_where = ["chat_id = ?"]
                        warn_params = [chat_id]
                        
                        if active_only is not None:
                            warns_where.append("is_active = ?")
                            warn_params.append(1 if active_only else 0)
                        
                        where_clause = " AND ".join(warns_where)
                        warns_query = (
                            "SELECT id, user_id, 'warn' as punishment_type, reason, NULL as duration_seconds, "
                            "warn_date as date, NULL as expiry_date, is_active, "
                            "user_username, user_first_name, user_last_name, "
                            "moderator_id, moderator_username, moderator_first_name, moderator_last_name, "
                            "'warn' as source_table "
                            "FROM warns WHERE " + where_clause
                        )
                        
                        cursor = db.execute(warns_query, warn_params)
                        rows = cursor.fetchall()
                        for row in rows:
                            all_punishments.append({
                                'id': row[0],
                                'user_id': row[1],
                                'punishment_type': row[2],
                                'reason': row[3],
                                'duration_seconds': row[4],
                                'date': row[5],
                                'expiry_date': row[6],
                                'is_active': bool(row[7]),
                                'user_username': row[8],
                                'user_first_name': row[9],
                                'user_last_name': row[10],
                                'moderator_id': row[11],
                                'moderator_username': row[12],
                                'moderator_first_name': row[13],
                                'moderator_last_name': row[14],
                                'source_table': row[15]
                            })
                    
                    # Сортируем по дате (новые сначала)
                    all_punishments.sort(key=lambda x: x.get('date', '') or '', reverse=True)
                    
                    # Подсчитываем общее количество
                    total_count = len(all_punishments)
                    
                    # Вычисляем пагинацию
                    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
                    offset = (page - 1) * per_page
                    
                    # Применяем пагинацию
                    punishments = all_punishments[offset:offset + per_page]
                    
                    return {
                        'punishments': punishments,
                        'total_count': total_count,
                        'total_pages': total_pages,
                        'page': page
                    }
            except Exception as e:
                logger.error(f"Ошибка при получении наказаний с пагинацией для чата {chat_id}: {e}")
                return {
                    'punishments': [],
                    'total_count': 0,
                    'total_pages': 1,
                    'page': 1
                }
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_paginated_sync)


# Глобальный экземпляр базы данных модерации
moderation_db = ModerationDatabase()
