"""
Модуль для управления алиасами команд
Содержит словарь соответствий русских команд английским
"""

# Словарь алиасов: русская_команда -> английская_команда
COMMAND_ALIASES = {
    # Статистика и топ
    "стата": "top",
    "топ": "top",
    "стата вся": "topall",
    "статистика вся": "topall",
    
    # Профиль
    "профиль": "myprofile",
    "мой профиль": "myprofile",
    "кто ты": "myprofile",
    
    # Настройки
    "настройки": "settings",
    "конфиг": "settings",
    "правила": "rules",
    
    # Модерация
    "мут": "mute",
    "размут": "unmute",
    "кик": "kick",
    "бан": "ban",
    "разбан": "unban",
    "варн": "warn",
    "анварн": "unwarn",

    # Ранги/модераторы (alias к /ap и /unap)
    "назначить": "ap",
    "снять": "unap",
    "remove": "unap",

    # Служебное
    "кто админ": "staff",
    "история наказаний": "punishhistory",
    
    # Защита от рейдов
    "антирейд": "raidprotection",
    "настройки антирейд": "raidprotection",
}

# Специальные алиасы, не входящие в основной словарь
SPECIAL_ALIASES = {"кто я": "myprofile_self", "снять меня": "selfdemote", "снять себя": "selfdemote"}


def _resolve_alias(text: str) -> str | None:
    """
    Внутренняя функция для разрешения алиаса
    
    Args:
        text: Очищенный текст (lowercase, stripped)
        
    Returns:
        Английская команда или None
    """
    # Специальные случаи
    if text in SPECIAL_ALIASES:
        return SPECIAL_ALIASES[text]
    
    # Проверка "кто ты" с аргументами
    if text.startswith("кто ты"):
        return "myprofile"
    
    # Точное совпадение
    if text in COMMAND_ALIASES:
        return COMMAND_ALIASES[text]
    
    # Первое слово как алиас (команда с аргументами)
    words = text.split()
    return COMMAND_ALIASES.get(words[0]) if words else None


def get_command_alias(text: str) -> str | None:
    """
    Получить английскую команду по русскому алиасу
    
    Args:
        text: Текст сообщения
        
    Returns:
        Английская команда или None если алиас не найден
    """
    return _resolve_alias(text.strip().lower())


def is_command_alias(text: str) -> bool:
    """
    Проверить, является ли текст алиасом команды
    
    Args:
        text: Текст сообщения
        
    Returns:
        True если это алиас команды, False иначе
    """
    if not text:
        return False
    
    clean_text = text.strip().lower()
    
    # Проверяем с префиксом "пиксель"
    if clean_text.startswith("пиксель"):
        clean_text = clean_text[7:].strip()
    
    return _resolve_alias(clean_text) is not None

def get_all_aliases() -> dict[str, str]:
    """
    Получить все алиасы команд
    
    Returns:
        Словарь всех алиасов
    """
    return COMMAND_ALIASES.copy()

def add_alias(russian_command: str, english_command: str) -> None:
    """
    Добавить новый алиас команды
    
    Args:
        russian_command: Русская команда
        english_command: Английская команда
    """
    COMMAND_ALIASES[russian_command.lower()] = english_command.lower()

def remove_alias(russian_command: str) -> bool:
    """
    Удалить алиас команды
    
    Args:
        russian_command: Русская команда для удаления
        
    Returns:
        True если алиас был удален, False если не найден
    """
    if russian_command.lower() in COMMAND_ALIASES:
        del COMMAND_ALIASES[russian_command.lower()]
        return True
    return False
