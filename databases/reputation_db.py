"""
Модуль для работы с базой данных репутации пользователей
Отдельная БД для отслеживания репутации и недавних наказаний
"""
import bisect
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

class ReputationDatabase:
    """Класс для работы с базой данных репутации"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(BASE_PATH / 'data' / 'reputation.db')
        self.db_path = db_path
        # Создаем директорию data если её нет
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        def _init_sync():
            with sqlite3.connect(self.db_path) as db:
                # Таблица репутации пользователей
                db.execute("""
                    CREATE TABLE IF NOT EXISTS user_reputation (
                        user_id INTEGER PRIMARY KEY,
                        reputation INTEGER DEFAULT 100,
                        last_updated TEXT
                    )
                """)
                
                # Таблица недавних наказаний (за последние 3 дня)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS recent_punishments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        punishment_type TEXT,
                        punishment_date TEXT,
                        duration_seconds INTEGER
                    )
                """)
                
                # Создаем индексы для оптимизации
                db.execute("CREATE INDEX IF NOT EXISTS idx_reputation_user ON user_reputation (user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_recent_punishments_user ON recent_punishments (user_id)")
                db.execute("CREATE INDEX IF NOT EXISTS idx_recent_punishments_date ON recent_punishments (punishment_date)")
                
                db.commit()
                logger.info("База данных репутации инициализирована")
        
        await asyncio.get_event_loop().run_in_executor(None, _init_sync)
    
    async def get_user_reputation(self, user_id: int) -> int:
        """Получить текущий рейтинг пользователя (по умолчанию 100)"""
        def _get_reputation_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT reputation FROM user_reputation WHERE user_id = ?
                    """, (user_id,))
                    row = cursor.fetchone()
                    return row[0] if row else 100
            except Exception as e:
                logger.error(f"Ошибка при получении репутации пользователя {user_id}: {e}")
                return 100
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_reputation_sync)
    
    async def update_reputation(self, user_id: int, change: int) -> bool:
        """Изменить рейтинг пользователя (с ограничением 0-100)"""
        def _update_reputation_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Получаем текущий рейтинг
                    cursor = db.execute("""
                        SELECT reputation FROM user_reputation WHERE user_id = ?
                    """, (user_id,))
                    row = cursor.fetchone()
                    current_reputation = row[0] if row else 100
                    
                    # Вычисляем новый рейтинг с ограничениями
                    new_reputation = max(0, min(100, current_reputation + change))
                    
                    # Обновляем или создаем запись
                    db.execute("""
                        INSERT OR REPLACE INTO user_reputation 
                        (user_id, reputation, last_updated)
                        VALUES (?, ?, ?)
                    """, (user_id, new_reputation, datetime.now().isoformat()))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при обновлении репутации пользователя {user_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _update_reputation_sync)
    
    async def add_recent_punishment(self, user_id: int, punishment_type: str, duration_seconds: Optional[int] = None) -> bool:
        """Добавить недавнее наказание"""
        def _add_punishment_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    db.execute("""
                        INSERT INTO recent_punishments 
                        (user_id, punishment_type, punishment_date, duration_seconds)
                        VALUES (?, ?, ?, ?)
                    """, (user_id, punishment_type, datetime.now().isoformat(), duration_seconds))
                    
                    db.commit()
                    return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении наказания для пользователя {user_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _add_punishment_sync)
    
    async def get_recent_punishments(self, user_id: int, days: int = 3) -> List[Dict[str, Any]]:
        """Получить наказания за последние N дней"""
        def _get_punishments_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
                    
                    cursor = db.execute("""
                        SELECT punishment_type, punishment_date, duration_seconds
                        FROM recent_punishments
                        WHERE user_id = ? AND punishment_date >= ?
                        ORDER BY punishment_date DESC
                    """, (user_id, cutoff_date))
                    
                    rows = cursor.fetchall()
                    return [
                        {
                            'punishment_type': row[0],
                            'punishment_date': row[1],
                            'duration_seconds': row[2]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении наказаний пользователя {user_id}: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_punishments_sync)
    
    async def get_recent_punishment_stats(self, user_id: int, days: int = 3) -> Dict[str, int]:
        """Получить статистику наказаний за последние N дней"""
        def _get_stats_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
                    
                    cursor = db.execute("""
                        SELECT punishment_type, COUNT(*) as count
                        FROM recent_punishments
                        WHERE user_id = ? AND punishment_date >= ?
                        GROUP BY punishment_type
                    """, (user_id, cutoff_date))
                    
                    rows = cursor.fetchall()
                    stats = {}
                    for row in rows:
                        stats[row[0]] = row[1]
                    
                    # Инициализируем все типы наказаний нулями
                    all_types = ['warn', 'mute', 'kick', 'ban']
                    for punishment_type in all_types:
                        if punishment_type not in stats:
                            stats[punishment_type] = 0
                    
                    return stats
            except Exception as e:
                logger.error(f"Ошибка при получении статистики наказаний пользователя {user_id}: {e}")
                return {'warn': 0, 'mute': 0, 'kick': 0, 'ban': 0}
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_stats_sync)
    
    async def cleanup_old_punishments(self, days: int = 7) -> int:
        """Удалить наказания старше N дней (по умолчанию 7 дней)"""
        def _cleanup_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
                    
                    cursor = db.execute("""
                        DELETE FROM recent_punishments 
                        WHERE punishment_date < ?
                    """, (cutoff_date,))
                    
                    deleted_count = cursor.rowcount
                    db.commit()
                    
                    if deleted_count > 0:
                        logger.info(f"Очищено {deleted_count} старых наказаний из базы репутации")
                    
                    return deleted_count
            except Exception as e:
                logger.error(f"Ошибка при очистке старых наказаний: {e}")
                return 0
        
        return await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)
    
    def calculate_reputation_penalty(self, punishment_type: str, duration_seconds: Optional[int] = None) -> int:
        """Рассчитать штраф за наказание"""
        # Базовые штрафы для типов наказаний
        base_penalties = {'warn': -2, 'kick': -8, 'ban': -15}
        
        if punishment_type == 'mute':
            if duration_seconds is None:
                return -3  # По умолчанию для мута без указания времени
            days = duration_seconds / 86400
            # Пороги: <=1 день -> -3, <=3 дня -> -5, <=7 дней -> -7, >7 дней -> -10
            thresholds = [1, 3, 7]
            penalties = [-3, -5, -7, -10]
            return penalties[bisect.bisect_left(thresholds, days)]
        
        if punishment_type == 'ban':
            return -25 if duration_seconds is None else -15
        
        return base_penalties.get(punishment_type, 0)
    
    async def get_all_users_with_reputation(self) -> List[Dict[str, Any]]:
        """Получить всех пользователей с репутацией (для восстановления)"""
        def _get_all_users_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    cursor = db.execute("""
                        SELECT user_id, reputation FROM user_reputation
                        WHERE reputation < 100
                    """)
                    
                    rows = cursor.fetchall()
                    return [
                        {
                            'user_id': row[0],
                            'reputation': row[1]
                        }
                        for row in rows
                    ]
            except Exception as e:
                logger.error(f"Ошибка при получении всех пользователей с репутацией: {e}")
                return []
        
        return await asyncio.get_event_loop().run_in_executor(None, _get_all_users_sync)
    
    async def delete_user_reputation(self, user_id: int) -> bool:
        """Удалить репутацию и наказания пользователя"""
        def _delete_sync():
            try:
                with sqlite3.connect(self.db_path) as db:
                    # Удаляем из recent_punishments (все записи пользователя)
                    db.execute("DELETE FROM recent_punishments WHERE user_id = ?", (user_id,))
                    
                    # Удаляем из user_reputation
                    db.execute("DELETE FROM user_reputation WHERE user_id = ?", (user_id,))
                    
                    db.commit()
                    logger.info(f"Репутация пользователя {user_id} удалена")
                    return True
            except Exception as e:
                logger.error(f"Ошибка при удалении репутации пользователя {user_id}: {e}")
                return False
        
        return await asyncio.get_event_loop().run_in_executor(None, _delete_sync)


# Глобальный экземпляр базы данных репутации
reputation_db = ReputationDatabase()
