from aiogram import Bot
from core.config import settings

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    if not settings.REQUIRED_CHANNELS:
        return True
    for channel_id in settings.REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(channel_id, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            continue # Пропускаем, если ошибка доступа к каналу
    return True
