"""
Модуль для автоматических задач бота PIXEL
"""
import asyncio
import logging
import time
from datetime import datetime

from aiogram.enums import ParseMode

from databases.database import db
from databases.moderation_db import moderation_db
from databases.reputation_db import reputation_db
from databases.network_db import network_db
from config import DEBUG
logger = logging.getLogger(__name__)


def get_raid_protection_db():
    """Получить экземпляр базы данных защиты от рейдов"""
    from databases.raid_protection_db import raid_protection_db
    return raid_protection_db


class TaskScheduler:
    """Планировщик автоматических задач"""
    
    def __init__(self, bot_instance=None, max_concurrent_chats=10):
        self.running = False
        self.tasks = []
        self.bot = bot_instance
        self.chat_semaphore = asyncio.Semaphore(max_concurrent_chats)
    
    async def start(self):
        """Запуск планировщика задач"""
        self.running = True
        logger.info("Планировщик задач запущен")
        
        self.tasks = [
            asyncio.create_task(self.cleanup_duplicates_task()),
            asyncio.create_task(self.cleanup_old_stats_task()),
            asyncio.create_task(self.update_chat_info_task()),
            asyncio.create_task(self.mute_expiry_task()),
            asyncio.create_task(self.ban_expiry_task()),
            asyncio.create_task(self.cleanup_old_moderation_records_task()),
            asyncio.create_task(self.reputation_recovery_task()),
            asyncio.create_task(self.cleanup_old_punishments_task()),
            asyncio.create_task(self.cleanup_frozen_chats_task()),
            asyncio.create_task(self.cleanup_expired_network_codes_task()),
            asyncio.create_task(self.cleanup_raid_protection_task()),
            asyncio.create_task(self.cleanup_inactive_task()),
            asyncio.create_task(self.cleanup_expired_commands_task()),
            asyncio.create_task(self.reset_daily_stats_task())
        ]
        
        await asyncio.gather(*self.tasks, return_exceptions=True)
    
    async def stop(self):
        """Остановка планировщика задач"""
        self.running = False
        logger.info("Останавливаем планировщик задач...")
        
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        if self.tasks:
            try:
                await asyncio.gather(*self.tasks, return_exceptions=True)
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.error(f"Ошибка при остановке задач планировщика: {e}")
        
        logger.info("Планировщик задач остановлен")
    
    async def cleanup_duplicates_task(self):
        """Задача очистки дубликатов чатов каждые 5 минут"""
        while self.running:
            try:
                await db.cleanup_duplicate_chats()
                logger.info("Автоматическая очистка дубликатов выполнена")
            except Exception as e:
                logger.error(f"Ошибка при автоматической очистке дубликатов: {e}")
            
            await asyncio.sleep(300)
    
    async def cleanup_old_stats_task(self):
        """Задача очистки старых записей статистики каждый час"""
        while self.running:
            try:
                await db.cleanup_old_stats(90)
                await db.cleanup_old_user_stats(90)
                logger.info("Автоматическая очистка старых записей выполнена")
            except Exception as e:
                logger.error(f"Ошибка при автоматической очистке старых записей: {e}")
            
            await asyncio.sleep(3600)
    
    async def update_chat_info_task(self):
        """Задача обновления информации о чатах каждую минуту"""
        while self.running:
            try:
                chats = await db.get_all_chats_for_update()
                
                async def update_single_chat(chat):
                    async with self.chat_semaphore:
                        try:
                            from handlers.common import update_chat_info_if_needed
                            await update_chat_info_if_needed(chat['chat_id'])
                        except Exception as e:
                            error_str = str(e).lower()
                            if "chat not found" in error_str or "bad request" in error_str or "bot was kicked" in error_str or "forbidden" in error_str:
                                if DEBUG:
                                    logger.debug(f"Чат {chat['chat_id']} недоступен при обновлении информации (бот исключен или чат не найден): {e}")
                            else:
                                logger.error(f"Ошибка при обновлении информации о чате {chat['chat_id']}: {e}")
                
                await asyncio.gather(*[update_single_chat(chat) for chat in chats], return_exceptions=True)
                
                logger.debug(f"Автоматическое обновление информации о {len(chats)} чатах выполнено")
            except Exception as e:
                logger.error(f"Ошибка при автоматическом обновлении информации о чатах: {e}")
            
            await asyncio.sleep(60)
    
    async def mute_expiry_task(self):
        """Задача проверки истечения мутов - сканирует каждые 10 сек если есть активные муты"""
        if not hasattr(self, '_recently_processed_mutes'):
            self._recently_processed_mutes = {}
        
        while self.running:
            try:
                current_time = time.time()
                self._recently_processed_mutes = {
                    mute_id: ts for mute_id, ts in self._recently_processed_mutes.items() 
                    if current_time - ts < 60
                }
                
                has_active_mutes = False
                total_active_mutes = 0
                
                chats = await db.get_all_chats_for_update()
                logger.debug(f"Проверяем муты в {len(chats)} чатах")
                
                async def process_chat_mutes(chat, recently_processed_ref, current_time_ref):
                    async with self.chat_semaphore:
                        try:
                            import bot
                            try:
                                bot_member = await bot.bot.get_chat_member(chat['chat_id'], bot.bot.id)
                            except Exception as e:
                                error_str = str(e).lower()
                                if "chat not found" in error_str or "bad request" in error_str or "bot was kicked" in error_str or "forbidden" in error_str:
                                    if DEBUG:
                                        logger.debug(f"Чат {chat['chat_id']} недоступен (бот исключен или чат не найден), деактивируем его: {e}")
                                    try:
                                        await db.deactivate_chat(chat['chat_id'])
                                    except Exception:
                                        pass
                                    return 0
                                raise
                            
                            if bot_member.status not in ['administrator', 'creator']:
                                return 0
                            
                            active_mutes = await moderation_db.get_active_punishments(chat['chat_id'], "mute")
                            
                            if not active_mutes:
                                return 0
                            
                            must_active_count = len(active_mutes)
                            logger.debug(f"В чате {chat['chat_id']} найдено {must_active_count} активных мутов")
                            
                            expired_count = 0
                            
                            for mute in active_mutes:
                                try:
                                    mute_id = mute['id']
                                    
                                    if mute_id in recently_processed_ref:
                                        time_since_processed = current_time_ref - recently_processed_ref[mute_id]
                                        if time_since_processed < 30:
                                            logger.debug(f"Мут {mute_id} был обработан {time_since_processed:.1f} сек назад, пропускаем")
                                            continue
                                    
                                    if mute['expiry_date']:
                                        expiry_date = datetime.fromisoformat(mute['expiry_date'])
                                        now = datetime.now(expiry_date.tzinfo) if expiry_date.tzinfo else datetime.now()
                                        
                                        logger.debug(f"Проверяем мут {mute_id}: expiry={expiry_date}, now={now}, diff={(now - expiry_date).total_seconds()} сек")
                                        
                                        time_diff = (now - expiry_date).total_seconds()
                                        if time_diff < 0:
                                            continue
                                        
                                        if time_diff >= 0:
                                            # Двойная проверка: если уже в recently_processed_ref, пропускаем
                                            # (защита от race condition между первой проверкой и этой)
                                            if mute_id in recently_processed_ref:
                                                time_since = current_time_ref - recently_processed_ref[mute_id]
                                                if time_since < 5:  # Очень недавно обработан
                                                    logger.debug(f"Мут {mute_id} уже обрабатывается (race condition защита), пропускаем")
                                                    continue
                                            
                                            # Отмечаем что обрабатываем этот мут до попытки деактивации
                                            recently_processed_ref[mute_id] = current_time_ref
                                            
                                            deactivated = await moderation_db.deactivate_punishment(mute_id)
                                            
                                            if not deactivated:
                                                logger.debug(f"Мут {mute_id} уже был обработан другим потоком, пропускаем")
                                                continue
                                            
                                            logger.info(f"Мут истек для пользователя {mute['user_id']} в чате {chat['chat_id']}")
                                            
                                            import bot
                                            from aiogram.types import ChatPermissions
                                            try:
                                                await bot.bot.restrict_chat_member(
                                                    chat_id=chat['chat_id'],
                                                    user_id=mute['user_id'],
                                                    permissions=ChatPermissions(
                                                        can_send_messages=True,
                                                        can_send_audios=True,
                                                        can_send_documents=True,
                                                        can_send_photos=True,
                                                        can_send_videos=True,
                                                        can_send_video_notes=True,
                                                        can_send_voice_notes=True,
                                                        can_send_polls=True,
                                                        can_send_other_messages=True,
                                                        can_add_web_page_previews=True,
                                                        can_change_info=True,
                                                        can_invite_users=True,
                                                        can_pin_messages=True,
                                                        can_manage_topics=True
                                                    )
                                                )
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при снятии ограничений: {e}")
                                                    try:
                                                        await db.deactivate_chat(chat['chat_id'])
                                                    except Exception:
                                                        pass
                                                else:
                                                    logger.error(f"Ошибка при снятии ограничений для пользователя {mute['user_id']}: {e}")
                                            
                                            username_display = mute['user_first_name'] or f"@{mute['user_username']}" if mute['user_username'] else f"ID{mute['user_id']}"
                                            
                                            philosophical_quotes = [
                                                "🗣️ Голос - это дар, который нужно беречь и использовать мудро",
                                                "🔄 Второй шанс - это возможность стать лучше",
                                                "🌅 После тишины приходит время для слов",
                                                "🕊️ Свобода слова рождает понимание",
                                                "💬 Каждое слово имеет значение, каждое молчание - тоже",
                                                "🌟 Освобождение от ограничений открывает новые горизонты",
                                                "🦋 Как бабочка выходит из кокона, так и слова выходят из молчания",
                                                "🌊 Река слов снова течет свободно",
                                                "🎵 После паузы музыка становится еще прекраснее",
                                                "🌱 Из тишины рождается мудрость",
                                                "🔓 Ключ к пониманию - это возможность быть услышанным",
                                                "📖 Новая глава начинается с первого слова",
                                                "🎭 Каждый актер заслуживает своего выхода на сцену",
                                                "🌈 После бури всегда наступает затишье",
                                                "🕯️ Свет разума рассеивает тьму непонимания"
                                            ]
                                            
                                            import random
                                            quote = random.choice(philosophical_quotes)
                                            
                                            # Проверяем настройку silent mute
                                            raid_protection_db = get_raid_protection_db()
                                            settings = await raid_protection_db.get_settings(chat['chat_id'])
                                            mute_silent = settings.get('mute_silent', False)
                                            
                                            # Отправляем сообщение в чат только если silent mode выключен
                                            if not mute_silent:
                                                try:
                                                    await bot.bot.send_message(
                                                        chat['chat_id'],
                                                        f"🔊 Участник <b>{username_display}</b> <i>освобожден(а) от тайм-аута</i>\n"
                                                        f"🔸 <b>По истечению времени я автоматически снял ограничения, не нарушайте правила чата!</b>\n\n"
                                                        f"<blockquote>{quote}</blockquote>",
                                                        parse_mode=ParseMode.HTML
                                                    )
                                                    logger.info(f"✅ Автоматически снят мут пользователю {mute['user_id']} в чате {chat['chat_id']}")
                                                except Exception as e:
                                                    error_str = str(e).lower()
                                                    if "chat not found" in error_str or "bad request" in error_str:
                                                        if DEBUG:
                                                            logger.debug(f"Чат {chat['chat_id']} не найден при отправке сообщения о размуте: {e}")
                                                        try:
                                                            await db.deactivate_chat(chat['chat_id'])
                                                        except Exception:
                                                            pass
                                                    else:
                                                        logger.error(f"Ошибка при отправке сообщения о размуте: {e}")
                                            else:
                                                logger.info(f"✅ Автоматически снят мут пользователю {mute['user_id']} в чате {chat['chat_id']} (silent mode)")
                                            
                                            expired_count += 1
                                            
                                except Exception as e:
                                    logger.error(f"Ошибка при обработке мута {mute['id']}: {e}")
                                    continue
                            
                            return must_active_count
                                
                        except Exception as e:
                            error_str = str(e).lower()
                            if "chat not found" in error_str or "bad request" in error_str or "bot was kicked" in error_str or "forbidden" in error_str:
                                if DEBUG:
                                    logger.debug(f"Чат {chat['chat_id']} недоступен при проверке мутов (бот исключен или чат не найден): {e}")
                                try:
                                    await db.deactivate_chat(chat['chat_id'])
                                except Exception:
                                    pass
                            else:
                                logger.error(f"Ошибка при проверке мутов в чате {chat['chat_id']}: {e}")
                            return 0
                
                results = await asyncio.gather(*[process_chat_mutes(chat, self._recently_processed_mutes, current_time) for chat in chats], return_exceptions=True)
                
                for result in results:
                    if isinstance(result, int):
                        if result > 0:
                            total_active_mutes += result
                            has_active_mutes = True
                
                if has_active_mutes:
                    logger.debug(f"Найдено {total_active_mutes} активных мутов - сканируем через 10 секунд")
                    await asyncio.sleep(10)
                else:
                    logger.debug("Нет активных мутов - сканируем через 60 секунд")
                    await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче проверки мутов: {e}")
                await asyncio.sleep(30)
    
    async def ban_expiry_task(self):
        """Задача для автоматического разбана истекших банов"""
        logger.info("Запущена задача проверки истечения банов")
        
        while self.running:
            try:
                chats = await db.get_all_chats_for_update()
                total_active_bans = 0
                has_active_bans = False
                
                async def process_chat_bans(chat):
                    async with self.chat_semaphore:
                        try:
                            active_bans = await moderation_db.get_active_punishments(chat['chat_id'], "ban")
                            
                            if not active_bans:
                                return 0
                            
                            ban_count = len(active_bans)
                            
                            for ban in active_bans:
                                try:
                                    if ban['expiry_date']:
                                        expiry_date = datetime.fromisoformat(ban['expiry_date'])
                                        now = datetime.now(expiry_date.tzinfo) if expiry_date.tzinfo else datetime.now()
                                        if now >= expiry_date:
                                            deactivated = await moderation_db.deactivate_punishment(ban['id'])
                                            
                                            if not deactivated:
                                                logger.warning(f"Бан {ban['id']} уже был обработан другим потоком, пропускаем")
                                                continue
                                            
                                            logger.info(f"Бан истек для пользователя {ban['user_id']} в чате {chat['chat_id']}")
                                            
                                            import bot
                                            try:
                                                await bot.bot.unban_chat_member(
                                                    chat_id=chat['chat_id'],
                                                    user_id=ban['user_id']
                                                )
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при разбане: {e}")
                                                    try:
                                                        await db.deactivate_chat(chat['chat_id'])
                                                    except Exception:
                                                        pass
                                                else:
                                                    logger.error(f"Ошибка при разбане пользователя {ban['user_id']}: {e}")
                                            
                                            username_display = ban['user_first_name'] or f"@{ban['user_username']}" if ban['user_username'] else f"ID{ban['user_id']}"
                                            
                                            philosophical_quotes = [
                                                "🌅 Время лечит все раны, даже самые глубокие",
                                                "🌊 Река находит путь к морю, преодолевая все препятствия",
                                                "🕊️ Птица свободы всегда найдет путь домой",
                                                "🌱 Из пепла может вырасти новая жизнь",
                                                "🌙 Даже самая темная ночь заканчивается рассветом",
                                                "🍃 Новый лист может вырасти на том же дереве",
                                                "🌌 Звезды не исчезают навсегда, они просто ждут своего времени",
                                                "🌿 Дерево может зацвести заново после зимы",
                                                "🦋 Превращение требует времени, но результат стоит ожидания",
                                                "🌅 Солнце всегда возвращается, даже после самой долгой ночи"
                                            ]
                                            
                                            import random
                                            quote = random.choice(philosophical_quotes)
                                            
                                            try:
                                                await bot.bot.send_message(
                                                    chat['chat_id'],
                                                    f"✅ <b>{username_display}</b> <i>был(а) автоматически разбанен(а)</i>\n"
                                                    f"🔸 <b>Срок наказания истек</b>\n\n"
                                                    f"<blockquote>{quote}</blockquote>",
                                                    parse_mode=ParseMode.HTML
                                                )
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при отправке сообщения о разбане: {e}")
                                                    try:
                                                        await db.deactivate_chat(chat['chat_id'])
                                                    except Exception:
                                                        pass
                                                else:
                                                    logger.error(f"Ошибка при отправке сообщения о разбане: {e}")
                                            
                                            try:
                                                try:
                                                    chat_info = await bot.bot.get_chat(chat['chat_id'])
                                                    chat_title = chat_info.title or "Неизвестный чат"
                                                except Exception as e:
                                                    error_str = str(e).lower()
                                                    if "chat not found" in error_str or "bad request" in error_str:
                                                        if DEBUG:
                                                            logger.debug(f"Чат {chat['chat_id']} не найден при получении информации: {e}")
                                                        chat_title = "неизвестный чат"
                                                    else:
                                                        raise
                                                
                                                from aiogram.utils.keyboard import InlineKeyboardBuilder
                                                builder = InlineKeyboardBuilder()
                                                try:
                                                    builder.button(text="💬 Открыть чат", url=f"https://t.me/{chat_info.username}" if chat_info.username else f"https://t.me/c/{str(chat['chat_id'])[4:]}")
                                                except:
                                                    pass
                                                
                                                await bot.bot.send_message(
                                                    ban['user_id'],
                                                    f"✅ Вы были автоматически разбанены в чате \"{chat_title}\"\n"
                                                    f"🔸 Срок наказания истек\n\n"
                                                    f"<blockquote>{quote}</blockquote>",
                                                    parse_mode=ParseMode.HTML,
                                                    reply_markup=builder.as_markup() if builder else None
                                                )
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                if "chat not found" in error_str or "bad request" in error_str:
                                                    if DEBUG:
                                                        logger.debug(f"Чат {chat['chat_id']} не найден при отправке уведомления: {e}")
                                                else:
                                                    logger.error(f"Ошибка при отправке уведомления пользователю {ban['user_id']}: {e}")
                                            
                                            logger.info(f"✅ Автоматически разбанен пользователь {ban['user_id']} в чате {chat['chat_id']}")
                                            
                                except Exception as e:
                                    logger.error(f"Ошибка при обработке бана {ban['id']}: {e}")
                            
                            return ban_count
                                    
                        except Exception as e:
                            error_str = str(e).lower()
                            if "chat not found" in error_str or "bad request" in error_str:
                                if DEBUG:
                                    logger.debug(f"Чат {chat['chat_id']} не найден при проверке банов: {e}")
                                try:
                                    await db.deactivate_chat(chat['chat_id'])
                                except Exception:
                                    pass
                            else:
                                logger.error(f"Ошибка при проверке банов в чате {chat['chat_id']}: {e}")
                            return 0
                
                results = await asyncio.gather(*[process_chat_bans(chat) for chat in chats], return_exceptions=True)
                
                for result in results:
                    if isinstance(result, int):
                        if result > 0:
                            total_active_bans += result
                            has_active_bans = True
                if has_active_bans:
                    logger.debug(f"Найдено {total_active_bans} активных банов - сканируем через 10 секунд")
                    await asyncio.sleep(10)
                else:
                    logger.debug("Нет активных банов - сканируем через 60 секунд")
                    await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче проверки банов: {e}")
                await asyncio.sleep(30)
    
    async def cleanup_old_moderation_records_task(self):
        """Задача очистки старых записей модерации"""
        logger.info("Задача автоматической очистки старых записей модерации запущена")
        
        # Небольшая задержка перед первым запуском
        await asyncio.sleep(10)
        
        while self.running:
            try:
                logger.info("Запуск очистки старых записей модерации...")
                success = await moderation_db.cleanup_old_records(days_to_keep=7)
                if success:
                    logger.info("Автоматическая очистка старых записей модерации завершена")
                else:
                    logger.warning("Ошибка при автоматической очистке старых записей модерации")
                
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче автоматической очистки старых записей модерации: {e}", exc_info=True)
                await asyncio.sleep(20)
    
    async def reputation_recovery_task(self):
        """Задача восстановления репутации: +1 каждые 4 часа, +2 по выходным (МСК)"""
        logger.info("Задача восстановления репутации запущена")
        
        await asyncio.sleep(7200)
        
        while self.running:
            try:
                ts = datetime.utcnow().timestamp() + 10800
                moscow_dt = datetime.utcfromtimestamp(ts)
                weekday = moscow_dt.isoweekday()
                delta = 2 if weekday in (6, 7) else 1
                
                users = await reputation_db.get_all_users_with_reputation()
                
                if users:
                    logger.info(f"Проверяем восстановление репутации для {len(users)} пользователей; прирост={delta}")
                    
                    recovered_count = 0
                    for user in users:
                        user_id = user['user_id']
                        
                        recent_punishments = await reputation_db.get_recent_punishments(user_id, days=1)
                        
                        if not recent_punishments:
                            await reputation_db.update_reputation(user_id, delta)
                            recovered_count += 1
                    
                    if recovered_count > 0:
                        logger.info(f"Восстановлена репутация для {recovered_count} пользователей")
                else:
                    logger.debug("Нет пользователей для восстановления репутации")
                
                await asyncio.sleep(14400)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче восстановления репутации: {e}")
                await asyncio.sleep(3600)
    
    async def cleanup_old_punishments_task(self):
        """Задача очистки старых наказаний из базы репутации"""
        logger.info("Задача очистки старых наказаний репутации запущена")
        
        await asyncio.sleep(10800)
        
        while self.running:
            try:
                deleted_count = await reputation_db.cleanup_old_punishments(days=7)
                
                if deleted_count > 0:
                    logger.info(f"Очищено {deleted_count} старых наказаний из базы репутации")
                else:
                    logger.debug("Нет старых наказаний для очистки")
                
                await asyncio.sleep(86400)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки старых наказаний репутации: {e}")
                await asyncio.sleep(21600)
    
    async def cleanup_expired_network_codes_task(self):
        """Задача очистки истекших кодов сетки чатов"""
        logger.info("Задача очистки истекших кодов сетки запущена")
        
        await asyncio.sleep(1800)
        
        while self.running:
            try:
                deleted_count = await network_db.cleanup_expired_codes()
                
                if deleted_count > 0:
                    logger.info(f"Очищено {deleted_count} истекших кодов сетки")
                else:
                    logger.debug("Нет истекших кодов для очистки")
                
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки истекших кодов сетки: {e}")
                await asyncio.sleep(300)
    
    async def cleanup_raid_protection_task(self):
        """Задача очистки старых записей защиты от рейдов"""
        logger.info("Задача очистки записей защиты от рейдов запущена")
        
        await asyncio.sleep(300)
        
        while self.running:
            try:
                raid_db = get_raid_protection_db()
                
                await raid_db.cleanup_old_activity(1)
                await raid_db.cleanup_old_joins(2)
                await raid_db.cleanup_old_deleted_messages(5)
                
                logger.debug("Очистка записей защиты от рейдов завершена")
                
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки записей защиты от рейдов: {e}")
                await asyncio.sleep(300)
    
    async def cleanup_inactive_task(self):
        """Периодическая очистка неактивных пользователей и чатов"""
        logger.info("🔄 Задача очистки неактивных пользователей и чатов запущена")
        
        await asyncio.sleep(86400)
        
        while self.running:
            try:
                logger.info("🧹 Начинаю автоматическую очистку неактивных пользователей и чатов (неактивность > 30 дней)...")
                
                stats = await db.cleanup_inactive_users_and_chats(days=30)
                
                logger.info(
                    f"✅ Очистка неактивных завершена: "
                    f"пользователей удалено: {stats['users_deleted']}, "
                    f"чатов удалено: {stats['chats_deleted']}, "
                    f"ошибок пользователей: {stats['users_failed']}, "
                    f"ошибок чатов: {stats['chats_failed']}"
                )
                
                logger.info("⏰ Следующая очистка неактивных пользователей и чатов через 7 дней")
                await asyncio.sleep(604800)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в задаче очистки неактивных пользователей и чатов: {e}")
                await asyncio.sleep(21600)
    
    async def cleanup_expired_commands_task(self):
        """Периодическая очистка истекших команд (защита от спама командами)"""
        logger.info("🔄 Задача очистки истекших команд запущена")
        
        while self.running:
            try:
                from databases.utilities_db import utilities_db
                await utilities_db.cleanup_expired_commands(seconds_threshold=60)
                logger.debug("Очистка истекших команд выполнена")
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки истекших команд: {e}")
            
            await asyncio.sleep(60)
    
    async def cleanup_frozen_chats_task(self):
        """Задача очистки замороженных чатов (проверка раз в день)"""
        from datetime import timedelta
        from databases.moderation_db import moderation_db
        from databases.utilities_db import utilities_db
        from databases.raid_protection_db import raid_protection_db
        from databases.network_db import network_db
        import sqlite3
        
        while self.running:
            try:
                await asyncio.sleep(86400)
                
                frozen_chats = await db.get_frozen_chats_older_than(days=30)
                
                if not frozen_chats:
                    logger.debug("Нет замороженных чатов для очистки")
                    continue
                
                logger.info(f"Найдено {len(frozen_chats)} замороженных чатов для удаления")
                
                for chat_data in frozen_chats:
                    chat_id = chat_data['chat_id']
                    frozen_at = chat_data['frozen_at']
                    try:
                        logger.info(f"Удаление данных чата {chat_id} (заморожен {frozen_at})")
                        
                        await db.delete_chat_data(chat_id)
                        await moderation_db.delete_chat_data(chat_id)
                        await utilities_db.delete_chat_data(chat_id)
                        await raid_protection_db.delete_chat_data(chat_id)
                        
                        try:
                            await network_db.remove_chat_from_all_networks(chat_id)
                        except Exception as e:
                            logger.warning(f"Ошибка при удалении чата {chat_id} из сетей: {e}")
                        
                        logger.info(f"✅ Данные чата {chat_id} полностью удалены")
                        
                    except Exception as e:
                        logger.error(f"Ошибка при удалении данных чата {chat_id}: {e}", exc_info=True)
                
            except Exception as e:
                logger.error(f"Ошибка в задаче очистки замороженных чатов: {e}", exc_info=True)
                await asyncio.sleep(3600)
    
    async def reset_daily_stats_task(self):
        """Задача сброса ежедневной статистики в 00:00 МСК каждый день"""
        while self.running:
            try:
                from datetime import timedelta
                now_utc = datetime.utcnow()
                msk_offset = 3
                
                now_msk_timestamp = now_utc.timestamp() + (msk_offset * 3600)
                now_msk = datetime.fromtimestamp(now_msk_timestamp)
                
                next_midnight_msk = datetime(now_msk.year, now_msk.month, now_msk.day, 0, 0, 0)
                if now_msk >= next_midnight_msk:
                    next_midnight_msk += timedelta(days=1)
                
                time_until_midnight = (next_midnight_msk.timestamp() - now_msk_timestamp)
                
                if time_until_midnight < 60:
                    await asyncio.sleep(60)
                    await db.reset_daily_stats()
                    logger.info("✅ Ежедневная статистика автоматически сброшена в 00:00 МСК")
                    await asyncio.sleep(86400 - 60)
                else:
                    hours = int(time_until_midnight / 3600)
                    minutes = int((time_until_midnight % 3600) / 60)
                    logger.info(f"Следующий сброс ежедневной статистики в 00:00 МСК через {hours} часов {minutes} минут")
                    await asyncio.sleep(time_until_midnight)
                    await db.reset_daily_stats()
                    logger.info("✅ Ежедневная статистика автоматически сброшена в 00:00 МСК")
                    await asyncio.sleep(86400)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка при сбросе ежедневной статистики: {e}", exc_info=True)
                await asyncio.sleep(3600)


scheduler = None
