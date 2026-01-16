"""
Модуль для работы с базой данных сетей чатов
"""
import sqlite3
import asyncio
import logging
import random
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

class NetworkDatabase:
    """Класс для работы с базой данных сетей чатов"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(BASE_PATH / 'data' / 'network.db')
        self.db_path = db_path
        # Создаем директорию data если её нет
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        def _init_sync():
            with sqlite3.connect(self.db_path) as db:
                # Проверяем, существует ли таблица с AUTOINCREMENT
                cursor = db.execute("""
                    SELECT sql FROM sqlite_master 
                    WHERE type='table' AND name='chat_networks'
                """)
                table_sql = cursor.fetchone()
                
                # Если таблица существует с AUTOINCREMENT, пересоздаем её
                if table_sql and 'AUTOINCREMENT' in table_sql[0]:
                    logger.info("Миграция таблицы chat_networks для переиспользования ID...")
                    
                    # Создаем временную таблицу
                    db.execute("""
                        CREATE TABLE chat_networks_new (
                            network_id INTEGER PRIMARY KEY,
                            owner_id INTEGER,
                            created_date TEXT
                        )
                    """)
                    
                    # Копируем данные
                    db.execute("""
                        INSERT INTO chat_networks_new (network_id, owner_id, created_date)
                        SELECT network_id, owner_id, created_date FROM chat_networks
                    """)
                    
                    # Удаляем старую таблицу
                    db.execute("DROP TABLE chat_networks")
                    
                    # Переименовываем новую таблицу
                    db.execute("ALTER TABLE chat_networks_new RENAME TO chat_networks")
                    
                    logger.info("Миграция завершена")
                
                # Таблица сетей чатов
                db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_networks (
                        network_id INTEGER PRIMARY KEY,
                        owner_id INTEGER,
                        created_date TEXT
                    )
                """)
                
                # Таблица чатов в сетях
                db.execute("""
                    CREATE TABLE IF NOT EXISTS network_chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        network_id INTEGER,
                        chat_id INTEGER,
                        joined_date TEXT,
                        is_primary BOOLEAN DEFAULT 0,
                        priority INTEGER DEFAULT 0,
                        FOREIGN KEY (network_id) REFERENCES chat_networks (network_id)
                    )
                """)
                
                # Проверяем, нужно ли добавить поле priority в network_chats (после создания таблицы)
                try:
                    cursor = db.execute("PRAGMA table_info(network_chats)")
                    columns = [column[1] for column in cursor.fetchall()]
                    if 'priority' not in columns:
                        logger.info("Добавление поля priority в таблицу network_chats...")
                        db.execute("ALTER TABLE network_chats ADD COLUMN priority INTEGER DEFAULT 0")
                        db.commit()
                        logger.info("Поле priority добавлено")
                except sqlite3.OperationalError:
                    # Таблица еще не существует, это нормально - она уже создана выше
                    pass
                
                # Таблица кодов для связывания
                db.execute("""
                    CREATE TABLE IF NOT EXISTS network_codes (
                        code TEXT PRIMARY KEY,
                        network_id INTEGER,
                        code_type TEXT,
                        created_date TEXT,
                        expires_at TEXT,
                        used BOOLEAN DEFAULT 0,
                        FOREIGN KEY (network_id) REFERENCES chat_networks (network_id)
                    )
                """)
                
                # Создаем индексы для оптимизации
                db.execute("CREATE INDEX IF NOT EXISTS idx_network_chats_network_id ON network_chats (network_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_network_chats_chat_id ON network_chats (chat_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_network_codes_expires ON network_codes (expires_at)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_network_codes_used ON network_codes (used)")
                
                db.commit()
                logger.info("База данных сетей чатов инициализирована")
        
        await asyncio.get_event_loop().run_in_executor(None, _init_sync)
    
    async def create_network(self, owner_id: int) -> int:
        """Создание новой сети чатов"""
        def _create_network_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Получаем максимальный номер сетки
                    cursor = db.execute("SELECT MAX(network_id) FROM chat_networks")
                    max_id = cursor.fetchone()[0]
                    
                    # Следующий номер = максимальный + 1 (или 1, если сеток нет)
                    network_id = (max_id or 0) + 1
                    
                    db.execute("""
                        INSERT INTO chat_networks (network_id, owner_id, created_date)
                        VALUES (?, ?, ?)
                    """, (network_id, owner_id, datetime.now().isoformat()))
                    db.commit()
                    return network_id
            except Exception as e:
                logger.error(f"Ошибка при создании сети для владельца {owner_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _create_network_sync)
    
    async def add_chat_to_network(self, network_id: int, chat_id: int, is_primary: bool = False) -> bool:
        """Добавление чата в сеть"""
        def _add_chat_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO network_chats (network_id, chat_id, joined_date, is_primary)
                        VALUES (?, ?, ?, ?)
                    """, (network_id, chat_id, datetime.now().isoformat(), is_primary))
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении чата {chat_id} в сеть {network_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_chat_sync)
    
    async def remove_chat_from_network(self, chat_id: int) -> bool:
        """Удаление чата из сети"""
        def _remove_chat_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM network_chats WHERE chat_id = ?
                    """, (chat_id,))
                    db.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Ошибка при удалении чата {chat_id} из сети: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _remove_chat_sync)
    
    async def get_network_by_chat(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получение сети по ID чата"""
        def _get_network_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT cn.network_id, cn.owner_id, cn.created_date
                        FROM chat_networks cn
                        JOIN network_chats nc ON cn.network_id = nc.network_id
                        WHERE nc.chat_id = ?
                    """, (chat_id,))
                    row = cursor.fetchone()
                    if row:
                        return {
                            'network_id': row[0],
                            'owner_id': row[1],
                            'created_date': row[2]
                        }
                    return None
            except Exception as e:
                logger.error(f"Ошибка при получении сети для чата {chat_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_network_sync)
    
    async def get_network_chats(self, network_id: int) -> List[Dict[str, Any]]:
        """Получение всех чатов в сети"""
        def _get_network_chats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT chat_id, joined_date, is_primary
                        FROM network_chats
                        WHERE network_id = ?
                        ORDER BY joined_date ASC
                    """, (network_id,))
                    rows = cursor.fetchall()
                    return [
                        {
                            'chat_id': row[0],
                            'joined_date': row[1],
                            'is_primary': bool(row[2])
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении чатов сети {network_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_network_chats_sync)
    
    async def get_user_networks(self, owner_id: int) -> List[Dict[str, Any]]:
        """Получение всех сетей пользователя"""
        def _get_user_networks_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT network_id, created_date
                        FROM chat_networks
                        WHERE owner_id = ?
                        ORDER BY created_date DESC
                    """, (owner_id,))
                    rows = cursor.fetchall()
                    return [
                        {
                            'network_id': row[0],
                            'created_date': row[1]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении сетей пользователя {owner_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_user_networks_sync)
    
    async def get_network_chat_count(self, network_id: int) -> int:
        """Получение количества чатов в сети"""
        def _get_chat_count_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT COUNT(*) FROM network_chats WHERE network_id = ?
                    """, (network_id,))
                    return cursor.fetchone()[0]
            except Exception as e:
                logger.error(f"Ошибка при получении количества чатов в сети {network_id}: {e}")
                return 0
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_chat_count_sync)
    
    async def delete_network(self, network_id: int) -> bool:
        """Удаление сети с переупорядочиванием номеров"""
        def _delete_network_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Получаем максимальный номер сетки
                    cursor = db.execute("SELECT MAX(network_id) FROM chat_networks")
                    max_id = cursor.fetchone()[0]
                    
                    # Если удаляемая сетка - не максимальная, нужно переупорядочить
                    if network_id < max_id:
                        # Находим сетку с максимальным номером
                        cursor = db.execute("""
                            SELECT network_id, owner_id, created_date 
                            FROM chat_networks 
                            WHERE network_id = ?
                        """, (max_id,))
                        max_network = cursor.fetchone()
                        
                        if max_network:
                            # Удаляем старую запись с максимальным номером
                            db.execute("DELETE FROM chat_networks WHERE network_id = ?", (max_id,))
                            
                            # Создаем новую запись с номером удаляемой сетки
                            db.execute("""
                                INSERT INTO chat_networks (network_id, owner_id, created_date)
                                VALUES (?, ?, ?)
                            """, (network_id, max_network[1], max_network[2]))
                            
                            # Обновляем все связанные записи
                            db.execute("""
                                UPDATE network_chats 
                                SET network_id = ? 
                                WHERE network_id = ?
                            """, (network_id, max_id))
                            
                            db.execute("""
                                UPDATE network_codes 
                                SET network_id = ? 
                                WHERE network_id = ?
                            """, (network_id, max_id))
                            
                            logger.info(f"Сетка #{max_id} переехала на место #{network_id}")
                    else:
                        # Если удаляем максимальную сетку, просто удаляем
                        db.execute("DELETE FROM network_chats WHERE network_id = ?", (network_id,))
                        db.execute("DELETE FROM network_codes WHERE network_id = ?", (network_id,))
                        db.execute("DELETE FROM chat_networks WHERE network_id = ?", (network_id,))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении сети {network_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_network_sync)
    
    async def generate_code(self, network_id: int, code_type: str) -> Optional[str]:
        """Генерация кода для связывания чатов"""
        def _generate_code_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Очищаем истекшие коды
                    db.execute("""
                        DELETE FROM network_codes 
                        WHERE expires_at < datetime('now')
                    """)
                    
                    # Генерируем код
                    if code_type == 'create':
                        # 4-значный код для создания сети
                        code = str(random.randint(1000, 9999))
                    else:  # add
                        # 2-значный код для добавления чата
                        code = str(random.randint(1, 99)).zfill(2)
                    
                    # Проверяем уникальность
                    cursor = db.execute("SELECT code FROM network_codes WHERE code = ?", (code,))
                    attempts = 0
                    while cursor.fetchone() and attempts < 100:
                        if code_type == 'create':
                            code = str(random.randint(1000, 9999))
                        else:
                            code = str(random.randint(1, 99)).zfill(2)
                        cursor = db.execute("SELECT code FROM network_codes WHERE code = ?", (code,))
                        attempts += 1
                    
                    if attempts >= 100:
                        return None  # Не удалось сгенерировать уникальный код
                    
                    # Сохраняем код
                    expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()
                    db.execute("""
                        INSERT INTO network_codes (code, network_id, code_type, created_date, expires_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (code, network_id, code_type, datetime.now().isoformat(), expires_at))
                    db.commit()
                    return code
            except Exception as e:
                logger.error(f"Ошибка при генерации кода для сети {network_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _generate_code_sync)
    
    async def validate_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Проверка кода (без пометки как использованный)"""
        def _validate_code_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT network_id, code_type, expires_at, used
                        FROM network_codes
                        WHERE code = ?
                    """, (code,))
                    row = cursor.fetchone()
                    
                    if not row:
                        return None
                    
                    network_id, code_type, expires_at, used = row
                    
                    # Проверяем, не истек ли код
                    if datetime.now().isoformat() > expires_at:
                        # Удаляем истекший код
                        db.execute("DELETE FROM network_codes WHERE code = ?", (code,))
                        db.commit()
                        return None
                    
                    # Для кодов типа 'add' проверяем, не использован ли код
                    if code_type == 'add' and used:
                        return None
                    
                    # Для кодов типа 'create' не проверяем used, так как они многоразовые
                    
                    return {
                        'network_id': network_id,
                        'code_type': code_type
                    }
            except Exception as e:
                logger.error(f"Ошибка при проверке кода {code}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _validate_code_sync)
    
    async def mark_code_as_used(self, code: str) -> bool:
        """Пометка кода как использованного"""
        def _mark_used_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("UPDATE network_codes SET used = 1 WHERE code = ?", (code,))
                    db.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Ошибка при пометке кода {code} как использованного: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _mark_used_sync)
    
    async def cleanup_expired_codes(self) -> int:
        """Очистка истекших кодов"""
        def _cleanup_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        DELETE FROM network_codes 
                        WHERE expires_at < datetime('now')
                    """)
                    db.commit()
                    return cursor.rowcount
            except Exception as e:
                logger.error(f"Ошибка при очистке истекших кодов: {e}")
                return 0
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def is_chat_in_network(self, chat_id: int) -> bool:
        """Проверка, находится ли чат в какой-либо сети"""
        def _check_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT 1 FROM network_chats WHERE chat_id = ?
                    """, (chat_id,))
                    return cursor.fetchone() is not None
            except Exception as e:
                logger.error(f"Ошибка при проверке чата {chat_id} в сети: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _check_sync)
    
    async def set_chat_priority(self, network_id: int, chat_id: int, priority: int) -> bool:
        """Установка приоритета чата в сети"""
        def _set_priority_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        UPDATE network_chats 
                        SET priority = ? 
                        WHERE network_id = ? AND chat_id = ?
                    """, (priority, network_id, chat_id))
                    db.commit()
                    return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Ошибка при установке приоритета чата {chat_id} в сети {network_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _set_priority_sync)
    
    async def get_network_chats_sorted(self, network_id: int, sort_by: str = 'priority') -> List[Dict[str, Any]]:
        """Получение чатов сети с сортировкой"""
        def _get_chats_sorted_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    if sort_by == 'priority':
                        # Сортировка по приоритету (больше = выше)
                        cursor = db.execute("""
                            SELECT chat_id, joined_date, is_primary, priority
                            FROM network_chats
                            WHERE network_id = ?
                            ORDER BY priority DESC, joined_date ASC
                        """, (network_id,))
                    elif sort_by == 'activity':
                        # Сортировка по активности (нужно будет добавить логику)
                        cursor = db.execute("""
                            SELECT chat_id, joined_date, is_primary, priority
                            FROM network_chats
                            WHERE network_id = ?
                            ORDER BY priority DESC, joined_date ASC
                        """, (network_id,))
                    else:
                        # Сортировка по дате добавления
                        cursor = db.execute("""
                            SELECT chat_id, joined_date, is_primary, priority
                            FROM network_chats
                            WHERE network_id = ?
                            ORDER BY joined_date ASC
                        """, (network_id,))
                    
                    return [{
                        'chat_id': row[0],
                        'joined_date': row[1],
                        'is_primary': bool(row[2]),
                        'priority': row[3]
                    } for row in cursor.fetchall()]
            except Exception as e:
                logger.error(f"Ошибка при получении отсортированных чатов сети {network_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_chats_sorted_sync)
    
    async def get_network_owner(self, network_id: int) -> Optional[int]:
        """Получение владельца сети"""
        def _get_owner_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT owner_id FROM chat_networks WHERE network_id = ?
                    """, (network_id,))
                    row = cursor.fetchone()
                    return row[0] if row else None
            except Exception as e:
                logger.error(f"Ошибка при получении владельца сети {network_id}: {e}")
                return None
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_owner_sync)
    
    async def cleanup_inactive_chats_from_networks(self, inactive_chat_ids: List[int]) -> bool:
        """Удалить неактивные чаты из сетей"""
        def _cleanup_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    if not inactive_chat_ids:
                        return True
                    
                    # Создаем плейсхолдеры для IN запроса
                    placeholders = ','.join('?' * len(inactive_chat_ids))
                    
                    # Удаляем неактивные чаты из network_chats
                    cursor = db.execute(
                        f"DELETE FROM network_chats WHERE chat_id IN ({placeholders})",
                        inactive_chat_ids
                    )
                    deleted_count = cursor.rowcount
                    
                    db.commit()
                    if deleted_count > 0:
                        logger.info(f"Удалено {deleted_count} неактивных чатов из сетей")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении неактивных чатов из сетей: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    async def remove_chat_from_all_networks(self, chat_id: int) -> bool:
        """Удалить чат из всех сетей"""
        def _remove_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("DELETE FROM network_chats WHERE chat_id = ?", (chat_id,))
                    deleted_count = cursor.rowcount
                    db.commit()
                    if deleted_count > 0:
                        logger.info(f"Чат {chat_id} удален из {deleted_count} сетей")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении чата {chat_id} из сетей: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _remove_sync)



# Глобальный экземпляр базы данных сетей
network_db = NetworkDatabase()
