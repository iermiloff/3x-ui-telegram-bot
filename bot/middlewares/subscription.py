from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.subscription import is_subscribed
from services.xui_client import XUIClient
from database.repositories import UserRepository
from core.config import settings
from core.logger import log

class CheckSubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        # Работаем только с сообщениями и кнопками
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        # Пропускаем проверку для администраторов
        user_id = event.from_user.id
        if user_id in settings.ADMIN_IDS:
            return await handler(event, data)

        bot = data['bot']
        # Получаем сессию из вашего DatabaseMiddleware
        session = data.get("session")
        if not session:
            log.error("Session not found in Middleware data")
            return await handler(event, data)

        repo = UserRepository(session)

        # 1. Проверяем подписку на все каналы
        subscribed = await is_subscribed(bot, user_id)
        
        if subscribed:
            # 2. АВТО-АКТИВАЦИЯ: Если пользователь подписан, но VPN в базе выключен
            user = await repo.get_by_tg_id(user_id)
            if user and user.is_approved and not user.is_active:
                try:
                    async with XUIClient() as xui:
                        # Включаем клиента в панели 3x-ui
                        success = await xui.update_client_status(
                            email=user.email,
                            uuid=user.uuid,
                            inbound_id=user.inbound_id,
                            enable=True
                        )
                        if success:
                            # Включаем статус в нашей базе данных
                            await repo.update_active_status(user.id, True)
                            await bot.send_message(
                                user_id, 
                                "✅ **Подписка подтверждена!**\nВаш VPN-доступ был автоматически активирован."
                            )
                            log.info(f"Auto-activated VPN for user {user_id}")
                except Exception as e:
                    log.error(f"Error during auto-activation for {user_id}: {e}")
            
            # Пропускаем к выполнению основной команды
            return await handler(event, data)

        # 3. ЕСЛИ НЕ ПОДПИСАН: Блокируем доступ и выводим кнопки
        builder = InlineKeyboardBuilder()
        
        # Динамически создаем кнопки на основе списка URL из .env
        for i, url in enumerate(settings.CHANNEL_URLS, start=1):
            builder.row(InlineKeyboardButton(
                text=f"📢 Подписаться на канал №{i}", 
                url=url
            ))

        # Добавляем кнопку ручной проверки
        builder.row(InlineKeyboardButton(
            text="🔄 Проверить подписку", 
            callback_data="check_subs"
        ))

        error_text = (
            "⚠️ **Доступ ограничен**\n\n"
            "Для использования этого VPN-бота необходимо быть подписанным на наши информационные каналы.\n\n"
            "После подписки нажмите кнопку «Проверить подписку» или просто отправьте любую команду."
        )

        if isinstance(event, Message):
            await event.answer(error_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        elif isinstance(event, CallbackQuery):
            # Если юзер нажал на кнопку, а подписки всё еще нет
            if event.data == "check_subs":
                await event.answer("❌ Вы всё еще не подписаны на все каналы!", show_alert=True)
            else:
                # Для всех остальных кнопок просто показываем предупреждение
                await event.message.edit_text(error_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        
        return # Прерываем выполнение хендлера
