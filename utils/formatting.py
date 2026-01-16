"""
Функции для форматирования текста, упоминаний, репутации
"""
import bisect
import random
from typing import Optional

def get_user_mention_html(user, enable_link: bool = True) -> str:
    """
    Генерирует HTML-упоминание пользователя с кликабельной ссылкой на профиль
    - Для пользователей с username: использует https://t.me/username
    - Для пользователей без username: использует tg://user?id=user_id
    - Fallback: ID пользователя
    
    Принимает либо types.User объект, либо словарь с полями user_id, username, first_name
    Если enable_link=False, возвращает просто имя без ссылки
    """
    # Поддержка как User объекта, так и словаря
    if isinstance(user, dict):
        user_id = user.get('user_id')
        username = user.get('username')
        first_name = user.get('first_name', '') or ""
    else:
        user_id = user.id
        username = user.username
        first_name = user.first_name or ""
    
    # Определяем отображаемое имя
    if first_name:
        display_name = first_name
    elif username:
        display_name = username
    else:
        display_name = f"ID{user_id}"
    
    # Если ссылки отключены, возвращаем просто имя
    if not enable_link:
        return display_name
    
    # Формируем ссылку
    if username:
        # Пользователь с username - обычная ссылка на профиль
        return f"<a href='https://t.me/{username}'>{display_name}</a>"
    elif first_name:
        # Пользователь без username - используем tg://user?id=
        return f"<a href='tg://user?id={user_id}'>{first_name}</a>"
    else:
        # Fallback - ID пользователя
        return f"<a href='tg://user?id={user_id}'>ID{user_id}</a>"


def parse_command_with_reason(text: str) -> tuple[str, str]:
    """
    Парсит команду с причиной на новой строке
    Возвращает (команда_с_аргументами, причина)
    """
    lines = text.strip().split('\n', 1)
    command_line = lines[0]
    reason = lines[1].strip() if len(lines) > 1 else None
    return command_line, reason


def get_reputation_emoji(reputation: int) -> str:
    """Получить эмодзи-индикатор для репутации"""
    thresholds = [30, 50, 70, 90]
    emojis = ["💀", "🔴", "⚠️", "✅", "🌟"]
    return emojis[bisect.bisect_right(thresholds, reputation)]


def get_reputation_progress_bar(reputation: int) -> str:
    """Получить прогресс-бар для репутации"""
    filled = int(reputation / 10)
    empty = 10 - filled
    return "▰" * filled + "▱" * empty


def format_mute_duration(duration_seconds: int) -> str:
    """Форматирование времени мута в читаемый вид"""
    units = [(86400, "д"), (3600, "ч"), (60, "м"), (1, "с")]
    parts = []
    remaining = duration_seconds
    for divisor, suffix in units:
        if remaining >= divisor:
            value, remaining = divmod(remaining, divisor)
            parts.append(f"{value}{suffix}")
            if len(parts) == 2:
                break
    return " ".join(parts) or "0с"


def parse_mute_duration(time_str: str) -> Optional[int]:
    """
    Парсит строку времени в секунды
    Примеры: "10 часов", "30 минут", "5 дней", "60 секунд"
    Возвращает количество секунд или None при ошибке
    """
    import re
    
    # Словарь единиц времени -> множитель в секундах
    time_units = {
        **dict.fromkeys(['секунд', 'секунды', 'секунду', 'сек', 'с'], 1),
        **dict.fromkeys(['минут', 'минуты', 'минуту', 'мин', 'м'], 60),
        **dict.fromkeys(['часов', 'часа', 'час', 'ч'], 3600),
        **dict.fromkeys(['дней', 'дня', 'день', 'д'], 86400),
    }
    
    # Убираем лишние пробелы и приводим к нижнему регистру
    time_str = time_str.strip().lower()
    
    # Регулярное выражение для поиска числа и единицы времени
    match = re.match(r'(\d+)\s*([а-яё]+)', time_str)
    if not match:
        return None
    
    number = int(match.group(1))
    unit = match.group(2)
    
    # Возвращаем результат или None если единица неизвестна
    multiplier = time_units.get(unit)
    return number * multiplier if multiplier else None


async def get_philosophical_access_denied_message():
    """Получить философское сообщение об отказе в доступе"""
    philosophical_messages = [
        "🌌 Власть — это не то, что можно взять просто так. Она дается тем, кто достоин.",
        "🔒 Только тот, кто имеет право, может открыть эту дверь.",
        "⚡ Сила приходит не от желания, а от авторитета.",
        "🌊 Только капитан может управлять кораблем.",
        "🏰 Ключи от крепости есть только у её защитников.",
        "🎭 Только режиссер может изменить сценарий.",
        "🌅 Только тот, кто встречал рассвет, может решить о закате.",
        "🦅 Только орел может парить в небесах власти.",
        "⚔️ Меч правосудия держит только тот, кто заслужил его.",
        "🔮 Видение будущего доступно только избранным."
    ]
    return random.choice(philosophical_messages)

