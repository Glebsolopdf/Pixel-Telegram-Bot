"""
Работа с GIF-файлами
"""
import json
import logging
import random
from pathlib import Path
from typing import Optional, Tuple

from aiogram.types import Message, BufferedInputFile
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)

# Путь к файлу настроек гифок
GIFS_SETTINGS_PATH = Path("data/gifs_settings.json")


def init_gifs_settings_file():
    """
    Инициализирует файл настроек гифок, если его нет
    Создает пустой JSON файл с пустым словарем
    """
    try:
        # Создаем папку data если её нет
        GIFS_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Если файл не существует, создаем его с пустым словарем
        if not GIFS_SETTINGS_PATH.exists():
            with open(GIFS_SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
            logger.info(f"Создан файл настроек гифок: {GIFS_SETTINGS_PATH}")
    except Exception as e:
        logger.error(f"Ошибка при инициализации файла настроек гифок: {e}")


def get_gifs_enabled(chat_id: int) -> bool:
    """
    Получает настройку включения гифок для чата
    
    Args:
        chat_id: ID чата
    
    Returns:
        True если гифки включены, False если выключены (по умолчанию False)
    """
    try:
        if not GIFS_SETTINGS_PATH.exists():
            return False  # По умолчанию выключены
        
        with open(GIFS_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        
        # Проверяем настройку для конкретного чата
        chat_id_str = str(chat_id)
        if chat_id_str in settings:
            return settings[chat_id_str].get('enabled', False)
        
        return False  # По умолчанию выключены
        
    except Exception as e:
        logger.error(f"Ошибка при чтении настроек гифок для чата {chat_id}: {e}")
        return False  # По умолчанию выключены при ошибке


def set_gifs_enabled(chat_id: int, enabled: bool) -> bool:
    """
    Устанавливает настройку включения гифок для чата
    
    Args:
        chat_id: ID чата
        enabled: True для включения, False для выключения
    
    Returns:
        True если успешно, False при ошибке
    """
    try:
        # Создаем папку data если её нет
        GIFS_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Загружаем существующие настройки
        settings = {}
        if GIFS_SETTINGS_PATH.exists():
            with open(GIFS_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        
        # Обновляем настройку для чата
        chat_id_str = str(chat_id)
        if chat_id_str not in settings:
            settings[chat_id_str] = {}
        
        settings[chat_id_str]['enabled'] = enabled
        
        # Сохраняем обратно
        with open(GIFS_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек гифок для чата {chat_id}: {e}")
        return False


def get_random_gif(command_name: str) -> Optional[Tuple[BufferedInputFile, str]]:
    """
    Получает случайную гифку из папки для команды модерации
    
    Args:
        command_name: Название команды (ban, unban, mute, unmute, warn, kick, welcome)
    
    Returns:
        Кортеж (BufferedInputFile, file_type) где file_type: 'animation' или 'video', 
        или None если папка пустая/не найдена
    """
    try:
        # Путь к папке с гифками для команды
        gif_dir = Path("Gifs") / command_name
        
        # Проверяем существование папки
        if not gif_dir.exists() or not gif_dir.is_dir():
            logger.debug(f"Папка {gif_dir} не существует или не является директорией")
            return None
        
        # Поддерживаемые форматы
        animation_formats = ('.gif', '.webm')  # Форматы для answer_animation
        video_formats = ('.mp4', '.MOV', '.mov')  # Форматы для answer_video
        
        # Получаем все файлы с поддерживаемыми форматами
        all_files = [f for f in gif_dir.iterdir() 
                     if f.is_file() and f.suffix.lower() in (*animation_formats, *video_formats)]
        
        if not all_files:
            logger.debug(f"В папке {gif_dir} нет файлов с поддерживаемыми форматами")
            return None
        
        # Выбираем случайный файл
        selected_file = random.choice(all_files)
        file_ext = selected_file.suffix.lower()
        
        # Определяем тип файла
        if file_ext in animation_formats:
            file_type = 'animation'
        elif file_ext in video_formats:
            file_type = 'video'
        else:
            file_type = 'video'  # По умолчанию как видео
        
        # Читаем файл
        with open(selected_file, 'rb') as f:
            file_data = f.read()
        
        # Создаем BufferedInputFile
        file_obj = BufferedInputFile(
            file_data,
            filename=selected_file.name
        )
        
        return (file_obj, file_type)
        
    except Exception as e:
        logger.error(f"Ошибка при получении гифки для команды {command_name}: {e}")
        return None


async def send_message_with_gif(message: Message, text: str, command_name: str, parse_mode=None, reply_markup=None):
    """
    Отправляет сообщение с гифкой/видео, если оно найдено, иначе отправляет только текст
    
    Args:
        message: Объект сообщения для ответа
        text: Текст сообщения (будет использован как подпись к гифке/видео)
        command_name: Название команды для поиска гифки (ban, unban, mute, unmute, warn, kick, welcome)
        parse_mode: Режим парсинга текста (например, ParseMode.HTML)
        reply_markup: Клавиатура для сообщения (опционально)
    """
    try:
        # Проверяем настройку для чата (только для групповых чатов)
        # Исключение: приветственное сообщение (welcome) всегда отправляется с гифкой
        chat_id = message.chat.id
        if message.chat.type in ['group', 'supergroup'] and command_name != "welcome":
            if not get_gifs_enabled(chat_id):
                # Гифки выключены - отправляем только текст
                await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
                return
        
        # Пытаемся получить гифку
        gif_result = get_random_gif(command_name)
        
        if gif_result is None:
            # Гифка не найдена - отправляем только текст
            await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return
        
        file_obj, file_type = gif_result
        
        # Отправляем гифку/видео с текстом
        if file_type == 'animation':
            await message.answer_animation(
                animation=file_obj,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        else:  # video
            await message.answer_video(
                video=file_obj,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения с гифкой: {e}", exc_info=True)
        # В случае ошибки отправляем только текст
        try:
            await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Ошибка при отправке текстового сообщения через message.answer: {e2}", exc_info=True)

