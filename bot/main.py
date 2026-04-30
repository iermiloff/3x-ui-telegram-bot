import asyncio
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.config import settings
from core.logger import log
from database.database import init_db, async_session_maker
from bot.middlewares.auth import DatabaseMiddleware
from bot.middlewares.subscription import CheckSubscriptionMiddleware
from bot.handlers import user, admin
from bot.tasks import check_subscriptions_task


async def main():
    """Инициализация и запуск VPN бота."""
    log.info("Starting VPN bot with subscription control...")
    
    # 1. Инициализация базы данных (создание таблиц, если их нет)
    try:
        await init_db()
    except Exception as e:
        log.error(f"Failed to initialize database: {e}")
        sys.exit(1)
    
    # 2. Настройка бота и диспетчера
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    dp = Dispatcher()
    
    # 3. Регистрация Middlewares
    # ПОРЯДОК ВАЖЕН: сначала DatabaseMiddleware создает сессию БД, 
    # затем CheckSubscriptionMiddleware ее использует.
    dp.message.middleware(DatabaseMiddleware(async_session_maker))
    dp.callback_query.middleware(DatabaseMiddleware(async_session_maker))
    
    dp.message.middleware(CheckSubscriptionMiddleware())
    dp.callback_query.middleware(CheckSubscriptionMiddleware())
    
    # 4. Регистрация роутеров (обработчиков команд)
    dp.include_router(user.router)
    dp.include_router(admin.router)
    
    # 5. Настройка планировщика (Background Tasks)
    scheduler = AsyncIOScheduler()
    # Проверка подписок раз в 60 минут (можно изменить в настройках)
    scheduler.add_job(
        check_subscriptions_task, 
        "interval", 
        minutes=60, 
        args=[bot],
        id="check_subs_job",
        replace_existing=True
    )
    scheduler.start()
    
    log.info("Bot and Scheduler initialized successfully")
    
    # 6. Запуск polling (прослушивания обновлений)
    try:
        log.info("Starting polling...")
        # resolve_used_update_types автоматически определяет, какие типы обновлений нужны (message, callback_query и т.д.)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        log.error(f"Error during polling: {e}")
    finally:
        # Корректное закрытие сессий при остановке
        await bot.session.close()
        scheduler.shutdown()
        log.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot stopped by user (Ctrl+C)")
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        sys.exit(1)
