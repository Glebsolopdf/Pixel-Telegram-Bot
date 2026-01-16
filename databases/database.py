"""
Модуль для работы с базой данных SQLite
"""
import sqlite3
import asyncio
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from config import DATABASE_PATH, DEBUG

logger = logging.getLogger(__name__)


def _apply_pragma_settings(db):
    """Применить настройки производительности SQLite к соединению"""
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA cache_size=-64000")  # 64MB cache
    except Exception:
        pass  # Игнорируем ошибки, если PRAGMA не поддерживается


class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._corruption_detected = False
        self._recovery_in_progress = False
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        def _init_sync():
            # Проверяем, существует ли файл базы данных
            import os
            if not os.path.exists(self.db_path):
                logger.info(f"Файл базы данных {self.db_path} не найден, создаем новую базу данных...")
            
            with sqlite3.connect(self.db_path) as db:
                # Применяем настройки производительности SQLite
                _apply_pragma_settings(db)
                db.commit()
                
                # Таблица для хранения информации о чатах
                db.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        chat_id INTEGER PRIMARY KEY,
                        chat_title TEXT,
                        owner_id INTEGER,
                        added_date TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        has_admin_rights BOOLEAN DEFAULT 0,
                        russian_commands_prefix BOOLEAN DEFAULT 0
                    )
                """)
                
                # Добавляем колонку has_admin_rights если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN has_admin_rights BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку russian_commands_prefix если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN russian_commands_prefix BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку chat_type если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN chat_type TEXT")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку member_count если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN member_count INTEGER")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку is_public если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN is_public BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку username если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN username TEXT")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку invite_link если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN invite_link TEXT")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Таблица черного списка чатов
                db.execute("""
                    CREATE TABLE IF NOT EXISTS blacklisted_chats (
                        chat_id INTEGER PRIMARY KEY,
                        reason TEXT,
                        added_at TEXT
                    )
                """)
                
                # Добавляем колонку hints_mode если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN hints_mode INTEGER DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку frozen_at если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN frozen_at TEXT")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонки для настроек топа
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN show_in_top TEXT DEFAULT 'public_only'")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN show_private_label BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN min_activity_threshold INTEGER DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку авто-принятия заявок если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN auto_accept_join_requests BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку уведомлений при авто-принятии, если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN auto_accept_notify BOOLEAN DEFAULT 0")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Добавляем колонку rules_text если её нет
                try:
                    db.execute("ALTER TABLE chats ADD COLUMN rules_text TEXT")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                # Таблица для хранения информации о пользователях
                db.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        is_bot BOOLEAN DEFAULT 0,
                        last_seen TEXT,
                        mention_ping_enabled BOOLEAN DEFAULT 1
                    )
                """)
                
                # Таблица для статистики сообщений по дням
                db.execute("""
                    CREATE TABLE IF NOT EXISTS daily_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        date TEXT,
                        message_count INTEGER DEFAULT 0,
                        FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
                    )
                """)
                
                # Таблица для статистики пользователей по дням
                db.execute("""
                    CREATE TABLE IF NOT EXISTS user_daily_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        date TEXT,
                        message_count INTEGER DEFAULT 0,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        FOREIGN KEY (chat_id) REFERENCES chats (chat_id),
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                """)
                
                # Добавляем колонку last_name если её нет
                try:
                    db.execute("ALTER TABLE user_daily_stats ADD COLUMN last_name TEXT")
                    db.commit()
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass

                # Таблица метаданных пользователя в чате (дата первого появления)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS user_chat_meta (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        first_seen TEXT,
                        UNIQUE(chat_id, user_id)
                    )
                """)
                
                # Таблица для запросов на вступление в чаты
                db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_join_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        request_date TEXT,
                        status TEXT DEFAULT 'pending',
                        invite_link TEXT,
                        admin_message_id INTEGER,
                        FOREIGN KEY (chat_id) REFERENCES chats (chat_id),
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                """)
                
                # Таблица для рангов модераторов
                db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_moderators (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        user_id INTEGER,
                        rank INTEGER,
                        assigned_by INTEGER,
                        assigned_date TEXT,
                        UNIQUE(chat_id, user_id),
                        FOREIGN KEY (chat_id) REFERENCES chats (chat_id),
                        FOREIGN KEY (user_id) REFERENCES users (user_id),
                        FOREIGN KEY (assigned_by) REFERENCES users (user_id)
                    )
                """)
                
                # Таблица для прав рангов
                db.execute("""
                    CREATE TABLE IF NOT EXISTS rank_permissions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        rank INTEGER,
                        permission_type TEXT,
                        permission_value BOOLEAN DEFAULT 1,
                        UNIQUE(chat_id, rank, permission_type),
                        FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
                    )
                """)
                
                # Таблица для настроек статистики
                db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_stat_settings (
                        chat_id INTEGER PRIMARY KEY,
                        stats_enabled BOOLEAN DEFAULT 1,
                        count_media BOOLEAN DEFAULT 1,
                        FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
                    )
                """)
                
                # Таблица для отслеживания времени последнего сообщения
                db.execute("""
                    CREATE TABLE IF NOT EXISTS user_last_message (
                        chat_id INTEGER,
                        user_id INTEGER,
                        last_message_time TEXT,
                        PRIMARY KEY (chat_id, user_id),
                        FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
                    )
                """)
                
                
                # Создаем индексы для быстрого поиска
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_daily_stats_chat_date 
                    ON daily_stats (chat_id, date)
                """)
                
                # Индексы для прав рангов
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rank_permissions_chat_rank 
                    ON rank_permissions (chat_id, rank)
                """)
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rank_permissions_chat_type 
                    ON rank_permissions (chat_id, permission_type)
                """)
                
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_user_daily_stats_chat_date 
                    ON user_daily_stats (chat_id, date)
                """)
                
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_user_daily_stats_user_date 
                    ON user_daily_stats (user_id, date)
                """)
                
                # Композитный индекс для оптимизации GROUP BY запросов в top командах
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_user_daily_stats_chat_date_user_count 
                    ON user_daily_stats (chat_id, date, user_id, message_count)
                """)
                
                # Уникальный индекс для предотвращения дубликатов (chat_id, user_id, date)
                try:
                    db.execute("""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_daily_stats_unique 
                        ON user_daily_stats (chat_id, user_id, date)
                    """)
                except sqlite3.OperationalError as e:
                    # Если индекс уже существует или есть дубликаты, пропускаем
                    # Дубликаты будут очищены при следующем запуске cleanup_duplicate_chats
                    logger.debug(f"Не удалось создать уникальный индекс user_daily_stats: {e}")

                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_user_chat_meta_chat_user
                    ON user_chat_meta (chat_id, user_id)
                """)
                
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chat_moderators_chat_user
                    ON chat_moderators (chat_id, user_id)
                """)
                
                db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chat_moderators_chat_rank
                    ON chat_moderators (chat_id, rank)
                """)
                
                
                # Убедимся, что в таблице есть колонка count_media
                cursor = db.execute("PRAGMA table_info(chat_stat_settings)")
                columns = [column[1] for column in cursor.fetchall()]
                if 'count_media' not in columns:
                    try:
                        db.execute("ALTER TABLE chat_stat_settings ADD COLUMN count_media BOOLEAN DEFAULT 1")
                        db.commit()
                    except sqlite3.OperationalError:
                        pass
                
                # Убедимся, что в таблице users есть колонка mention_ping_enabled
                cursor = db.execute("PRAGMA table_info(users)")
                user_columns = [column[1] for column in cursor.fetchall()]
                if 'mention_ping_enabled' not in user_columns:
                    try:
                        db.execute("ALTER TABLE users ADD COLUMN mention_ping_enabled BOOLEAN DEFAULT 1")
                        db.commit()
                    except sqlite3.OperationalError:
                        pass
                
                # Убедимся, что в таблице chat_stat_settings есть колонка profile_enabled
                cursor = db.execute("PRAGMA table_info(chat_stat_settings)")
                stat_columns = [column[1] for column in cursor.fetchall()]
                if 'profile_enabled' not in stat_columns:
                    try:
                        db.execute("ALTER TABLE chat_stat_settings ADD COLUMN profile_enabled BOOLEAN DEFAULT 1")
                        db.commit()
                    except sqlite3.OperationalError:
                        pass
                
                # Убедимся, что в таблице chat_stat_settings есть колонка userinfo_enabled
                cursor = db.execute("PRAGMA table_info(chat_stat_settings)")
                stat_columns = [column[1] for column in cursor.fetchall()]
                if 'userinfo_enabled' not in stat_columns:
                    try:
                        db.execute("ALTER TABLE chat_stat_settings ADD COLUMN userinfo_enabled BOOLEAN DEFAULT 1")
                        db.commit()
                    except sqlite3.OperationalError:
                        pass
                
                # Создаем настройки по умолчанию для всех чатов, у которых их еще нет
                db.execute("""
                    INSERT OR IGNORE INTO chat_stat_settings (chat_id, stats_enabled, count_media, profile_enabled, userinfo_enabled)
                    SELECT chat_id, 1, 1, 1, 1 FROM chats
                """)
                
                # Проверяем, существует ли таблица user_last_message
                cursor = db.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='user_last_message'
                """)
                if not cursor.fetchone():
                    # Таблица не существует, создаем её
                    logger.info("Создаем таблицу user_last_message...")
                    db.execute("""
                        CREATE TABLE user_last_message (
                            chat_id INTEGER,
                            user_id INTEGER,
                            last_message_time TEXT,
                            PRIMARY KEY (chat_id, user_id),
                            FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
                        )
                    """)
                    logger.info("Таблица user_last_message создана")
                
                # Убедимся, что композитный индекс существует (для существующих баз данных)
                cursor = db.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='index' AND name='idx_user_daily_stats_chat_date_user_count'
                """)
                if not cursor.fetchone():
                    logger.info("Создаем композитный индекс для оптимизации top запросов...")
                    db.execute("""
                        CREATE INDEX idx_user_daily_stats_chat_date_user_count 
                        ON user_daily_stats (chat_id, date, user_id, message_count)
                    """)
                    logger.info("Композитный индекс создан")
                
                db.commit()
                logger.info("База данных инициализирована")
        
        await asyncio.get_event_loop().run_in_executor(None, _init_sync)
    
    async def check_integrity(self) -> bool:
        """Проверка целостности базы данных"""
        def _check_integrity_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("PRAGMA integrity_check")
                    result = cursor.fetchone()
                    # Если результат "ok", база цела
                    return result and result[0] == "ok"
            except Exception as e:
                logger.error(f"Ошибка при проверке целостности базы данных: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _check_integrity_sync)
    
    async def recover_database(self) -> bool:
        """Восстановление поврежденной базы данных"""
        def _recover_sync():
            try:
                db_path = Path(self.db_path)
                if not db_path.exists():
                    logger.error(f"База данных не найдена: {self.db_path}")
                    return False
                
                # Создаем резервную копию перед восстановлением
                backup_path = db_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
                logger.info(f"Создание резервной копии: {backup_path}")
                shutil.copy2(db_path, backup_path)
                
                # Используем .recover для восстановления
                recovered_path = db_path.with_suffix(".recovered.db")
                logger.info("Начинаем восстановление базы данных...")
                
                # SQLite 3.29+ поддерживает .recover
                try:
                    with sqlite3.connect(self.db_path) as source_db:
                        with sqlite3.connect(recovered_path) as recovered_db:
                            for line in source_db.iterdump():
                                try:
                                    recovered_db.executescript(line)
                                except:
                                    pass  # Пропускаем поврежденные строки
                            recovered_db.commit()
                    
                    # Заменяем старую базу восстановленной
                    db_path.unlink()
                    recovered_path.rename(db_path)
                    logger.info("База данных успешно восстановлена")
                    return True
                except Exception as e:
                    logger.error(f"Ошибка при восстановлении через .recover: {e}")
                    # Пробуем альтернативный метод через dump
                    try:
                        with sqlite3.connect(self.db_path) as source_db:
                            dump = '\n'.join(source_db.iterdump())
                        
                        with sqlite3.connect(recovered_path) as recovered_db:
                            recovered_db.executescript(dump)
                            recovered_db.commit()
                        
                        db_path.unlink()
                        recovered_path.rename(db_path)
                        logger.info("База данных восстановлена через dump")
                        return True
                    except Exception as e2:
                        logger.error(f"Ошибка при восстановлении через dump: {e2}")
                        return False
                        
            except Exception as e:
                logger.error(f"Критическая ошибка при восстановлении базы данных: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _recover_sync)
    
    def _is_database_corrupted_error(self, error: Exception) -> bool:
        """Проверяет, является ли ошибка признаком повреждения базы данных"""
        error_str = str(error).lower()
        return any(keyword in error_str for keyword in [
            "database disk image is malformed",
            "database is locked",
            "disk i/o error",
            "corrupted",
            "malformed"
        ])
    
    async def auto_recover_if_needed(self) -> bool:
        """Автоматически восстанавливает базу данных, если обнаружено повреждение"""
        if not self._corruption_detected or self._recovery_in_progress:
            return False
        
        self._recovery_in_progress = True
        logger.warning("Запуск автоматического восстановления базы данных...")
        
        try:
            result = await self.recover_database()
            if result:
                self._corruption_detected = False
                logger.info("База данных успешно восстановлена")
            else:
                logger.error("Не удалось восстановить базу данных")
            return result
        finally:
            self._recovery_in_progress = False
    
    async def add_chat(self, chat_id: int, chat_title: str, owner_id: int) -> bool:
        """Добавление чата в базу данных"""
        def _add_chat_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT OR REPLACE INTO chats (chat_id, chat_title, owner_id, added_date, is_active)
                        VALUES (?, ?, ?, ?, 1)
                    """, (chat_id, chat_title, owner_id, datetime.now().isoformat()))
                    db.commit()
                    logger.info(f"Чат {chat_id} добавлен в базу данных")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_chat_sync)
    
    async def remove_chat(self, chat_id: int) -> bool:
        """Удаление чата из базы данных"""
        def _remove_chat_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE chats SET is_active = 0 WHERE chat_id = ?
                    """, (chat_id,))
                    db.commit()
                    logger.info(f"Чат {chat_id} удален из базы данных")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _remove_chat_sync)
    
    async def get_chat(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получение информации о чате"""
        def _get_chat_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем, какие колонки есть
                    cursor_info = db.execute("PRAGMA table_info(chats)")
                    columns = [col[1] for col in cursor_info.fetchall()]
                    has_username = "username" in columns
                    has_invite_link = "invite_link" in columns
                    
                    # Проверяем наличие колонки frozen_at
                    has_frozen_at = "frozen_at" in columns
                    
                    # Формируем SELECT с учетом доступных колонок
                    select_fields = ["chat_id", "chat_title", "owner_id", "added_date", "is_active"]
                    if has_username:
                        select_fields.append("username")
                    if has_invite_link:
                        select_fields.append("invite_link")
                    if has_frozen_at:
                        select_fields.append("frozen_at")
                    
                    query = f"""
                        SELECT {', '.join(select_fields)}
                        FROM chats WHERE chat_id = ?
                    """
                    cursor = db.execute(query, (chat_id,))
                    
                    row = cursor.fetchone()
                    if row:
                        result = {
                            'chat_id': row[0],
                            'chat_title': row[1],
                            'owner_id': row[2],
                            'added_date': row[3],
                            'is_active': bool(row[4])
                        }
                        idx = 5
                        if has_username:
                            result['username'] = row[idx]
                            idx += 1
                        if has_invite_link:
                            result['invite_link'] = row[idx] if idx < len(row) else None
                            idx += 1
                        if has_frozen_at:
                            result['frozen_at'] = row[idx] if idx < len(row) else None
                        return result
                    return None
            except Exception as e:
                logger.error(f"Ошибка при получении чата {chat_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_chat_sync)
    
    async def get_chat_owner(self, chat_id: int) -> Optional[int]:
        """Получение ID владельца чата"""
        chat = await self.get_chat(chat_id)
        return chat['owner_id'] if chat else None
    
    async def get_russian_commands_prefix_setting(self, chat_id: int) -> bool:
        """Получить настройку префикса для русских команд"""
        def _get_setting_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT russian_commands_prefix FROM chats WHERE chat_id = ?
                    """, (chat_id,))
                    result = cursor.fetchone()
                    return bool(result[0]) if result else False
            except Exception as e:
                logger.error(f"Ошибка при получении настройки префикса русских команд: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_setting_sync)
    
    async def set_russian_commands_prefix_setting(self, chat_id: int, enabled: bool) -> bool:
        """Установить настройку префикса для русских команд"""
        def _set_setting_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE chats SET russian_commands_prefix = ? WHERE chat_id = ?
                    """, (enabled, chat_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при установке настройки префикса русских команд: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _set_setting_sync)
    
    async def get_rules_text(self, chat_id: int) -> Optional[str]:
        """Получить текст правил чата"""
        def _get_rules_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT rules_text FROM chats WHERE chat_id = ?
                    """, (chat_id,))
                    result = cursor.fetchone()
                    return result[0] if result and result[0] else None
            except Exception as e:
                logger.error(f"Ошибка при получении правил чата {chat_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_rules_sync)
    
    async def set_rules_text(self, chat_id: int, rules_text: Optional[str]) -> bool:
        """Установить текст правил чата"""
        def _set_rules_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE chats SET rules_text = ? WHERE chat_id = ?
                    """, (rules_text, chat_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при установке правил чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _set_rules_sync)
    
    async def get_hints_mode(self, chat_id: int) -> int:
        """Получить режим подсказок для чата"""
        def _get_hints_mode_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT hints_mode FROM chats WHERE chat_id = ?
                    """, (chat_id,))
                    result = cursor.fetchone()
                    return int(result[0]) if result else 0
            except Exception as e:
                logger.error(f"Ошибка при получении режима подсказок: {e}")
                return 0
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_hints_mode_sync)
    
    async def set_hints_mode(self, chat_id: int, mode: int) -> bool:
        """Установить режим подсказок для чата"""
        def _set_hints_mode_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE chats SET hints_mode = ? WHERE chat_id = ?
                    """, (mode, chat_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при установке режима подсказок: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _set_hints_mode_sync)
    
    async def add_user(self, user_id: int, username: str = None, 
                      first_name: str = None, last_name: str = None, 
                      is_bot: bool = False) -> bool:
        """Добавление пользователя в базу данных"""
        def _add_user_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Сохраняем существующее значение mention_ping_enabled если пользователь уже существует
                    db.execute("""
                        INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, is_bot, last_seen, mention_ping_enabled)
                        VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT mention_ping_enabled FROM users WHERE user_id = ?), 1))
                    """, (user_id, username, first_name, last_name, is_bot, datetime.now().isoformat(), user_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении пользователя {user_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_user_sync)
    
    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение информации о пользователе"""
        def _get_user_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT user_id, username, first_name, last_name, is_bot, last_seen, mention_ping_enabled
                        FROM users WHERE user_id = ?
                    """, (user_id,))
                    row = cursor.fetchone()
                    if row:
                        return {
                            'user_id': row[0],
                            'username': row[1],
                            'first_name': row[2],
                            'last_name': row[3],
                            'is_bot': bool(row[4]),
                            'last_seen': row[5],
                            'mention_ping_enabled': bool(row[6]) if row[6] is not None else True
                        }
                    return None
            except Exception as e:
                logger.error(f"Ошибка при получении пользователя {user_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_sync)
    
    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Получение информации о пользователе по username"""
        def _get_user_by_username_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT user_id, username, first_name, last_name, is_bot, last_seen
                        FROM users WHERE username = ?
                    """, (username,))
                    row = cursor.fetchone()
                    if row:
                        return {
                            'user_id': row[0],
                            'username': row[1],
                            'first_name': row[2],
                            'last_name': row[3],
                            'is_bot': bool(row[4]),
                            'last_seen': row[5]
                        }
                    return None
            except Exception as e:
                logger.error(f"Ошибка при получении пользователя по username {username}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_by_username_sync)
    
    async def get_all_active_chats(self) -> List[Dict[str, Any]]:
        """Получение всех активных чатов"""
        def _get_all_chats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT chat_id, chat_title, owner_id, added_date
                        FROM chats WHERE is_active = 1
                        ORDER BY added_date DESC
                    """)
                    rows = cursor.fetchall()
                    return [
                        {
                            'chat_id': row[0],
                            'chat_title': row[1],
                            'owner_id': row[2],
                            'added_date': row[3]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении списка чатов: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_all_chats_sync)

    async def is_chat_blacklisted(self, chat_id: int) -> bool:
        def _get_sync():
            with sqlite3.connect(self.db_path) as db:
                cur = db.execute("SELECT 1 FROM blacklisted_chats WHERE chat_id = ?", (chat_id,))
                return cur.fetchone() is not None
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)

    async def add_chat_to_blacklist(self, chat_id: int, reason: str | None = None) -> bool:
        def _set_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute(
                        "INSERT OR REPLACE INTO blacklisted_chats (chat_id, reason, added_at) VALUES (?, ?, ?)",
                        (chat_id, reason, datetime.now().isoformat())
                    )
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении чата {chat_id} в ЧС: {e}")
                return False
        return await asyncio.get_event_loop().run_in_executor(None, _set_sync)

    async def remove_chat_from_blacklist(self, chat_id: int) -> bool:
        def _del_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("DELETE FROM blacklisted_chats WHERE chat_id = ?", (chat_id,))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении чата {chat_id} из ЧС: {e}")
                return False
        return await asyncio.get_event_loop().run_in_executor(None, _del_sync)

    async def list_blacklisted_chats(self) -> list[dict]:
        def _list_sync():
            with sqlite3.connect(self.db_path) as db:
                cur = db.execute("SELECT chat_id, reason, added_at FROM blacklisted_chats ORDER BY added_at DESC")
                rows = cur.fetchall()
                return [{"chat_id": r[0], "reason": r[1], "added_at": r[2]} for r in rows]
        return await asyncio.get_event_loop().run_in_executor(None, _list_sync)

    async def get_auto_accept_join_requests(self, chat_id: int) -> bool:
        """Получить настройку авто-принятия заявок в чат."""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        "SELECT auto_accept_join_requests FROM chats WHERE chat_id = ?",
                        (chat_id,)
                    )
                    row = cur.fetchone()
                    return bool(row[0]) if row and row[0] is not None else False
            except Exception as e:
                logger.error(f"Ошибка при получении авто-принятия заявок для чата {chat_id}: {e}")
                return False
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)

    async def set_auto_accept_join_requests(self, chat_id: int, enabled: bool) -> bool:
        """Установить настройку авто-принятия заявок в чат."""
        def _set_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute(
                        "UPDATE chats SET auto_accept_join_requests = ? WHERE chat_id = ?",
                        (1 if enabled else 0, chat_id)
                    )
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при установке авто-принятия заявок для чата {chat_id}: {e}")
                return False
        return await asyncio.get_event_loop().run_in_executor(None, _set_sync)

    async def get_auto_accept_notify(self, chat_id: int) -> bool:
        """Получить настройку уведомлений при авто-принятии заявок."""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        "SELECT auto_accept_notify FROM chats WHERE chat_id = ?",
                        (chat_id,)
                    )
                    row = cur.fetchone()
                    return bool(row[0]) if row and row[0] is not None else False
            except Exception as e:
                logger.error(f"Ошибка при получении настройки авто-уведомлений для чата {chat_id}: {e}")
                return False
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)

    async def set_auto_accept_notify(self, chat_id: int, enabled: bool) -> bool:
        """Установить настройку уведомлений при авто-принятии заявок."""
        def _set_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute(
                        "UPDATE chats SET auto_accept_notify = ? WHERE chat_id = ?",
                        (1 if enabled else 0, chat_id)
                    )
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при установке настройки авто-уведомлений для чата {chat_id}: {e}")
                return False
        return await asyncio.get_event_loop().run_in_executor(None, _set_sync)
    
    async def get_top_chat_settings(self, chat_id: int) -> Dict[str, Any]:
        """Получить настройки показа в топе для чата"""
        def _get_settings_sync():
            try:
                from config import TOP_CHATS_DEFAULTS
                import json
                
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT show_in_top, show_private_label, min_activity_threshold
                        FROM chats
                        WHERE chat_id = ?
                    """, (chat_id,))
                    row = cursor.fetchone()
                    
                    # Если настройки есть в БД, возвращаем их
                    if row and row[0] is not None:
                        return {
                            'show_in_top': row[0] or TOP_CHATS_DEFAULTS['show_in_top'],
                            'show_private_label': bool(row[1]) if row[1] is not None else TOP_CHATS_DEFAULTS['show_private_label'],
                            'min_activity_threshold': row[2] if row[2] is not None else TOP_CHATS_DEFAULTS['min_activity_threshold']
                        }
                    
                    # Если настроек нет в БД, пытаемся мигрировать из JSON
                    json_path = Path("data/top_chats_settings.json")
                    if json_path.exists():
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                all_settings = json.load(f)
                            chat_settings = all_settings.get(str(chat_id), {})
                            
                            if chat_settings:
                                # Мигрируем данные в БД
                                settings_to_save = {**TOP_CHATS_DEFAULTS, **chat_settings}
                                
                                # Удаляем поле 'visible', если оно есть (оно не используется)
                                settings_to_save.pop('visible', None)
                                
                                # Сохраняем в БД
                                updates = []
                                params = []
                                
                                if 'show_in_top' in settings_to_save:
                                    updates.append("show_in_top = ?")
                                    params.append(settings_to_save['show_in_top'])
                                
                                if 'show_private_label' in settings_to_save:
                                    updates.append("show_private_label = ?")
                                    params.append(1 if settings_to_save['show_private_label'] else 0)
                                
                                if 'min_activity_threshold' in settings_to_save:
                                    updates.append("min_activity_threshold = ?")
                                    params.append(int(settings_to_save['min_activity_threshold']))
                                
                                if updates:
                                    params.append(chat_id)
                                    query = f"UPDATE chats SET {', '.join(updates)} WHERE chat_id = ?"
                                    db.execute(query, params)
                                    db.commit()
                                    logger.info(f"Настройки топа для чата {chat_id} мигрированы из JSON в БД")
                                
                                return settings_to_save
                        except Exception as json_error:
                            logger.warning(f"Ошибка при миграции настроек топа из JSON для чата {chat_id}: {json_error}")
                    
                    # Если ничего не найдено, возвращаем значения по умолчанию
                    return TOP_CHATS_DEFAULTS.copy()
            except Exception as e:
                logger.error(f"Ошибка при получении настроек топа для чата {chat_id}: {e}")
                from config import TOP_CHATS_DEFAULTS
                return TOP_CHATS_DEFAULTS.copy()
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_settings_sync)
    
    async def set_top_chat_setting(self, chat_id: int, setting_name: str, value: Any) -> bool:
        """Установить одну настройку топа для чата"""
        def _set_setting_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    if setting_name == 'show_in_top':
                        db.execute("UPDATE chats SET show_in_top = ? WHERE chat_id = ?", (value, chat_id))
                    elif setting_name == 'show_private_label':
                        db.execute("UPDATE chats SET show_private_label = ? WHERE chat_id = ?", (1 if value else 0, chat_id))
                    elif setting_name == 'min_activity_threshold':
                        db.execute("UPDATE chats SET min_activity_threshold = ? WHERE chat_id = ?", (int(value), chat_id))
                    else:
                        logger.warning(f"Неизвестная настройка топа: {setting_name}")
                        return False
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при установке настройки топа {setting_name} для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _set_setting_sync)
    
    async def update_top_chat_settings(self, chat_id: int, settings: Dict[str, Any]) -> bool:
        """Обновить несколько настроек топа для чата"""
        def _update_settings_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    updates = []
                    params = []
                    
                    if 'show_in_top' in settings:
                        updates.append("show_in_top = ?")
                        params.append(settings['show_in_top'])
                    
                    if 'show_private_label' in settings:
                        updates.append("show_private_label = ?")
                        params.append(1 if settings['show_private_label'] else 0)
                    
                    if 'min_activity_threshold' in settings:
                        updates.append("min_activity_threshold = ?")
                        params.append(int(settings['min_activity_threshold']))
                    
                    if updates:
                        params.append(chat_id)
                        query = f"UPDATE chats SET {', '.join(updates)} WHERE chat_id = ?"
                        db.execute(query, params)
                        db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении настроек топа для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_settings_sync)
    
    async def update_admin_rights(self, chat_id: int, has_rights: bool) -> bool:
        """Обновление информации о правах администратора"""
        def _update_admin_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE chats SET has_admin_rights = ? WHERE chat_id = ?
                    """, (has_rights, chat_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении прав администратора для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_admin_sync)
    
    async def increment_message_count(self, chat_id: int, date: str = None) -> bool:
        """Увеличение счетчика сообщений за день"""
        if date is None:
            # Дата по московскому времени (UTC+3)
            ts = datetime.utcnow().timestamp() + 10800
            date = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
        
        def _increment_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем, есть ли запись за этот день
                    cursor = db.execute("""
                        SELECT message_count FROM daily_stats 
                        WHERE chat_id = ? AND date = ?
                    """, (chat_id, date))
                    row = cursor.fetchone()
                    
                    if row:
                        # Обновляем существующую запись
                        db.execute("""
                            UPDATE daily_stats SET message_count = message_count + 1
                            WHERE chat_id = ? AND date = ?
                        """, (chat_id, date))
                    else:
                        # Создаем новую запись
                        db.execute("""
                            INSERT INTO daily_stats (chat_id, date, message_count)
                            VALUES (?, ?, 1)
                        """, (chat_id, date))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при увеличении счетчика сообщений для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _increment_sync)
    
    async def get_daily_stats(self, chat_id: int, days: int = 7) -> List[Dict[str, Any]]:
        """Получение статистики сообщений за последние N дней"""
        def _get_stats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT date, message_count FROM daily_stats 
                        WHERE chat_id = ? 
                        ORDER BY date DESC 
                        LIMIT ?
                    """, (chat_id, days))
                    rows = cursor.fetchall()
                    return [
                        {
                            'date': row[0],
                            'message_count': row[1]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении статистики для чата {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_stats_sync)
    
    async def get_today_message_count(self, chat_id: int) -> int:
        """Получение количества сообщений за сегодня"""
        # Дата по московскому времени (UTC+3)
        ts = datetime.utcnow().timestamp() + 10800
        today = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
        stats = await self.get_daily_stats(chat_id, 1)
        
        if stats and stats[0]['date'] == today:
            return stats[0]['message_count']
        return 0

    async def ensure_user_first_seen(self, chat_id: int, user_id: int, when: str | None = None) -> None:
        """Зафиксировать дату первого появления пользователя в чате"""
        if when is None:
            when = datetime.now().strftime('%Y-%m-%d')

        def _ensure_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Пытаемся вставить, при конфликте ничего не делаем
                    db.execute(
                        """
                        INSERT OR IGNORE INTO user_chat_meta (chat_id, user_id, first_seen)
                        VALUES (?, ?, ?)
                        """,
                        (chat_id, user_id, when),
                    )
                    db.commit()
            except Exception as e:
                logger.error(f"Ошибка при фиксации first_seen для пользователя {user_id} в чате {chat_id}: {e}")

        await asyncio.get_event_loop().run_in_executor(None, _ensure_sync)

    async def get_user_first_seen(self, chat_id: int, user_id: int) -> str | None:
        """Получить дату первого появления пользователя в чате"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        "SELECT first_seen FROM user_chat_meta WHERE chat_id = ? AND user_id = ?",
                        (chat_id, user_id),
                    )
                    row = cur.fetchone()
                    return row[0] if row else None
            except Exception as e:
                logger.error(f"Ошибка при получении first_seen для пользователя {user_id} в чате {chat_id}: {e}")
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)

    async def get_user_30d_stats(self, chat_id: int, user_id: int) -> list[dict[str, int | str]]:
        """Статистика пользователя по дням за последние 30 дней в чате"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        """
                        SELECT date, message_count FROM user_daily_stats
                        WHERE chat_id = ? AND user_id = ?
                          AND date >= date('now','-29 days')
                        ORDER BY date ASC
                        """,
                        (chat_id, user_id),
                    )
                    rows = cur.fetchall()
                    return [{"date": r[0], "message_count": r[1]} for r in rows]
            except Exception as e:
                logger.error(f"Ошибка при получении 30д статистики пользователя {user_id}: {e}")
                return []

        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)

    async def get_user_7d_stats(self, chat_id: int, user_id: int) -> list[dict[str, int | str]]:
        """Статистика пользователя по дням за последние 7 дней в чате"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        """
                        SELECT date, message_count FROM user_daily_stats
                        WHERE chat_id = ? AND user_id = ?
                          AND date >= date('now','-6 days')
                        ORDER BY date ASC
                        """,
                        (chat_id, user_id),
                    )
                    rows = cur.fetchall()
                    return [{"date": r[0], "message_count": r[1]} for r in rows]
            except Exception as e:
                logger.error(f"Ошибка при получении 7д статистики пользователя {user_id}: {e}")
                return []

        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)

    async def get_user_best_day(self, chat_id: int, user_id: int) -> dict | None:
        """Лучший день пользователя (макс. сообщений) в чате"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        """
                        SELECT date, message_count FROM user_daily_stats
                        WHERE chat_id = ? AND user_id = ?
                        ORDER BY message_count DESC, date DESC
                        LIMIT 1
                        """,
                        (chat_id, user_id),
                    )
                    row = cur.fetchone()
                    return {"date": row[0], "message_count": row[1]} if row else None
            except Exception as e:
                logger.error(f"Ошибка при получении лучшего дня пользователя {user_id}: {e}")
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)

    async def get_user_daily_stats(self, chat_id: int, user_id: int, date: str) -> Optional[dict]:
        """Получение статистики пользователя за конкретный день"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        """
                        SELECT date, message_count FROM user_daily_stats
                        WHERE chat_id = ? AND user_id = ? AND date = ?
                        """,
                        (chat_id, user_id, date),
                    )
                    row = cur.fetchone()
                    if row:
                        return {"date": row[0], "message_count": row[1]}
                    return None
            except Exception as e:
                logger.error(f"Ошибка при получении дневной статистики пользователя {user_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)

    async def get_user_global_activity(self, user_id: int) -> dict:
        """Глобальная активность по всем чатам: сегодня и за 7 дней"""
        def _get_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cur = db.execute(
                        """
                        SELECT 
                          SUM(CASE WHEN date = date('now') THEN message_count ELSE 0 END) AS today_sum,
                          SUM(CASE WHEN date >= date('now','-6 days') THEN message_count ELSE 0 END) AS week_sum
                        FROM user_daily_stats
                        WHERE user_id = ?
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()
                    return {"today": row[0] or 0, "week": row[1] or 0}
            except Exception as e:
                logger.error(f"Ошибка при получении глобальной активности пользователя {user_id}: {e}")
                return {"today": 0, "week": 0}

        return await asyncio.get_event_loop().run_in_executor(None, _get_sync)
    
    async def cleanup_old_stats(self, days_to_keep: int = 7) -> bool:
        """Очистка старых записей статистики (старше N дней)"""
        def _cleanup_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Вычисляем сегодняшнюю дату по Москве (UTC+3)
                    ts = datetime.utcnow().timestamp() + 10800
                    moscow_today = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
                    # Удаляем записи старше указанного количества дней относительно московской даты
                    db.execute(
                        """
                        DELETE FROM daily_stats 
                        WHERE date < date(?, '-{} days')
                        """.format(days_to_keep),
                        (moscow_today,)
                    )
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке старых записей: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def reset_daily_stats(self, chat_id: int = None) -> bool:
        """Сброс ежедневной статистики за сегодня (по МСК)
        
        Args:
            chat_id: ID чата для сброса статистики. Если None, сбрасывает для всех чатов.
        
        Returns:
            True если успешно, False при ошибке
        """
        # Дата по московскому времени (UTC+3)
        # Правильный способ: получаем UTC время, добавляем 3 часа, затем извлекаем дату
        from datetime import timezone, timedelta
        msk_tz = timezone(timedelta(hours=3))
        now_msk = datetime.now(msk_tz)
        today = now_msk.strftime('%Y-%m-%d')
        
        def _reset_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    if chat_id is not None:
                        # Сбрасываем статистику для конкретного чата
                        db.execute(
                            "DELETE FROM daily_stats WHERE chat_id = ? AND date = ?",
                            (chat_id, today)
                        )
                        db.execute(
                            "DELETE FROM user_daily_stats WHERE chat_id = ? AND date = ?",
                            (chat_id, today)
                        )
                    else:
                        # Сбрасываем статистику для всех чатов
                        db.execute(
                            "DELETE FROM daily_stats WHERE date = ?",
                            (today,)
                        )
                        db.execute(
                            "DELETE FROM user_daily_stats WHERE date = ?",
                            (today,)
                        )
                    db.commit()
                    logger.info(f"Ежедневная статистика сброшена за {today} для {'чата ' + str(chat_id) if chat_id else 'всех чатов'}")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при сбросе ежедневной статистики: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _reset_sync)
    
    async def increment_user_message_count(self, chat_id: int, user_id: int, 
                                         username: str = None, first_name: str = None, 
                                         last_name: str = None, date: str = None) -> bool:
        """Увеличение счетчика сообщений пользователя за день"""
        if date is None:
            # Дата по московскому времени (UTC+3)
            ts = datetime.utcnow().timestamp() + 10800
            date = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
        
        def _increment_user_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Включаем настройки производительности
                    _apply_pragma_settings(db)
                    
                    # Проверяем, есть ли дубликаты для этого пользователя за этот день
                    cursor = db.execute("""
                        SELECT COUNT(*) FROM user_daily_stats 
                        WHERE chat_id = ? AND user_id = ? AND date = ?
                    """, (chat_id, user_id, date))
                    record_count = cursor.fetchone()[0]
                    
                    if record_count > 1:
                        # Есть дубликаты - удаляем их и суммируем message_count
                        cursor = db.execute("""
                            SELECT SUM(message_count) as total_count
                            FROM user_daily_stats
                            WHERE chat_id = ? AND user_id = ? AND date = ?
                        """, (chat_id, user_id, date))
                        total_count_row = cursor.fetchone()
                        total_count = total_count_row[0] if total_count_row and total_count_row[0] is not None else 0
                        
                        # Удаляем все дубликаты, оставляем только одну запись с максимальным rowid
                        db.execute("""
                            DELETE FROM user_daily_stats 
                            WHERE chat_id = ? AND user_id = ? AND date = ?
                            AND rowid NOT IN (
                                SELECT MAX(rowid) 
                                FROM user_daily_stats 
                                WHERE chat_id = ? AND user_id = ? AND date = ?
                            )
                        """, (chat_id, user_id, date, chat_id, user_id, date))
                        
                        # Обновляем оставшуюся запись с суммированным счетчиком + 1
                        new_count = total_count + 1
                        cursor = db.execute("""
                            UPDATE user_daily_stats 
                            SET message_count = ?, username = ?, first_name = ?, last_name = ?
                            WHERE chat_id = ? AND user_id = ? AND date = ?
                        """, (new_count, username, first_name, last_name, chat_id, user_id, date))
                        
                        # Если запись не была обновлена (не найдена после удаления), создаем новую
                        if cursor.rowcount == 0:
                            logger.warning(f"Запись не найдена после удаления дубликатов, создаем новую для user_id={user_id}, chat_id={chat_id}, date={date}")
                            db.execute("""
                                INSERT INTO user_daily_stats 
                                (chat_id, user_id, date, message_count, username, first_name, last_name)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (chat_id, user_id, date, new_count, username, first_name, last_name))
                    elif record_count == 1:
                        # Запись уже существует (одна), увеличиваем счетчик
                        cursor = db.execute("""
                            SELECT message_count FROM user_daily_stats 
                            WHERE chat_id = ? AND user_id = ? AND date = ?
                        """, (chat_id, user_id, date))
                        row = cursor.fetchone()
                        if row and row[0] is not None:
                            new_count = row[0] + 1
                        else:
                            new_count = 1
                        db.execute("""
                            UPDATE user_daily_stats 
                            SET message_count = ?, username = ?, first_name = ?, last_name = ?
                            WHERE chat_id = ? AND user_id = ? AND date = ?
                        """, (new_count, username, first_name, last_name, chat_id, user_id, date))
                    else:
                        # Записи нет, создаем новую
                        # Используем INSERT OR IGNORE для защиты от возможных конфликтов с уникальным индексом
                        # Если запись уже существует (race condition), обновим её
                        try:
                            db.execute("""
                                INSERT INTO user_daily_stats 
                                (chat_id, user_id, date, message_count, username, first_name, last_name)
                                VALUES (?, ?, ?, 1, ?, ?, ?)
                            """, (chat_id, user_id, date, username, first_name, last_name))
                        except sqlite3.IntegrityError:
                            # Если возникла ошибка уникальности (индекс уже создан и есть запись),
                            # обновляем существующую запись
                            cursor = db.execute("""
                                SELECT message_count FROM user_daily_stats 
                                WHERE chat_id = ? AND user_id = ? AND date = ?
                            """, (chat_id, user_id, date))
                            row = cursor.fetchone()
                            if row and row[0] is not None:
                                new_count = row[0] + 1
                            else:
                                new_count = 1
                            db.execute("""
                                UPDATE user_daily_stats 
                                SET message_count = ?, username = ?, first_name = ?, last_name = ?
                                WHERE chat_id = ? AND user_id = ? AND date = ?
                            """, (new_count, username, first_name, last_name, chat_id, user_id, date))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при увеличении счетчика сообщений пользователя {user_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _increment_user_sync)
    
    async def get_top_users_today(self, chat_id: int, limit: int = 20, timezone_offset: int = 3) -> List[Dict[str, Any]]:
        """Получение топа пользователей за сегодня с учетом часового пояса. Группирует по user_id для предотвращения дубликатов."""
        # Дата с учетом часового пояса пользователя
        ts = datetime.utcnow().timestamp() + (timezone_offset * 3600)
        today = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
        
        def _get_top_users_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Применяем настройки производительности
                    _apply_pragma_settings(db)
                    
                    # Отладочная информация только в DEBUG режиме
                    if DEBUG:
                        logger.info(f"get_top_users_today: chat_id={chat_id}, today={today}, limit={limit}")
                        
                        # Проверяем, есть ли вообще записи для этого чата
                        cursor = db.execute("""
                            SELECT COUNT(*) FROM user_daily_stats 
                            WHERE chat_id = ?
                        """, (chat_id,))
                        total_records = cursor.fetchone()[0]
                        logger.info(f"Всего записей в user_daily_stats для чата {chat_id}: {total_records}")
                        
                        # Проверяем записи за сегодня
                        cursor = db.execute("""
                            SELECT COUNT(*) FROM user_daily_stats 
                            WHERE chat_id = ? AND date = ?
                        """, (chat_id, today))
                        today_records = cursor.fetchone()[0]
                        logger.info(f"Записей за {today} для чата {chat_id}: {today_records}")
                    
                    # Основной запрос с оптимизированным индексом
                    cursor = db.execute("""
                        SELECT user_id, MAX(username) as username, MAX(first_name) as first_name, MAX(last_name) as last_name, SUM(message_count) as message_count 
                        FROM user_daily_stats 
                        WHERE chat_id = ? AND date = ? AND message_count > 0
                        GROUP BY user_id
                        ORDER BY message_count DESC 
                        LIMIT ?
                    """, (chat_id, today, limit))
                    rows = cursor.fetchall()
                    
                    if DEBUG:
                        logger.info(f"Найдено {len(rows)} пользователей с сообщениями > 0")
                    
                    return [
                        {
                            'user_id': row[0],
                            'username': row[1],
                            'first_name': row[2],
                            'last_name': row[3],
                            'message_count': row[4]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении топа пользователей для чата {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_top_users_sync)
    
    async def get_top_users_last_days_global(self, days: int = 60, limit: int = 30) -> List[Dict[str, Any]]:
        """Топ пользователей по сообщениям за последние N дней по всем чатам."""
        def _get_top_users_last_days_global_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute(
                        f"""
                            SELECT 
                                user_id,
                                MAX(username) as username,
                                MAX(first_name) as first_name,
                                MAX(last_name) as last_name,
                                SUM(message_count) as total_messages
                            FROM user_daily_stats
                            WHERE date >= date('now','-{days} days')
                            GROUP BY user_id
                            HAVING total_messages > 0
                            ORDER BY total_messages DESC
                            LIMIT ?
                        """,
                        (limit,)
                    )
                    rows = cursor.fetchall()
                    return [
                        {
                            'user_id': row[0],
                            'username': row[1],
                            'first_name': row[2],
                            'last_name': row[3],
                            'message_count': row[4]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении глобального топа пользователей за {days} дней: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_top_users_last_days_global_sync)

    async def get_top_users_last_days(self, chat_id: int, days: int = 60, limit: int = 20) -> List[Dict[str, Any]]:
        """Топ пользователей по сообщениям за последние N дней для конкретного чата."""
        def _get_top_users_last_days_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute(
                        f"""
                            SELECT 
                                user_id,
                                MAX(username) as username,
                                MAX(first_name) as first_name,
                                MAX(last_name) as last_name,
                                SUM(message_count) as total_messages
                            FROM user_daily_stats
                            WHERE chat_id = ? AND date >= date('now','-{days} days')
                            GROUP BY user_id
                            HAVING total_messages > 0
                            ORDER BY total_messages DESC
                            LIMIT ?
                        """,
                        (chat_id, limit)
                    )
                    rows = cursor.fetchall()
                    return [
                        {
                            'user_id': row[0],
                            'username': row[1],
                            'first_name': row[2],
                            'last_name': row[3],
                            'message_count': row[4]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении топа пользователей за {days} дней для чата {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_top_users_last_days_sync)
    
    async def get_all_active_chats(self) -> List[Dict[str, Any]]:
        """Получение всех активных чатов"""
        def _get_chats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Используем DISTINCT чтобы избежать дубликатов
                    cursor = db.execute("""
                        SELECT DISTINCT chat_id, chat_title, owner_id, added_date, has_admin_rights, chat_type, member_count
                        FROM chats 
                        WHERE is_active = 1 AND is_public = 1
                        ORDER BY added_date DESC
                    """)
                    rows = cursor.fetchall()
                    return [
                        {
                            'chat_id': row[0],
                            'chat_title': row[1],
                            'owner_id': row[2],
                            'added_date': row[3],
                            'has_admin_rights': bool(row[4]),
                            'chat_type': row[5],
                            'member_count': row[6]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении списка чатов: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_chats_sync)
    
    async def get_all_chats_for_update(self) -> List[Dict[str, Any]]:
        """Получение всех активных чатов для обновления (включая приватные)"""
        def _get_all_chats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT DISTINCT chat_id, chat_title, owner_id, added_date, has_admin_rights, chat_type, member_count
                        FROM chats 
                        WHERE is_active = 1
                        ORDER BY added_date DESC
                    """)
                    rows = cursor.fetchall()
                    return [
                        {
                            'chat_id': row[0],
                            'chat_title': row[1],
                            'owner_id': row[2],
                            'added_date': row[3],
                            'has_admin_rights': bool(row[4]),
                            'chat_type': row[5],
                            'member_count': row[6]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении всех чатов для обновления: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_all_chats_sync)
    
    async def get_chat_activity_stats(self, chat_id: int, days: int = 7) -> Dict[str, Any]:
        """Получение статистики активности чата за N дней"""
        def _get_stats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Общее количество сообщений за период
                    # Граница периода относительно московской даты
                    ts = datetime.utcnow().timestamp() + 10800
                    moscow_today = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
                    cursor = db.execute(
                        """
                        SELECT SUM(message_count) as total_messages
                        FROM daily_stats 
                        WHERE chat_id = ? AND date >= date(?, '-{} days')
                        """.format(days),
                        (chat_id, moscow_today)
                    )
                    total_row = cursor.fetchone()
                    total_messages = total_row[0] if total_row[0] else 0
                    
                    # Количество активных пользователей
                    cursor = db.execute(
                        """
                        SELECT COUNT(DISTINCT user_id) as active_users
                        FROM user_daily_stats 
                        WHERE chat_id = ? AND date >= date(?, '-{} days') AND message_count > 0
                        """.format(days),
                        (chat_id, moscow_today)
                    )
                    users_row = cursor.fetchone()
                    active_users = users_row[0] if users_row[0] else 0
                    
                    return {
                        'total_messages': total_messages,
                        'active_users': active_users
                    }
            except Exception as e:
                logger.error(f"Ошибка при получении статистики чата {chat_id}: {e}")
                return {'total_messages': 0, 'active_users': 0}
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_stats_sync)
    
    async def create_join_request(self, chat_id: int, user_id: int, admin_message_id: int = None) -> int:
        """Создание запроса на вступление в чат"""
        def _create_request_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        INSERT INTO chat_join_requests (chat_id, user_id, request_date, admin_message_id)
                        VALUES (?, ?, ?, ?)
                    """, (chat_id, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), admin_message_id))
                    db.commit()
                    return cursor.lastrowid
            except Exception as e:
                logger.error(f"Ошибка при создании запроса на вступление: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _create_request_sync)
    
    async def update_join_request_status(self, request_id: int, status: str, invite_link: str = None) -> bool:
        """Обновление статуса запроса на вступление"""
        def _update_request_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE chat_join_requests 
                        SET status = ?, invite_link = ?
                        WHERE id = ?
                    """, (status, invite_link, request_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении статуса запроса {request_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_request_sync)
    
    async def get_join_request(self, request_id: int) -> Optional[Dict[str, Any]]:
        """Получение информации о запросе на вступление"""
        def _get_request_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT id, chat_id, user_id, request_date, status, invite_link, admin_message_id
                        FROM chat_join_requests 
                        WHERE id = ?
                    """, (request_id,))
                    row = cursor.fetchone()
                    if row:
                        return {
                            'id': row[0],
                            'chat_id': row[1],
                            'user_id': row[2],
                            'request_date': row[3],
                            'status': row[4],
                            'invite_link': row[5],
                            'admin_message_id': row[6]
                        }
                    return None
            except Exception as e:
                logger.error(f"Ошибка при получении запроса {request_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_request_sync)
    
    async def update_chat_id(self, old_chat_id: int, new_chat_id: int) -> bool:
        """Обновление ID чата при миграции группы в супергруппу"""
        def _update_chat_id_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Проверяем, существует ли уже чат с новым ID
                    cursor = db.execute("SELECT chat_id FROM chats WHERE chat_id = ?", (new_chat_id,))
                    if cursor.fetchone():
                        logger.info(f"Чат с ID {new_chat_id} уже существует, удаляем старую запись")
                        # Удаляем старую запись
                        db.execute("DELETE FROM chats WHERE chat_id = ?", (old_chat_id,))
                    else:
                        # Обновляем ID в таблице chats
                        db.execute("UPDATE chats SET chat_id = ? WHERE chat_id = ?", (new_chat_id, old_chat_id))
                    
                    # Обновляем ID в остальных таблицах
                    db.execute("UPDATE daily_stats SET chat_id = ? WHERE chat_id = ?", (new_chat_id, old_chat_id))
                    db.execute("UPDATE user_daily_stats SET chat_id = ? WHERE chat_id = ?", (new_chat_id, old_chat_id))
                    db.execute("UPDATE user_chat_meta SET chat_id = ? WHERE chat_id = ?", (new_chat_id, old_chat_id))
                    db.execute("UPDATE chat_join_requests SET chat_id = ? WHERE chat_id = ?", (new_chat_id, old_chat_id))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении ID чата {old_chat_id} -> {new_chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_chat_id_sync)
    
    async def cleanup_old_user_stats(self, days_to_keep: int = 7) -> bool:
        """Очистка старых записей пользовательской статистики"""
        def _cleanup_user_stats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Удаляем записи старше указанного количества дней
                    db.execute("""
                        DELETE FROM user_daily_stats 
                        WHERE date < date('now', '-{} days')
                    """.format(days_to_keep))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке старых записей пользовательской статистики: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_user_stats_sync)
    
    async def get_top_chats_by_activity(self, days: int = 3, limit: int = 30, 
                                       exclude_chat_ids: list = None, 
                                       include_private: bool = False,
                                       min_activity_threshold: int = 0) -> List[Dict[str, Any]]:
        """
        Получение топ чатов по активности за указанное количество дней
        
        Args:
            days: Количество дней для анализа
            limit: Максимальное количество чатов в результате
            exclude_chat_ids: Список chat_id для исключения из топа
            include_private: Включать ли частные чаты (по умолчанию только публичные)
            min_activity_threshold: Минимальное количество сообщений для показа
        """
        def _get_top_chats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Формируем условия WHERE
                    where_conditions = [
                        "ds.date >= date('now', '-{} days')".format(days),
                        "c.is_active = 1"
                    ]
                    
                    # Условие для публичных/частных чатов
                    if not include_private:
                        where_conditions.append("c.is_public = 1")
                    
                    # Условие для исключения чатов
                    if exclude_chat_ids:
                        placeholders = ','.join(['?'] * len(exclude_chat_ids))
                        where_conditions.append(f"c.chat_id NOT IN ({placeholders})")
                    
                    where_clause = " AND ".join(where_conditions)
                    
                    # Параметры для запроса
                    params = []
                    if exclude_chat_ids:
                        params.extend(exclude_chat_ids)
                    
                    # Получаем топ чатов по общему количеству сообщений за последние N дней
                    query = f"""
                        SELECT 
                            ds.chat_id,
                            c.chat_title,
                            SUM(ds.message_count) as total_messages,
                            COUNT(DISTINCT ds.date) as active_days,
                            c.is_public
                        FROM daily_stats ds
                        JOIN chats c ON ds.chat_id = c.chat_id
                        WHERE {where_clause}
                        GROUP BY ds.chat_id
                        HAVING total_messages > ?
                        ORDER BY total_messages DESC, active_days DESC
                        LIMIT ?
                    """
                    
                    params.append(min_activity_threshold)
                    params.append(limit)
                    
                    cursor = db.execute(query, params)
                    
                    rows = cursor.fetchall()
                    return [
                        {
                            'chat_id': row[0],
                            'title': row[1],
                            'total_messages': row[2],
                            'active_days': row[3],
                            'is_public': bool(row[4]) if row[4] is not None else False
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении топ чатов: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_top_chats_sync)
    
    async def update_chat_info(self, chat_id: int, title: str = None, chat_type: str = None, 
                              member_count: int = None, is_active: bool = None, is_public: bool = None,
                              username: str = None, invite_link: str = None) -> bool:
        """Обновление информации о чате"""
        def _update_chat_info_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Формируем запрос обновления только для переданных полей
                    updates = []
                    params = []
                    
                    if title is not None:
                        updates.append("chat_title = ?")
                        params.append(title)
                    
                    if chat_type is not None:
                        updates.append("chat_type = ?")
                        params.append(chat_type)
                    
                    if member_count is not None:
                        updates.append("member_count = ?")
                        params.append(member_count)
                    
                    if is_active is not None:
                        updates.append("is_active = ?")
                        params.append(is_active)
                    
                    if is_public is not None:
                        updates.append("is_public = ?")
                        params.append(is_public)
                    
                    if username is not None:
                        updates.append("username = ?")
                        params.append(username)
                    
                    if invite_link is not None:
                        updates.append("invite_link = ?")
                        params.append(invite_link)
                    
                    if updates:
                        params.append(chat_id)
                        query = f"UPDATE chats SET {', '.join(updates)} WHERE chat_id = ?"
                        db.execute(query, params)
                        db.commit()
                        return True
                    return False
            except Exception as e:
                logger.error(f"Ошибка при обновлении информации о чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_chat_info_sync)
    
    async def deactivate_chat(self, chat_id: int) -> bool:
        """Деактивация чата и установка времени заморозки (бот был удален)"""
        def _deactivate_chat_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    frozen_at = datetime.now().isoformat()
                    db.execute("""
                        UPDATE chats 
                        SET is_active = 0, frozen_at = ? 
                        WHERE chat_id = ?
                    """, (frozen_at, chat_id))
                    db.commit()
                    logger.info(f"Чат {chat_id} деактивирован и заморожен (frozen_at: {frozen_at})")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при деактивации чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _deactivate_chat_sync)
    
    async def unfreeze_chat(self, chat_id: int) -> bool:
        """Разморозка чата и сброс времени заморозки (бот был добавлен обратно)"""
        def _unfreeze_chat_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE chats 
                        SET is_active = 1, frozen_at = NULL 
                        WHERE chat_id = ?
                    """, (chat_id,))
                    db.commit()
                    logger.info(f"Чат {chat_id} разморожен (frozen_at сброшен, is_active = 1)")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при разморозке чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _unfreeze_chat_sync)
    
    async def cleanup_duplicate_chats(self) -> bool:
        """Очистка дублирующихся записей чатов"""
        def _cleanup_duplicates_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Находим дубликаты по chat_id
                    cursor = db.execute("""
                        SELECT chat_id, COUNT(*) as count
                        FROM chats
                        GROUP BY chat_id
                        HAVING COUNT(*) > 1
                    """)
                    duplicates = cursor.fetchall()
                    
                    total_cleaned = 0
                    for chat_id, count in duplicates:
                        logger.info(f"Найден дубликат чата {chat_id} ({count} записей)")
                        
                        # Оставляем только самую новую запись
                        result = db.execute("""
                            DELETE FROM chats 
                            WHERE chat_id = ? 
                            AND rowid NOT IN (
                                SELECT MAX(rowid) 
                                FROM chats 
                                WHERE chat_id = ?
                            )
                        """, (chat_id, chat_id))
                        
                        total_cleaned += result.rowcount
                        logger.info(f"Удалено {result.rowcount} дубликатов для чата {chat_id}")
                    
                    # Также очищаем дубликаты в daily_stats
                    cursor = db.execute("""
                        SELECT chat_id, date, COUNT(*) as count
                        FROM daily_stats
                        GROUP BY chat_id, date
                        HAVING COUNT(*) > 1
                    """)
                    stats_duplicates = cursor.fetchall()
                    
                    for chat_id, date, count in stats_duplicates:
                        logger.info(f"Найден дубликат статистики для чата {chat_id} на дату {date} ({count} записей)")
                        
                        # Оставляем только самую новую запись
                        result = db.execute("""
                            DELETE FROM daily_stats 
                            WHERE chat_id = ? AND date = ?
                            AND rowid NOT IN (
                                SELECT MAX(rowid) 
                                FROM daily_stats 
                                WHERE chat_id = ? AND date = ?
                            )
                        """, (chat_id, date, chat_id, date))
                        
                        total_cleaned += result.rowcount
                    
                    # Очищаем дубликаты в user_daily_stats
                    cursor = db.execute("""
                        SELECT chat_id, user_id, date, COUNT(*) as count
                        FROM user_daily_stats
                        GROUP BY chat_id, user_id, date
                        HAVING COUNT(*) > 1
                    """)
                    user_stats_duplicates = cursor.fetchall()
                    
                    for chat_id, user_id, date, count in user_stats_duplicates:
                        logger.info(f"Найден дубликат статистики пользователя {user_id} в чате {chat_id} на дату {date} ({count} записей)")
                        
                        # Находим запись с максимальным message_count (или самую новую по rowid, если счетчики равны)
                        # Сначала суммируем все message_count для этого пользователя
                        cursor = db.execute("""
                            SELECT SUM(message_count) as total_count
                            FROM user_daily_stats
                            WHERE chat_id = ? AND user_id = ? AND date = ?
                        """, (chat_id, user_id, date))
                        total_count_row = cursor.fetchone()
                        total_count = total_count_row[0] if total_count_row else 0
                        
                        # Оставляем только одну запись с максимальным rowid, обновляем её message_count на сумму всех
                        result = db.execute("""
                            DELETE FROM user_daily_stats 
                            WHERE chat_id = ? AND user_id = ? AND date = ?
                            AND rowid NOT IN (
                                SELECT MAX(rowid) 
                                FROM user_daily_stats 
                                WHERE chat_id = ? AND user_id = ? AND date = ?
                            )
                        """, (chat_id, user_id, date, chat_id, user_id, date))
                        
                        # Обновляем оставшуюся запись с правильным message_count
                        db.execute("""
                            UPDATE user_daily_stats
                            SET message_count = ?
                            WHERE chat_id = ? AND user_id = ? AND date = ?
                        """, (total_count, chat_id, user_id, date))
                        
                        total_cleaned += result.rowcount
                        logger.info(f"Удалено {result.rowcount} дубликатов для пользователя {user_id} в чате {chat_id} на дату {date}, обновлен счетчик до {total_count}")
                    
                    db.commit()
                    logger.info(f"Всего очищено {total_cleaned} дубликатов")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при очистке дубликатов чатов: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_duplicates_sync)
    
    async def assign_moderator(self, chat_id: int, user_id: int, rank: int, assigned_by: int) -> bool:
        """Назначение ранга модератора"""
        def _assign_moderator_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Назначаем ранг
                    db.execute("""
                        INSERT OR REPLACE INTO chat_moderators 
                        (chat_id, user_id, rank, assigned_by, assigned_date)
                        VALUES (?, ?, ?, ?, ?)
                    """, (chat_id, user_id, rank, assigned_by, datetime.now().isoformat()))
                    
                    # Создаем права по умолчанию для этого ранга, если их еще нет
                    from utils.constants import DEFAULT_RANK_PERMISSIONS
                    default_permissions = DEFAULT_RANK_PERMISSIONS.get(rank, {})
                    
                    for permission_type, permission_value in default_permissions.items():
                        # Проверяем, есть ли уже это право
                        cursor = db.execute("""
                            SELECT id FROM rank_permissions 
                            WHERE chat_id = ? AND rank = ? AND permission_type = ?
                        """, (chat_id, rank, permission_type))
                        
                        if not cursor.fetchone():
                            # Создаем право по умолчанию
                            db.execute("""
                                INSERT INTO rank_permissions 
                                (chat_id, rank, permission_type, permission_value)
                                VALUES (?, ?, ?, ?)
                            """, (chat_id, rank, permission_type, permission_value))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при назначении модератора {user_id} в чат {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _assign_moderator_sync)
    
    async def initialize_rank_permissions(self, chat_id: int) -> bool:
        """Инициализация прав по умолчанию для всех рангов в чате"""
        def _initialize_permissions_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    from utils.constants import DEFAULT_RANK_PERMISSIONS
                    
                    for rank, permissions in DEFAULT_RANK_PERMISSIONS.items():
                        for permission_type, permission_value in permissions.items():
                            # Проверяем, есть ли уже это право
                            cursor = db.execute("""
                                SELECT id FROM rank_permissions 
                                WHERE chat_id = ? AND rank = ? AND permission_type = ?
                            """, (chat_id, rank, permission_type))
                            
                            if not cursor.fetchone():
                                # Создаем право по умолчанию
                                db.execute("""
                                    INSERT INTO rank_permissions 
                                    (chat_id, rank, permission_type, permission_value)
                                    VALUES (?, ?, ?, ?)
                                """, (chat_id, rank, permission_type, permission_value))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при инициализации прав для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _initialize_permissions_sync)
    
    async def remove_moderator(self, chat_id: int, user_id: int) -> bool:
        """Снятие ранга модератора"""
        def _remove_moderator_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM chat_moderators 
                        WHERE chat_id = ? AND user_id = ?
                    """, (chat_id, user_id))
                    db.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Ошибка при снятии модератора {user_id} из чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _remove_moderator_sync)
    
    async def get_user_rank(self, chat_id: int, user_id: int) -> Optional[int]:
        """Получение ранга пользователя в чате"""
        def _get_user_rank_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT rank FROM chat_moderators 
                        WHERE chat_id = ? AND user_id = ?
                    """, (chat_id, user_id))
                    row = cursor.fetchone()
                    return row[0] if row else None
            except Exception as e:
                logger.error(f"Ошибка при получении ранга пользователя {user_id} в чате {chat_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_rank_sync)
    
    async def get_chat_moderators(self, chat_id: int) -> List[Dict[str, Any]]:
        """Получение списка всех модераторов чата"""
        def _get_chat_moderators_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT cm.user_id, cm.rank, u.username, u.first_name, u.last_name
                        FROM chat_moderators cm
                        JOIN users u ON cm.user_id = u.user_id
                        WHERE cm.chat_id = ?
                        ORDER BY cm.rank ASC, u.first_name ASC
                    """, (chat_id,))
                    rows = cursor.fetchall()
                    return [
                        {
                            'user_id': row[0],
                            'rank': row[1],
                            'username': row[2],
                            'first_name': row[3],
                            'last_name': row[4]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении модераторов чата {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_chat_moderators_sync)
    
    async def update_moderator_rank(self, chat_id: int, user_id: int, new_rank: int, assigned_by: int) -> bool:
        """Обновление ранга модератора"""
        def _update_moderator_rank_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        UPDATE chat_moderators 
                        SET rank = ?, assigned_by = ?, assigned_date = ?
                        WHERE chat_id = ? AND user_id = ?
                    """, (new_rank, assigned_by, datetime.now().isoformat(), chat_id, user_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении ранга модератора {user_id} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_moderator_rank_sync)
    
    # ========== МЕТОДЫ ДЛЯ РАБОТЫ С ПРАВАМИ РАНГОВ ==========
    
    async def get_rank_permission(self, chat_id: int, rank: int, permission_type: str) -> Optional[bool]:
        """Получить право для ранга в чате"""
        def _get_rank_permission_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT permission_value FROM rank_permissions 
                        WHERE chat_id = ? AND rank = ? AND permission_type = ?
                    """, (chat_id, rank, permission_type))
                    row = cursor.fetchone()
                    return bool(row[0]) if row else None
            except Exception as e:
                logger.error(f"Ошибка при получении права {permission_type} для ранга {rank} в чате {chat_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_rank_permission_sync)
    
    async def set_rank_permission(self, chat_id: int, rank: int, permission_type: str, value: bool) -> bool:
        """Установить право для ранга в чате"""
        # Специальная защита: для ранга владельца (ранг 1) право can_config_ranks всегда должно быть True
        if rank == 1 and permission_type == 'can_config_ranks' and not value:
            logger.warning(f"Попытка отключить право can_config_ranks для владельца в чате {chat_id} - игнорируется")
            # Принудительно устанавливаем True
            value = True
        
        final_value = value  # Сохраняем значение для использования во вложенной функции
        
        def _set_rank_permission_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT OR REPLACE INTO rank_permissions 
                        (chat_id, rank, permission_type, permission_value) 
                        VALUES (?, ?, ?, ?)
                    """, (chat_id, rank, permission_type, final_value))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при установке права {permission_type} для ранга {rank} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _set_rank_permission_sync)
    
    async def get_all_rank_permissions(self, chat_id: int, rank: int) -> Dict[str, bool]:
        """Получить все права для ранга в чате"""
        def _get_all_rank_permissions_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT permission_type, permission_value FROM rank_permissions 
                        WHERE chat_id = ? AND rank = ?
                    """, (chat_id, rank))
                    return {row[0]: bool(row[1]) for row in cursor.fetchall()}
            except Exception as e:
                logger.error(f"Ошибка при получении всех прав для ранга {rank} в чате {chat_id}: {e}")
                return {}
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_all_rank_permissions_sync)
    
    async def reset_rank_permissions_to_default(self, chat_id: int, rank: int) -> bool:
        """Сбросить права ранга к стандартным"""
        def _reset_rank_permissions_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Удаляем все существующие права для этого ранга
                    db.execute("""
                        DELETE FROM rank_permissions 
                        WHERE chat_id = ? AND rank = ?
                    """, (chat_id, rank))
                    
                    # Добавляем стандартные права
                    from utils.constants import DEFAULT_RANK_PERMISSIONS
                    if rank in DEFAULT_RANK_PERMISSIONS:
                        for permission_type, value in DEFAULT_RANK_PERMISSIONS[rank].items():
                            db.execute("""
                                INSERT INTO rank_permissions 
                                (chat_id, rank, permission_type, permission_value) 
                                VALUES (?, ?, ?, ?)
                            """, (chat_id, rank, permission_type, value))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при сбросе прав для ранга {rank} в чате {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _reset_rank_permissions_sync)
    
    async def has_permission(self, chat_id: int, user_id: int, permission_type: str) -> Optional[bool]:
        """Проверить, есть ли у пользователя право. Возвращает None если права не настроены"""
        async def _has_permission_async():
            try:
                # Сначала проверяем, является ли пользователь владельцем чата
                # Владелец чата должен проверяться через Telegram API
                from utils.permissions import get_effective_rank
                effective_rank = await get_effective_rank(chat_id, user_id)
                
                # Если пользователь не является модератором (ранг 5), возвращаем None для fallback
                if effective_rank == 5:
                    return None
                
                rank = effective_rank
                
                # Теперь проверяем право для этого ранга в БД
                def _check_permission_sync():
                    try:
                        with sqlite3.connect(self.db_path) as db:
                            # Специальная защита: для ранга владельца (ранг 1) право can_config_ranks всегда должно быть True
                            if rank == 1 and permission_type == 'can_config_ranks':
                                # Проверяем, что в БД записано False, и если да - исправляем
                                cursor = db.execute("""
                                    SELECT permission_value FROM rank_permissions 
                                    WHERE chat_id = ? AND rank = ? AND permission_type = ?
                                """, (chat_id, rank, permission_type))
                                row = cursor.fetchone()
                                
                                if row is not None and not bool(row[0]):
                                    # Если право выключено, включаем его обратно
                                    db.execute("""
                                        UPDATE rank_permissions 
                                        SET permission_value = 1 
                                        WHERE chat_id = ? AND rank = ? AND permission_type = ?
                                    """, (chat_id, rank, permission_type))
                                    db.commit()
                                    logger.warning(f"Автоматически включено право can_config_ranks для владельца в чате {chat_id}")
                                
                                # Всегда возвращаем True для владельца
                                return True
                            
                            # Получаем право для этого ранга
                            cursor = db.execute("""
                                SELECT permission_value FROM rank_permissions 
                                WHERE chat_id = ? AND rank = ? AND permission_type = ?
                            """, (chat_id, rank, permission_type))
                            row = cursor.fetchone()
                            
                            # Если право найдено в БД, возвращаем его значение (даже если False)
                            if row is not None:
                                return bool(row[0])
                            
                            # Если права нет в БД, возвращаем None для использования fallback
                            # Это означает, что права для этого чата еще не были настроены
                            return None
                    except Exception as e:
                        logger.error(f"Ошибка при проверке права {permission_type} для ранга {rank} в чате {chat_id}: {e}")
                        return None
                
                return await asyncio.get_event_loop().run_in_executor(None, _check_permission_sync)
            except Exception as e:
                logger.error(f"Ошибка при проверке права {permission_type} для пользователя {user_id} в чате {chat_id}: {e}")
                return None
        
        return await _has_permission_async()
    
    async def get_chat_stat_settings(self, chat_id: int) -> dict:
        """Получить настройки статистики для чата"""
        def _get_settings_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT stats_enabled, count_media, profile_enabled, userinfo_enabled
                        FROM chat_stat_settings 
                        WHERE chat_id = ?
                    """, (chat_id,))
                    row = cursor.fetchone()
                    
                    if row:
                        return {
                            'stats_enabled': bool(row[0]),
                            'count_media': bool(row[1]) if row[1] is not None else True,
                            'profile_enabled': bool(row[2]) if len(row) > 2 and row[2] is not None else True,
                            'userinfo_enabled': bool(row[3]) if len(row) > 3 and row[3] is not None else True,
                        }
                    else:
                        # Возвращаем настройки по умолчанию
                        return {
                            'stats_enabled': True,
                            'count_media': True,
                            'profile_enabled': True,
                            'userinfo_enabled': True,
                        }
            except Exception as e:
                logger.error(f"Ошибка при получении настроек статистики для чата {chat_id}: {e}")
                return {
                    'stats_enabled': True,
                    'count_media': True,
                    'profile_enabled': True,
                    'userinfo_enabled': True,
                }
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_settings_sync)
    
    async def set_chat_stats_enabled(self, chat_id: int, enabled: bool) -> bool:
        """Включить/выключить статистику для чата"""
        def _set_stats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT OR REPLACE INTO chat_stat_settings (chat_id, stats_enabled, count_media)
                        VALUES (
                            ?, 
                            ?, 
                            COALESCE((SELECT count_media FROM chat_stat_settings WHERE chat_id = ?), 1)
                        )
                    """, (chat_id, enabled, chat_id))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при изменении настройки статистики для чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _set_stats_sync)

    async def set_chat_stats_count_media(self, chat_id: int, enabled: bool) -> bool:
        """Включить/выключить учет медиа-сообщений в статистике"""
        def _set_media_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT OR REPLACE INTO chat_stat_settings (chat_id, stats_enabled, count_media)
                        VALUES (
                            ?,
                            COALESCE((SELECT stats_enabled FROM chat_stat_settings WHERE chat_id = ?), 1),
                            ?
                        )
                    """, (chat_id, chat_id, enabled))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при изменении настройки count_media для чата {chat_id}: {e}")
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _set_media_sync)
    
    async def set_chat_stats_profile_enabled(self, chat_id: int, enabled: bool) -> bool:
        """Включить/выключить команду профиля в чате"""
        def _set_profile_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT OR REPLACE INTO chat_stat_settings (chat_id, stats_enabled, count_media, profile_enabled, userinfo_enabled)
                        VALUES (
                            ?,
                            COALESCE((SELECT stats_enabled FROM chat_stat_settings WHERE chat_id = ?), 1),
                            COALESCE((SELECT count_media FROM chat_stat_settings WHERE chat_id = ?), 1),
                            ?,
                            COALESCE((SELECT userinfo_enabled FROM chat_stat_settings WHERE chat_id = ?), 1)
                        )
                    """, (chat_id, chat_id, chat_id, enabled, chat_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при изменении настройки profile_enabled для чата {chat_id}: {e}")
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _set_profile_sync)
    
    async def set_chat_stats_userinfo_enabled(self, chat_id: int, enabled: bool) -> bool:
        """Включить/выключить команду userinfo в чате"""
        def _set_userinfo_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT OR REPLACE INTO chat_stat_settings (chat_id, stats_enabled, count_media, profile_enabled, userinfo_enabled)
                        VALUES (
                            ?,
                            COALESCE((SELECT stats_enabled FROM chat_stat_settings WHERE chat_id = ?), 1),
                            COALESCE((SELECT count_media FROM chat_stat_settings WHERE chat_id = ?), 1),
                            COALESCE((SELECT profile_enabled FROM chat_stat_settings WHERE chat_id = ?), 1),
                            ?
                        )
                    """, (chat_id, chat_id, chat_id, chat_id, enabled))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при изменении настройки userinfo_enabled для чата {chat_id}: {e}")
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _set_userinfo_sync)
    
    async def set_user_mention_ping_enabled(self, user_id: int, enabled: bool) -> bool:
        """Включить/выключить кликабельные упоминания (ping) в статистике для пользователя (глобально)"""
        def _set_mention_ping_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Убедимся, что пользователь существует в базе
                    db.execute("""
                        INSERT OR IGNORE INTO users (user_id, mention_ping_enabled)
                        VALUES (?, 1)
                    """, (user_id,))
                    
                    # Обновляем настройку
                    db.execute("""
                        UPDATE users SET mention_ping_enabled = ? WHERE user_id = ?
                    """, (enabled, user_id))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при изменении настройки mention_ping_enabled для пользователя {user_id}: {e}")
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _set_mention_ping_sync)
    
    async def get_user_mention_ping_enabled(self, user_id: int) -> bool:
        """Получить настройку кликабельных упоминаний для пользователя (по умолчанию True)"""
        user = await self.get_user(user_id)
        if user:
            return user.get('mention_ping_enabled', True)
        return True
    
    
    async def get_user_last_message_time(self, chat_id: int, user_id: int) -> str:
        """Получить время последнего сообщения от пользователя"""
        def _get_last_message_time_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT last_message_time FROM user_last_message 
                        WHERE chat_id = ? AND user_id = ?
                    """, (chat_id, user_id))
                    result = cursor.fetchone()
                    return result[0] if result else None
            except Exception as e:
                if self._is_database_corrupted_error(e):
                    logger.critical(f"Обнаружено повреждение базы данных при получении времени последнего сообщения: {e}")
                    self._corruption_detected = True
                else:
                    logger.error(f"Ошибка при получении времени последнего сообщения: {e}")
                return None
        
        result = await asyncio.get_event_loop().run_in_executor(None, _get_last_message_time_sync)
        
        # Автоматическое восстановление при обнаружении повреждения
        if self._corruption_detected and not self._recovery_in_progress:
            await self.auto_recover_if_needed()
        
        return result
    
    async def update_user_last_message_time(self, chat_id: int, user_id: int, message_time: str) -> bool:
        """Обновить время последнего сообщения от пользователя"""
        def _update_last_message_time_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT OR REPLACE INTO user_last_message (chat_id, user_id, last_message_time)
                        VALUES (?, ?, ?)
                    """, (chat_id, user_id, message_time))
                    db.commit()
                    return True
            except Exception as e:
                if self._is_database_corrupted_error(e):
                    logger.critical(f"Обнаружено повреждение базы данных при обновлении времени последнего сообщения: {e}")
                    self._corruption_detected = True
                else:
                    logger.error(f"Ошибка при обновлении времени последнего сообщения: {e}")
                return False
        
        result = await asyncio.get_event_loop().run_in_executor(None, _update_last_message_time_sync)
        
        # Автоматическое восстановление при обнаружении повреждения
        if self._corruption_detected and not self._recovery_in_progress:
            await self.auto_recover_if_needed()
        
        return result
    
    async def get_hourly_stats_today(self, chat_id: int, timezone_offset: int = 3) -> List[Dict[str, int]]:
        """Получение статистики сообщений по часам за сегодня с учетом часового пояса"""
        def _get_hourly_stats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Получаем дату сегодня с учетом часового пояса
                    ts = datetime.utcnow().timestamp() + (timezone_offset * 3600)
                    today = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
                    
                    # Получаем все записи из user_daily_stats за сегодня
                    # Используем данные из user_last_message для получения времени сообщений
                    cursor = db.execute("""
                        SELECT 
                            uds.user_id,
                            uds.message_count,
                            ulm.last_message_time
                        FROM user_daily_stats uds
                        LEFT JOIN user_last_message ulm 
                            ON uds.chat_id = ulm.chat_id AND uds.user_id = ulm.user_id
                        WHERE uds.chat_id = ? AND uds.date = ?
                    """, (chat_id, today))
                    
                    rows = cursor.fetchall()
                    
                    # Инициализируем массив для 24 часов
                    hourly_counts = [0] * 24
                    
                    # Распределяем сообщения по часам на основе времени последнего сообщения
                    for user_id, message_count, last_message_time in rows:
                        if last_message_time:
                            try:
                                # Парсим время последнего сообщения
                                msg_time = datetime.fromisoformat(last_message_time)
                                # Корректируем с учетом часового пояса (если нужно)
                                # Получаем час сообщения
                                hour = msg_time.hour
                                
                                # Распределяем сообщения пользователя по этому часу
                                # Это приблизительная оценка, так как мы знаем только время последнего сообщения
                                hourly_counts[hour] += message_count
                            except (ValueError, TypeError):
                                # Если не удалось распарсить время, пропускаем
                                continue
                        else:
                            # Если нет времени последнего сообщения, распределяем равномерно
                            # Это менее точный вариант, но лучше чем ничего
                            messages_per_hour = message_count // 24
                            remainder = message_count % 24
                            for h in range(24):
                                hourly_counts[h] += messages_per_hour + (1 if h < remainder else 0)
                    
                    # Формируем результат
                    result = []
                    for hour in range(24):
                        result.append({
                            'hour': hour,
                            'count': hourly_counts[hour]
                        })
                    
                    return result
            except Exception as e:
                logger.error(f"Ошибка при получении почасовой статистики для чата {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_hourly_stats_sync)
    
    async def get_chat_users(self, chat_id: int) -> List[dict]:
        """Получить всех пользователей чата с их username из базы данных"""
        def _get_chat_users_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.cursor()
                cursor.execute("""
                    SELECT DISTINCT user_id, username 
                    FROM user_daily_stats 
                    WHERE chat_id = ? AND message_count > 0
                """, (chat_id,))
                return [{'user_id': row[0], 'username': row[1]} for row in cursor.fetchall()]
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_chat_users_sync)
    
    async def search_users_by_name_in_chat(self, chat_id: int, name: str) -> List[Dict[str, Any]]:
        """Поиск пользователей по имени в конкретном чате"""
        def _search_users_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    name_lower = name.lower()
                    # Ищем пользователей, которые когда-либо были в этом чате (через user_daily_stats)
                    # убираем условие message_count > 0, чтобы найти всех пользователей
                    cursor = db.execute("""
                        SELECT DISTINCT u.user_id, u.username, u.first_name, u.last_name, u.is_bot
                        FROM users u
                        WHERE (
                            LOWER(u.first_name) = ? 
                            OR LOWER(u.username) = ?
                            OR LOWER(u.first_name || ' ' || COALESCE(u.last_name, '')) = ?
                        )
                        AND EXISTS (
                            SELECT 1 FROM user_daily_stats uds 
                            WHERE uds.user_id = u.user_id AND uds.chat_id = ?
                        )
                        LIMIT 10
                    """, (name_lower, name_lower, name_lower, chat_id))
                    
                    rows = cursor.fetchall()
                    return [
                        {
                            'user_id': row[0],
                            'username': row[1],
                            'first_name': row[2],
                            'last_name': row[3],
                            'is_bot': bool(row[4])
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при поиске пользователей по имени '{name}' в чате {chat_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _search_users_sync)
    
    async def get_inactive_users(self, days: int = 30) -> List[int]:
        """Найти пользователей, у которых нет записей в user_daily_stats за последние N дней"""
        def _get_inactive_users_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Находим всех пользователей, у которых нет записей в user_daily_stats за последние N дней
                    cursor = db.execute(
                        f"""
                        SELECT DISTINCT u.user_id
                        FROM users u
                        WHERE NOT EXISTS (
                            SELECT 1 
                            FROM user_daily_stats uds 
                            WHERE uds.user_id = u.user_id 
                            AND uds.date >= date('now', '-{days} days')
                            AND uds.message_count > 0
                        )
                        """,
                    )
                    rows = cursor.fetchall()
                    return [row[0] for row in rows]
            except Exception as e:
                logger.error(f"Ошибка при поиске неактивных пользователей: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_inactive_users_sync)
    
    async def get_inactive_chats(self, days: int = 30) -> List[int]:
        """Найти чаты, у которых нет записей в daily_stats за последние N дней"""
        def _get_inactive_chats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Находим все чаты, у которых нет записей в daily_stats за последние N дней
                    cursor = db.execute(
                        f"""
                        SELECT DISTINCT c.chat_id
                        FROM chats c
                        WHERE NOT EXISTS (
                            SELECT 1 
                            FROM daily_stats ds 
                            WHERE ds.chat_id = c.chat_id 
                            AND ds.date >= date('now', '-{days} days')
                            AND ds.message_count > 0
                        )
                        """,
                    )
                    rows = cursor.fetchall()
                    return [row[0] for row in rows]
            except Exception as e:
                logger.error(f"Ошибка при поиске неактивных чатов: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_inactive_chats_sync)
    
    async def delete_user_completely(self, user_id: int) -> bool:
        """Удалить пользователя из всех таблиц основной БД"""
        def _delete_user_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Удаляем в правильном порядке: сначала связанные данные, потом основные записи
                    
                    # 1. Удаляем из chat_moderators (модераторы)
                    db.execute("DELETE FROM chat_moderators WHERE user_id = ?", (user_id,))
                    
                    # 2. Удаляем из chat_join_requests (заявки)
                    db.execute("DELETE FROM chat_join_requests WHERE user_id = ?", (user_id,))
                    
                    # 3. Удаляем из user_chat_meta (метаданные)
                    db.execute("DELETE FROM user_chat_meta WHERE user_id = ?", (user_id,))
                    
                    # 4. Удаляем из user_last_message (время последнего сообщения)
                    db.execute("DELETE FROM user_last_message WHERE user_id = ?", (user_id,))
                    
                    # 5. Удаляем из user_daily_stats (статистика)
                    db.execute("DELETE FROM user_daily_stats WHERE user_id = ?", (user_id,))
                    
                    # 6. Удаляем из rank_permissions (если есть связи через assigned_by)
                    # Сначала удаляем права, где пользователь был назначен модератором
                    # Но rank_permissions связан с chat_id и rank, не с user_id напрямую
                    # Оставляем rank_permissions, так как они связаны с чатами, а не с пользователями
                    
                    # 7. Удаляем из users (основная таблица)
                    db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                    
                    db.commit()
                    logger.info(f"Пользователь {user_id} полностью удален из основной БД")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_user_sync)
    
    async def delete_chat_completely(self, chat_id: int) -> bool:
        """Удалить чат из всех таблиц основной БД"""
        def _delete_chat_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Удаляем в правильном порядке: сначала связанные данные, потом основные записи
                    
                    # 1. Удаляем из chat_moderators (все модераторы чата)
                    db.execute("DELETE FROM chat_moderators WHERE chat_id = ?", (chat_id,))
                    
                    # 2. Удаляем из chat_join_requests (все заявки чата)
                    db.execute("DELETE FROM chat_join_requests WHERE chat_id = ?", (chat_id,))
                    
                    # 3. Удаляем из user_chat_meta (метаданные чата)
                    db.execute("DELETE FROM user_chat_meta WHERE chat_id = ?", (chat_id,))
                    
                    # 4. Удаляем из rank_permissions (права рангов чата)
                    db.execute("DELETE FROM rank_permissions WHERE chat_id = ?", (chat_id,))
                    
                    # 5. Удаляем из chat_stat_settings (настройки статистики)
                    db.execute("DELETE FROM chat_stat_settings WHERE chat_id = ?", (chat_id,))
                    
                    # 6. Удаляем из user_last_message (все записи для чата)
                    db.execute("DELETE FROM user_last_message WHERE chat_id = ?", (chat_id,))
                    
                    # 7. Удаляем из user_daily_stats (все записи чата)
                    db.execute("DELETE FROM user_daily_stats WHERE chat_id = ?", (chat_id,))
                    
                    # 8. Удаляем из daily_stats (статистика чата)
                    db.execute("DELETE FROM daily_stats WHERE chat_id = ?", (chat_id,))
                    
                    # 9. Удаляем из blacklisted_chats (если есть)
                    db.execute("DELETE FROM blacklisted_chats WHERE chat_id = ?", (chat_id,))
                    
                    # 10. Удаляем из chats (основная таблица)
                    db.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
                    
                    db.commit()
                    logger.info(f"Чат {chat_id} полностью удален из основной БД")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении чата {chat_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_chat_sync)
    
    async def cleanup_inactive_users_and_chats(self, days: int = 30) -> Dict[str, int]:
        """
        Основная функция очистки неактивных пользователей и чатов
        Координирует удаление из всех баз данных
        
        Returns:
            Dict с статистикой: {'users_deleted': int, 'chats_deleted': int, 'users_failed': int, 'chats_failed': int}
        """
        # Импортируем здесь, чтобы избежать циклических зависимостей
        from reputation_db import reputation_db
        from network_db import network_db
        
        stats = {
            'users_deleted': 0,
            'chats_deleted': 0,
            'users_failed': 0,
            'chats_failed': 0
        }
        
        try:
            # 1. Находим неактивных пользователей и чаты
            logger.info(f"Поиск неактивных пользователей и чатов (неактивность > {days} дней)...")
            inactive_users = await self.get_inactive_users(days)
            inactive_chats = await self.get_inactive_chats(days)
            
            logger.info(f"Найдено неактивных пользователей: {len(inactive_users)}, чатов: {len(inactive_chats)}")
            
            # 2. Удаляем неактивных пользователей
            if inactive_users:
                logger.info(f"🧹 Начинаю удаление {len(inactive_users)} неактивных пользователей...")
            for user_id in inactive_users:
                try:
                    # Удаляем из других БД
                    await reputation_db.delete_user_reputation(user_id)
                    
                    # Удаляем из основной БД
                    if await self.delete_user_completely(user_id):
                        stats['users_deleted'] += 1
                    else:
                        stats['users_failed'] += 1
                except Exception as e:
                    logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")
                    stats['users_failed'] += 1
            
            # 3. Удаляем неактивные чаты из сетей
            if inactive_chats:
                logger.info(f"🌐 Удаляю {len(inactive_chats)} неактивных чатов из сетей...")
                await network_db.cleanup_inactive_chats_from_networks(inactive_chats)
            
            # 4. Удаляем неактивные чаты из основной БД
            if inactive_chats:
                logger.info(f"🗑️ Начинаю удаление {len(inactive_chats)} неактивных чатов из основной БД...")
            for chat_id in inactive_chats:
                try:
                    if await self.delete_chat_completely(chat_id):
                        stats['chats_deleted'] += 1
                    else:
                        stats['chats_failed'] += 1
                except Exception as e:
                    logger.error(f"Ошибка при удалении чата {chat_id}: {e}")
                    stats['chats_failed'] += 1
            
            logger.info(
                f"Очистка завершена: "
                f"пользователей удалено: {stats['users_deleted']}, "
                f"чатов удалено: {stats['chats_deleted']}, "
                f"ошибок пользователей: {stats['users_failed']}, "
                f"ошибок чатов: {stats['chats_failed']}"
            )
            
        except Exception as e:
            logger.error(f"Критическая ошибка при очистке неактивных пользователей и чатов: {e}")
        
        return stats
    
    async def get_user_top_chats(self, user_id: int, limit: int = 3) -> List[Dict]:
        """Получить топ чатов пользователя по активности за последние 6 дней"""
        def _get_user_top_chats_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute("""
                    SELECT 
                        uds.chat_id,
                        c.chat_title,
                        SUM(uds.message_count) as total_messages
                    FROM user_daily_stats uds
                    LEFT JOIN chats c ON uds.chat_id = c.chat_id
                    WHERE uds.user_id = ? 
                    AND uds.date >= date('now', '-6 days')
                    GROUP BY uds.chat_id, c.chat_title
                    ORDER BY total_messages DESC
                    LIMIT ?
                """, (user_id, limit))
                
                return [{
                    'chat_id': row[0],
                    'chat_title': row[1] or f"Чат {row[0]}",
                    'total_messages': row[2]
                } for row in cursor.fetchall()]
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_top_chats_sync)
    
    async def get_common_chats(self, user_id_1: int, user_id_2: int) -> List[Dict]:
        """Получить общие чаты двух пользователей"""
        def _get_common_chats_sync():
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute("""
                    SELECT DISTINCT 
                        c.chat_id, 
                        c.chat_title
                    FROM chats c
                    WHERE c.chat_id IN (
                        SELECT DISTINCT chat_id 
                        FROM user_daily_stats 
                        WHERE user_id = ? AND message_count > 0
                    )
                    AND c.chat_id IN (
                        SELECT DISTINCT chat_id 
                        FROM user_daily_stats 
                        WHERE user_id = ? AND message_count > 0
                    )
                    ORDER BY c.chat_title
                """, (user_id_1, user_id_2))
                
                return [{
                    'chat_id': row[0],
                    'chat_title': row[1] or f"Чат {row[0]}"
                } for row in cursor.fetchall()]
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_common_chats_sync)


# Глобальный экземпляр базы данных
db = Database()
