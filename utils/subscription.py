from aiogram import Bot
from core.config import settings
from core.logger import log

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """
    Проверяет, подписан ли пользователь на все обязательные каналы.
    Возвращает True, если подписан или если список каналов пуст.
    """
    # Если в .env не указаны каналы, проверка всегда пройдена
    if not settings.REQUIRED_CHANNELS:
        return True

    for channel_id in settings.REQUIRED_CHANNELS:
        try:
            # Получаем информацию о статусе пользователя в канале
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            
            # Статусы, которые означают, что пользователь НЕ подписан
            # member.status может быть: 'creator', 'administrator', 'member', 'restricted', 'left', 'kicked'
            if member.status in ["left", "kicked"]:
                return False
                
        except Exception as e:
            # Ошибка может возникнуть, если бота удалили из канала или ID канала неверный
            log.error(f"Ошибка проверки подписки для {user_id} в канале {channel_id}: {e}")
            # В случае ошибки доступа к одному из каналов, 
            # мы пропускаем проверку этого канала, чтобы не блокировать юзера зря
            continue 
            
    return True
