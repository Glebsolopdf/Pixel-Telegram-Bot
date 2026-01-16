"""
Telegram бот Pixel Utils Bot - чат менеджер

Copyright (c) 2025 GlebSoloProjects

This project is licensed under MIT License.
See LICENSE file for details.

ATTRIBUTION REQUIREMENT:
If you modify or distribute this Software, you MUST include a reference to the
original project in the source code (e.g., in README.md or in code comments).

Required attribution:
- Original Project: Pixel Utils Bot
- Creator: GlebSoloProjects
- Website: https://pixel-ut.pro
- Telegram: @pixel_ut_bot
"""
import argparse
import asyncio
import logging
import signal
import shutil
from pathlib import Path

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN, BOT_NAME, BOT_DESCRIPTION, DEBUG, CLEANUP_PYCACHE_ON_SHUTDOWN, BASE_PATH
from databases.database import db
from databases.moderation_db import moderation_db
from databases.reputation_db import reputation_db
from databases.network_db import network_db
from databases.raid_protection_db import raid_protection_db
from databases.utilities_db import utilities_db
from raid_protection import raid_protection
from scheduler import TaskScheduler
from utils.notifications import (
    send_test_mode_notification, 
    send_shutdown_notification, 
    send_update_notification,
    set_bot_instance as set_notifications_bot
)
from utils.permissions import set_bot_instance as set_permissions_bot
from middleware.settings_guard import SettingsGuardMiddleware
from middleware.command_spam import CommandSpamMiddleware
from middleware.auto_spam_detection import AutoSpamDetectionMiddleware
from handlers.common import register_common_handlers
from handlers.private import register_private_handlers
from handlers.moderation import register_moderation_handlers
from handlers.settings import register_settings_handlers
from handlers.profile import register_profile_handlers
from handlers.userinfo import register_userinfo_handlers
from handlers.network import register_network_handlers
from handlers.raid_protection import register_raid_protection_handlers
from handlers.top_chats import register_top_chats_handlers
from handlers.initial_setup import register_initial_setup_handlers

logging.basicConfig(
    level=logging.INFO if not DEBUG else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN "
        "или задайте её в config.py. См. env.example для примера."
    )

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

scheduler = TaskScheduler(bot_instance=bot)

shutdown_event = asyncio.Event()

set_notifications_bot(bot)
set_permissions_bot(bot)

dp.callback_query.middleware(SettingsGuardMiddleware())
dp.message.outer_middleware(AutoSpamDetectionMiddleware())
dp.message.outer_middleware(CommandSpamMiddleware())

register_common_handlers(dp, bot)
register_private_handlers(dp, bot)
register_moderation_handlers(dp, bot)
register_settings_handlers(dp, bot)
register_profile_handlers(dp, bot)
register_userinfo_handlers(dp, bot)
register_network_handlers(dp, bot)
register_raid_protection_handlers(dp, bot)
register_top_chats_handlers(dp, bot)
register_initial_setup_handlers(dp, bot)


def signal_handler(signum, frame):
    """Обработчик сигналов для корректного завершения"""
    logger.info(f"Получен сигнал {signum}, инициируем остановку...")
    shutdown_event.set()


def setup_signal_handlers():
    """Настройка обработчиков сигналов"""
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        logger.info("Обработчики сигналов настроены")
    except (ValueError, OSError) as e:
        logger.warning(f"Не удалось настроить обработчики сигналов: {e}")
        logger.info("Используем альтернативный способ остановки")


def cleanup_pycache():
    """Удаляет все директории __pycache__ в проекте"""
    if not CLEANUP_PYCACHE_ON_SHUTDOWN:
            return
        
    try:
        removed_count = 0
        for pycache_dir in BASE_PATH.rglob("__pycache__"):
            try:
                shutil.rmtree(pycache_dir)
                removed_count += 1
                logger.debug(f"Удалена директория: {pycache_dir}")
            except Exception as e:
                logger.warning(f"Не удалось удалить {pycache_dir}: {e}")
        
        if removed_count > 0:
            logger.info(f"✓ Удалено {removed_count} директорий __pycache__")
    except Exception as e:
        logger.warning(f"Ошибка при удалении __pycache__: {e}")


def print_startup_banner():
    """Выводит ASCII-арт при запуске бота"""
    banner = """
╔═════════════════════════════════════════════╗
║                                             ║
║     ██████╗ ██╗██╗  ██╗███████╗██║          ║
║     ██╔══██╗██║╚██╗██╔╝██╔════╝██║          ║
║     ██████╔╝██║ ╚███╔╝ █████╗  ██║          ║
║     ██╔═══╝ ██║ ██╔██╗ ██╔══╝  ██║          ║
║     ██║     ██║██╔╝ ██╗███████╗╚██████╗     ║
║     ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝     ║
║                                             ║
║                                             ║    
║ Telegram Bot           by GlebSoloProjects  ║
║ Version: 1.12          https://pixel-ut.pro ║
╚═════════════════════════════════════════════╝
    """
    print(banner)


def print_success_message():
    """Выводит сообщение об успешном запуске"""
    success_msg = """
╔═════════════════╗
║                 ║
║ УСПЕШНЫЙ ЗАПУСК ║
║          V 1.12 ║
╚═════════════════╝

    """
    print(success_msg)


