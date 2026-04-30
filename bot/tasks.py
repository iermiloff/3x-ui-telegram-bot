import asyncio
from aiogram import Bot

from services.xui_client import XUIClient
from database.repositories import UserRepository
from database.database import async_session_maker
from utils.subscription import is_subscribed
from core.logger import log

async def check_subscriptions_task(bot: Bot):
    """
    Фоновая задача для проверки подписок и деактивации VPN.
    """
    log.info("Запуск фоновой проверки подписок пользователей...")
    
    # Создаем новую сессию для фоновой задачи
    async with async_session_maker() as session:
        repo = UserRepository(session)
        
        # Получаем всех пользователей, у которых VPN сейчас активен
        all_users = await repo.get_approved_users()
        active_users = [u for u in all_users if u.is_active]
        
        if not active_users:
            log.info("Активных пользователей для проверки не найдено.")
            return

        async with XUIClient() as xui:
            for user in active_users:
                # Проверяем подписку через нашу утилиту
                subscribed = await is_subscribed(bot, user.tg_id)
                
                if not subscribed:
                    try:
                        log.info(f"Пользователь {user.tg_id} ({user.email}) отписался. Деактивация...")
                        
                        # 1. Отключаем в панели 3x-ui
                        # Используем ваш метод update_client_status
                        success = await xui.update_client_status(
                            email=user.email,
                            uuid=user.uuid,
                            inbound_id=user.inbound_id,
                            enable=False
                        )
                        
                        if success:
                            # 2. Обновляем статус в базе данных
                            await repo.update_active_status(user.id, is_active=False)
                            
                            # 3. Уведомляем пользователя
                            try:
                                await bot.send_message(
                                    user.tg_id,
                                    "⚠️ **Доступ приостановлен**\n\n"
                                    "Мы заметили, что вы отписались от наших каналов. "
                                    "Ваш VPN-доступ был автоматически отключен.\n\n"
                                    "Подпишитесь снова и нажмите любую кнопку в боте для активации."
                                )
                            except Exception as send_error:
                                log.warning(f"Не удалось отправить сообщение {user.tg_id}: {send_error}")
                                
                    except Exception as e:
                        log.error(f"Ошибка при деактивации пользователя {user.tg_id}: {e}")
                
                # Небольшая пауза между проверками, чтобы не поймать Flood Limit от Telegram
                await asyncio.sleep(0.1)

    log.info("Фоновая проверка подписок завершена.")
