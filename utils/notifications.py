"""
Отправка уведомлений во все чаты
"""
import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.enums import ParseMode
from databases.database import db

logger = logging.getLogger(__name__)

# Глобальная переменная bot будет установлена при инициализации
bot: Optional[Bot] = None

def set_bot_instance(bot_instance: Bot):
    """Устанавливает экземпляр бота для использования в модуле"""
    global bot
    bot = bot_instance


async def send_notification_to_all_chats(notification_text: str, delete_after: int = None):
    """Универсальная функция для отправки уведомлений во все активные чаты"""
    if not bot:
        logger.error("Bot instance not set in notifications module")
        return
        
    try:
        logger.info("Отправка уведомлений во все чаты...")
        
        # Получаем все активные чаты
        all_chats = await db.get_all_chats_for_update()
        
        # Фильтруем только группы и супергруппы (исключаем личные сообщения и каналы)
        chats = [
            chat for chat in all_chats 
            if chat.get('chat_type') in ['group', 'supergroup']
        ]
        
        logger.info(
            f"Найдено {len(chats)} групп/супергрупп для отправки уведомлений "
            f"(всего чатов: {len(all_chats)})"
        )
        
        if not chats:
            logger.info("Нет активных групп для отправки уведомлений")
            return
        
        success_count = 0
        error_count = 0
        rate_limit_count = 0
        
        # Telegram API ограничения:
        # - Максимум 30 сообщений в секунду в разные чаты
        # - Используем консервативную задержку: 0.05 секунды = ~20 сообщений/сек
        delay_between_messages = 0.05
        
        # Семафор для ограничения параллельных запросов (максимум 5 одновременно)
        semaphore = asyncio.Semaphore(5)
        
        async def delete_message_after_delay(chat_id: int, message_id: int, delay: int):
            """Удаляет сообщение через указанное количество секунд"""
            try:
                await asyncio.sleep(delay)
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.debug(f"Сообщение удалено из чата {chat_id}")
            except Exception as e:
                # Игнорируем ошибки удаления (сообщение уже удалено, нет прав и т.д.)
                logger.debug(f"Не удалось удалить сообщение из чата {chat_id}: {e}")
        
        async def send_to_chat(chat_id: int):
            """Отправка сообщения в один чат с обработкой ошибок"""
            nonlocal success_count, error_count, rate_limit_count
            
            async with semaphore:
                max_retries = 3
                retry_delay = 1
                
                for attempt in range(max_retries):
                    try:
                        message = await bot.send_message(
                            chat_id=chat_id,
                            text=notification_text,
                            parse_mode=ParseMode.HTML
                        )
                        success_count += 1
                        
                        # Запускаем задачу удаления сообщения только если указано время (delete_after не None и > 0)
                        # Для сообщений о выключении и обновлении (--up, --newup) delete_after=None, поэтому они не удаляются
                        if delete_after is not None and delete_after > 0:
                            asyncio.create_task(delete_message_after_delay(chat_id, message.message_id, delete_after))
                        
                        return
                    except Exception as e:
                        error_str = str(e).lower()
                        
                        # Обработка rate limit (429 Too Many Requests)
                        if "429" in error_str or "too many requests" in error_str or "retry after" in error_str:
                            rate_limit_count += 1
                            if attempt < max_retries - 1:
                                # Экспоненциальный backoff: 1, 2, 4 секунды
                                wait_time = retry_delay * (2 ** attempt)
                                logger.debug(f"Rate limit для чата {chat_id}, ожидание {wait_time} сек перед повтором")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                logger.warning(f"Превышен rate limit для чата {chat_id} после {max_retries} попыток")
                                error_count += 1
                                return
                        
                        # Другие ошибки (чат недоступен, бот удален и т.д.)
                        if attempt == 0:  # Логируем только при первой попытке
                            logger.debug(f"Не удалось отправить уведомление в чат {chat_id}: {e}")
                        error_count += 1
                        return
        
        # Отправляем сообщения с задержкой между ними
        for i, chat in enumerate(chats):
            chat_id = chat['chat_id']
            await send_to_chat(chat_id)
            
            # Задержка между отправками (кроме последнего сообщения)
            if i < len(chats) - 1:
                await asyncio.sleep(delay_between_messages)
        
        logger.info(
            f"Уведомления отправлены: успешно {success_count}, ошибок {error_count}, "
            f"rate limit {rate_limit_count} (всего чатов: {len(chats)})"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}")


async def send_test_mode_notification():
    """Отправка уведомления о тестовом режиме во все активные чаты"""
    notification_text = (
        "⚠️ Бот запускается в тестовом режиме.\n"
        "Возможны ошибки в работе!\n\n"
        "<i>Удалю это сообщение через минуту</i>"
    )
    await send_notification_to_all_chats(notification_text, delete_after=60)


async def send_shutdown_notification():
    """Отправка уведомления о выключении бота для обновления"""
    notification_text = (
        "🔧 <b>Уведомление об обновлении</b>\n\n"
        "Бот выключается для загрузки обновления.\n"
        "Это может занять до 10 минут.\n\n"
        "Подробности читайте на сайте: <a href=\"https://pixel-ut.pro\">pixel-ut.pro</a>"
    )
    await send_notification_to_all_chats(notification_text, delete_after=None)


async def send_update_notification():
    """Отправка уведомления об обновлении бота"""
    notification_text = (
        "✅ <b>Обновление x.x вышло! </b>\n\n"
        "Добавлены настройки видимости в топе, отображения, фильтров и частных чатов.\n\n"
        "Ссылка: <a href=\"https://pixel-ut.pro/updates\">pixel-ut.pro</a>"
    )
    await send_notification_to_all_chats(notification_text, delete_after=None)