async def main(test_mode: bool = False):
    """Основная функция запуска бота"""
    setup_signal_handlers()
    
    try:
        await db.init_db()
        
        logger.info("Проверка целостности базы данных...")
        is_integrity_ok = await db.check_integrity()
        if not is_integrity_ok:
            logger.warning("Обнаружено повреждение базы данных. Запуск автоматического восстановления...")
            recovery_success = await db.auto_recover_if_needed()
            if recovery_success:
                logger.info("База данных успешно восстановлена")
                await db.init_db()
            else:
                logger.error("Не удалось восстановить базу данных. Бот может работать некорректно.")
        else:
            logger.info("Целостность базы данных проверена: OK")
        
        await moderation_db.init_db()
        await reputation_db.init_db()
        await network_db.init_db()
        await raid_protection_db.init_db()
        await utilities_db.init_db()
        logger.info("Базы данных инициализированы")
        
        from utils.gifs import init_gifs_settings_file
        init_gifs_settings_file()
        
        raid_protection.set_bot(bot)
        logger.info("Система защиты от рейдов инициализирована")
        
        await db.cleanup_duplicate_chats()
        logger.info("Дубликаты чатов очищены")
        
        await db.cleanup_old_stats(90)
        await db.cleanup_old_user_stats(90)
        logger.info("Старые записи статистики очищены")
        
        expired_count = await moderation_db.cleanup_expired_punishments()
        logger.info(f"Очищено {expired_count} истекших наказаний")
        
        await raid_protection_db.cleanup_old_activity(1)
        await raid_protection_db.cleanup_old_joins(2)
        await raid_protection_db.cleanup_old_deleted_messages(5)
        logger.info("Старые записи защиты от рейдов очищены")
        
        if test_mode:
            await send_test_mode_notification()
        
        scheduler_task = asyncio.create_task(scheduler.start())
        logger.info("Планировщик автоматических задач запущен")
        
        logger.info(f"Запуск бота {BOT_NAME}...")
        
        polling_task = asyncio.create_task(dp.start_polling(bot))
        
        await asyncio.sleep(1)
        
        if not polling_task.done():
            print_success_message()
            print_startup_banner()
        
        done, pending = await asyncio.wait(
            [polling_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        if 'scheduler_task' in locals() and not scheduler_task.done():
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        logger.info("Остановка бота...")
        
        try:
            if scheduler:
                await scheduler.stop()
            
            try:
                await dp.stop_polling(close_bot_session=True)
            except Exception as e:
                logger.debug(f"Ошибка при остановке polling: {e}")
            
            # Дополнительно закрываем HTTP-сессию бота на случай, если stop_polling не закрыл её
            try:
                if bot and hasattr(bot, 'session') and bot.session:
                    if not bot.session.closed:
                        await bot.session.close()
                    # Даем время на закрытие всех соединений
                    await asyncio.sleep(0.2)
            except Exception as e:
                logger.debug(f"Ошибка при закрытии сессии бота: {e}")
            
            logger.info("✓ Бот остановлен")
        except Exception as e:
            logger.error(f"Ошибка при остановке бота: {e}")
        finally:
            # Удаляем __pycache__ перед выключением
            cleanup_pycache()


async def send_notifications_and_exit(notification_type: str):
    """Отправляет уведомления и завершает работу бота"""
    try:
        await db.init_db()
        logger.info("База данных инициализирована")
        
        if notification_type == "shutdown":
            logger.info("Начинаем рассылку уведомлений о выключении...")
            await send_shutdown_notification()
            logger.info("✓ Все уведомления о выключении отправлены. Завершение работы...")
        elif notification_type == "update":
            logger.info("Начинаем рассылку уведомлений об обновлении...")
            await send_update_notification()
            logger.info("✓ Все уведомления об обновлении отправлены. Завершение работы...")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}")
    finally:
        try:
            if bot and hasattr(bot, 'session') and bot.session:
                if not bot.session.closed:
                    await bot.session.close()
                await asyncio.sleep(0.2)
                logger.info("Соединение с Telegram API закрыто")
        except Exception as e:
            logger.debug(f"Ошибка при закрытии соединения: {e}")
        
        cleanup_pycache()
        
        logger.info("Работа бота завершена")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Запуск Telegram бота PIXEL')
    parser.add_argument('--test', action='store_true', 
                       help='Запустить бота в тестовом режиме (отправит уведомления во все чаты)')
    parser.add_argument('--up', action='store_true',
                       help='Отправить уведомление о выключении для обновления и завершить работу')
    parser.add_argument('--newup', action='store_true',
                       help='Отправить уведомление об обновлении и запустить бота')
    args = parser.parse_args()
    
    logger.info(f"Запуск с аргументами: test={args.test}, up={args.up}, newup={args.newup}")
    
    try:
        if args.up:
            logger.info("Режим --up: отправка уведомлений о выключении...")
            asyncio.run(send_notifications_and_exit("shutdown"))
        elif args.newup:
            logger.info("Режим --newup: отправка уведомлений об обновлении...")
            async def send_update_and_start():
                await db.init_db()
                await send_update_notification()
                logger.info("Уведомления об обновлении отправлены. Запуск бота...")
                await main(test_mode=False)
            asyncio.run(send_update_and_start())
        else:
            asyncio.run(main(test_mode=args.test))
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
