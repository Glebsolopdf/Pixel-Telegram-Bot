"""
Конфигурация бота Pixel Utils Bot
"""
import os
from pathlib import Path

# Загружаем переменные окружения из .env файла, если он существует
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv не установлен, используем только системные переменные окружения
    pass

# Токен бота (обязательно)
# Можно задать через переменную окружения BOT_TOKEN или здесь
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Дополнительные настройки (опциональные)
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
CLEANUP_PYCACHE_ON_SHUTDOWN = os.getenv("CLEANUP_PYCACHE_ON_SHUTDOWN", "True").lower() == "true"

# Автоматическое определение базового пути
def safe_path_exists(path):
    """Безопасно проверяет существование пути, обрабатывая PermissionError"""
    try:
        return path.exists()
    except PermissionError:
        return False

def get_base_path():
    """Определяет базовый путь к директории проекта"""
    # Используем переменную окружения или текущий путь
    custom_path = os.getenv("BASE_PATH")
    if custom_path and safe_path_exists(Path(custom_path)):
        return Path(custom_path)
    # Иначе используем текущий путь
    return Path(__file__).parent.absolute()

BASE_PATH = get_base_path()

# Создаем директорию data если её нет
data_dir = BASE_PATH / 'data'
data_dir.mkdir(parents=True, exist_ok=True)

# Настройки базы данных (абсолютные пути)
DATABASE_PATH = str(data_dir / 'pixel_bot.db')

# Настройки бота
BOT_NAME = "Pixel" 
BOT_DESCRIPTION = "Чат-менеджер для управления группами в Telegram"

# Anti-Raid Protection Defaults
RAID_PROTECTION = {
    'gif_limit': 3,           # GIFs in time window
    'gif_time_window': 5,     # seconds
    'sticker_limit': 5,       # stickers in time window
    'sticker_time_window': 10, # seconds
    'duplicate_text_limit': 3, # similar messages in time window
    'duplicate_text_window': 30, # seconds
    'mass_join_limit': 10,    # new members in time window
    'mass_join_window': 60,   # seconds
    'similarity_threshold': 0.7 # text similarity threshold (0-1)
}

# Top Chats Settings Defaults
TOP_CHATS_DEFAULTS = {
    'show_in_top': 'public_only',  # 'always', 'public_only', or 'never'
}
