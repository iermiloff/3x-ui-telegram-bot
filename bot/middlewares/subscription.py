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
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        bot = data['bot']
        session = data.get("session")
        if not session:
            return await handler(event, data)

        repo = UserRepository(session)
        user_id = event.from_user.id

        # 1. Проверяем подписку
        subscribed = await is_subscribed(bot, user_id)
        
        if subscribed:
            # АВТО-АКТИВАЦИЯ
            user = await repo.get_by_tg_id(user_id)
            if user and user.is_approved and not user.is_active:
                try:
                    async with XUIClient() as xui:
                        success = await xui.update_client_status(
                            email=user.email, uuid=user.uuid, inbound_id=user.inbound_id, enable=True
                        )
                        if success:
                            await repo.update_active_status(user.id, True)
                            await bot.send_message(user_id, "✅ VPN активирован!")
                except Exception as e:
                    log.error(f"Error auto-activation: {e}")
            
            return await handler(event, data)

        # 2. ЕСЛИ НЕ ПОДПИСАН
        builder = InlineKeyboardBuilder()
        for i, url in enumerate(settings.CHANNEL_URLS, start=1):
            builder.row(InlineKeyboardButton(text=f"📢 Канал №{i}", url=url))
        builder.row(InlineKeyboardButton(text="🔄 Я подписался", callback_data="check_subs"))

        text = "❌ **Доступ ограничен**\n\nПожалуйста, подпишитесь на наши каналы для использования VPN."

        if isinstance(event, Message):
            await event.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        elif isinstance(event, CallbackQuery):
            # ВОТ ЗДЕСЬ БЫЛА ОШИБКА. Добавляем логику ответа на кнопку
            if event.data == "check_subs":
                await event.answer("⚠️ Вы всё еще не подписались!", show_alert=True)
            else:
                # Для других кнопок просто обновляем текст
                try:
                    await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
                except:
                    pass
        
        return # Прерываем выполнение
