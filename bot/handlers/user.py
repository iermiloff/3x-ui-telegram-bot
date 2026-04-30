"""User handlers for the bot."""

import uuid
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from bot.keyboards.user_kb import (
    get_request_access_keyboard,
    get_main_menu_keyboard,
    get_cancel_keyboard
)
from database.repositories import UserRepository, AccessRequestRepository, ActiveInboundRepository
from services.xui_client import XUIClient
from utils.qr_generator import generate_vless_qr
from utils.formatters import format_traffic_gb, format_date, format_status
from core.config import settings
from core.logger import log
from bot.keyboards.admin_kb import get_approval_keyboard


class AccessRequestStates(StatesGroup):
    """FSM states for access request."""
    waiting_for_name = State()


router = Router()

@router.callback_query(F.data == "check_subs")
async def handle_check_subscription(callback: types.CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    user_repo = UserRepository(session)
    user = await user_repo.get_by_tg_id(user_id)

    await callback.answer() # Убираем "часики" сразу

    try:
        await callback.message.delete()
    except Exception:
        pass

    if user_id == settings.ADMIN_TG_ID:
        from bot.keyboards.admin_kb import get_admin_menu_keyboard
        await callback.message.answer(
            "👨‍💼 <b>Панель администратора</b>",
            reply_markup=get_admin_menu_keyboard()
        )
    elif user and user.is_approved:
        # ИСПРАВЛЕНИЕ: вызываем БЕЗ аргументов и БЕЗ await, как в cmd_start
        await callback.message.answer(
            f"✅ <b>Подписка подтверждена!</b>\n\n👋 Привет, {user.full_name}!\nВыберите действие:",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    else:
        await callback.message.answer(
            "👋 Добро пожаловать!\nДля получения доступа нажмите кнопку ниже:",
            reply_markup=get_request_access_keyboard()
        )

@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession):
    """Handle /start command."""
    # Check if user is admin
    if message.from_user.id == settings.ADMIN_TG_ID:
        user_repo = UserRepository(session)
        users = await user_repo.get_all()
        
        total_users = len(users)
        active_users = len([u for u in users if u.is_active])
        approved_users = len([u for u in users if u.is_approved])
        
        # Import here to avoid circular import
        from bot.keyboards.admin_kb import get_admin_menu_keyboard
        
        stats_text = (
            "👨‍💼 <b>Панель администратора</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"✅ Одобрено: {approved_users}\n"
            f"🟢 Активных: {active_users}\n\n"
            "Выберите действие:"
        )
        
        await message.answer(
            stats_text,
            reply_markup=get_admin_menu_keyboard(),
            parse_mode="HTML"
        )
        return
    
    # Regular user flow
    from bot.keyboards.user_kb import remove_keyboard
    user_repo = UserRepository(session)
    user = await user_repo.get_by_tg_id(message.from_user.id)
    
    if user and user.is_approved:
        # User is approved, show main menu
        await message.answer(
            f"👋 Привет, {user.full_name}!\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    elif user and not user.is_approved:
        # User exists but not approved yet
        await message.answer(
            "⏳ Ваша заявка на рассмотрении.\n"
            "Ожидайте одобрения администратора.",
            reply_markup=get_request_access_keyboard()
        )
    else:
        # New user
        await message.answer(
            "👋 Добро пожаловать в VPN бот!\n\n"
            "Для получения доступа к VPN нажмите кнопку ниже:",
            reply_markup=get_request_access_keyboard()
        )


@router.callback_query(F.data == "request_access")
async def request_access(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Handle access request button."""
    user_repo = UserRepository(session)
    user = await user_repo.get_by_tg_id(callback.from_user.id)
    
    if user:
        if user.is_approved:
            await callback.message.edit_text(
                "✅ У вас уже есть доступ!",
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await callback.answer(
                "⏳ Ваша заявка уже отправлена.\n"
                "Ожидайте одобрения администратора.",
                show_alert=True
            )
        return
    
    # Start FSM for name input
    await state.set_state(AccessRequestStates.waiting_for_name)
    await callback.message.edit_text(
        "📝 Пожалуйста, введите ваше имя:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_request")
async def cancel_request_callback(callback: CallbackQuery, state: FSMContext):
    """Cancel access request."""
    await state.clear()
    await callback.message.edit_text(
        "❌ Запрос отменен.",
        reply_markup=get_request_access_keyboard()
    )
    await callback.answer()


@router.message(StateFilter(AccessRequestStates.waiting_for_name))
async def process_name(message: Message, state: FSMContext, session: AsyncSession):
    """Process user name and create access request."""
    full_name = message.text.strip()
    
    if len(full_name) < 2:
        await message.answer("❌ Имя слишком короткое. Попробуйте еще раз:")
        return
    
    # Create or update user in database
    user_repo = UserRepository(session)
    request_repo = AccessRequestRepository(session)
    
    # Format email as "Name_Username" or "Name_TelegramID"
    username_part = message.from_user.username if message.from_user.username else str(message.from_user.id)
    email = f"{full_name}_{username_part}"
    
    try:
        # Check if user already exists
        existing_user = await user_repo.get_by_tg_id(message.from_user.id)
        
        if existing_user:
            # Update existing user's data
            log.info(f"Updating existing user {existing_user.id}: old_email={existing_user.email}, new_email={email}")
            
            from database.models import User
            
            await session.execute(
                update(User)
                .where(User.id == existing_user.id)
                .values(
                    full_name=full_name,
                    email=email,
                    username=message.from_user.username,
                    updated_at=datetime.utcnow()
                )
            )
            await session.commit()
            
            user = await user_repo.get_by_id(existing_user.id)
        else:
            # Create new user
            user_uuid = str(uuid.uuid4())
            user = await user_repo.create(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                full_name=full_name,
                uuid=user_uuid,
                email=email
            )
        
        # Create access request
        access_request = await request_repo.create(user.id)
        
        # Notify admin
        admin_message = (
            "🔔 <b>Новая заявка на доступ</b>\n\n"
            f"👤 Имя: {full_name}\n"
            f"🆔 Telegram ID: {message.from_user.id}\n"
            f"📱 Username: @{message.from_user.username or 'нет'}\n"
        )
        
        await message.bot.send_message(
            settings.ADMIN_TG_ID,
            admin_message,
            reply_markup=get_approval_keyboard(user.id, access_request.id),
            parse_mode="HTML"
        )
        
        await state.clear()
        await message.answer(
            "✅ Заявка отправлена!\n"
            "Ожидайте одобрения администратора."
        )
        
        log.info(f"Access request created: user_id={user.id}, tg_id={message.from_user.id}")
    
    except Exception as e:
        log.error(f"Error creating access request: {e}")
        await message.answer(
            "❌ Произошла ошибка. Попробуйте позже.",
            reply_markup=get_request_access_keyboard()
        )
        await state.clear()


@router.callback_query(F.data == "user_profile")
async def show_profile(callback: CallbackQuery, session: AsyncSession):
    """Show user profile with traffic statistics."""
    user_repo = UserRepository(session)
    user = await user_repo.get_by_tg_id(callback.from_user.id)
    
    if not user or not user.is_approved:
        await callback.message.edit_text(
            "❌ У вас нет доступа. Запросите доступ сначала.",
            reply_markup=get_request_access_keyboard()
        )
        await callback.answer()
        return
    
    # Get traffic statistics from 3x-ui
    try:
        async with XUIClient() as xui:
            traffic = await xui.get_client_traffic(user.email)
            traffic_used = format_traffic_gb(traffic["total"])
    except Exception as e:
        log.error(f"Error getting traffic stats: {e}")
        traffic_used = "Недоступно"
    
    profile_text = (
        "👤 <b>Ваш профиль</b>\n\n"
        f"📝 Имя: {user.full_name}\n"
        f"🔐 Протокол: {user.protocol}\n"
        f"📊 Статус: {format_status(user.is_active)}\n"
        f"📈 Использовано трафика: {traffic_used}\n"
        f"📅 Дата подключения: {format_date(user.created_at)}\n"
    )
    
    # Add back button
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="user_menu")]
        ]
    )
    
    await callback.message.edit_text(profile_text, reply_markup=back_kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "user_connection")
async def show_connection(callback: CallbackQuery, session: AsyncSession):
    """Generate and show connection link and QR code."""
    user_repo = UserRepository(session)
    user = await user_repo.get_by_tg_id(callback.from_user.id)
    
    if not user or not user.is_approved:
        await callback.message.edit_text(
            "❌ У вас нет доступа. Запросите доступ сначала.",
            reply_markup=get_request_access_keyboard()
        )
        await callback.answer()
        return
    
    if not user.is_active:
        await callback.answer(
            "❌ Ваш доступ деактивирован.\n"
            "Обратитесь к администратору.",
            show_alert=True
        )
        return
    
    try:
        # Get connection link from 3x-ui API
        connection_link = None
        
        if user.inbound_id:
            # Get link from 3x-ui
            async with XUIClient() as xui:
                connection_link = await xui.get_client_link(user.inbound_id, user.email)
        
        if not connection_link:
            # Fallback: generate link manually (for old users or if API fails)
            log.warning(f"Could not get link from API, generating manually for {user.email}")
            from utils.qr_generator import generate_vless_link
            connection_link = generate_vless_link(
                user.uuid,
                user.email,
                server=settings.VLESS_SERVER,
                port=settings.VLESS_PORT,
                sni=settings.VLESS_SNI
            )
        
        # Generate QR code from link
        from utils.qr_generator import generate_qr_code
        qr_image = generate_qr_code(connection_link)
        
        # Send QR code
        qr_file = BufferedInputFile(qr_image.read(), filename="vpn_qr.png")
        
        # Add back button
        back_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="user_menu")]
            ]
        )
        
        await callback.message.answer_photo(
            qr_file,
            caption=(
                "🔗 <b>Подключение к VPN</b>\n\n"
                "Отсканируйте QR-код или скопируйте ссылку ниже:\n\n"
                f"<code>{connection_link}</code>"
            ),
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        
        # Delete the menu message
        await callback.message.delete()
        
        log.info(f"Connection info sent to user: tg_id={callback.from_user.id}")
        await callback.answer()
    
    except Exception as e:
        log.error(f"Error generating connection info: {e}")
        await callback.answer("❌ Ошибка при генерации данных подключения.", show_alert=True)


@router.callback_query(F.data == "user_instructions")
async def show_instructions(callback: CallbackQuery):
    """Show VPN client installation instructions."""
    instructions = (
        "📖 <b>Инструкции по подключению</b>\n\n"
        "<b>Шаг 1: Установите приложение</b>\n\n"
        "📱 <b>Android:</b>\n"
        "AmneziaVPN - https://play.google.com/store/apps/details?id=org.amnezia.vpn&hl=ru\n\n"
        "💻 <b>Windows/Linux:</b>\n"
        "AmneziaVPN - https://github.com/amnezia-vpn/amnezia-client/releases/download/4.8.11.1/AmneziaVPN_4.8.11.1_x64.exe\n\n"
        "🍎 <b>iOS:</b>\n"
        "V2Ray - https://apps.apple.com/ru/app/v2ray-client/id6747379524\n\n"
        "<b>Шаг 2: Подключитесь</b>\n"
        "1. Нажмите кнопку '🔗 Подключиться' в боте\n"
        "2. Отсканируйте QR-код в приложении или скопируйте ссылку\n"
        "3. Нажмите 'Подключиться' в приложении\n\n"
        "✅ Готово! Вы подключены к VPN."
    )
    
    # Add back button
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="user_menu")]
        ]
    )
    
    await callback.message.edit_text(instructions, reply_markup=back_kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "user_menu")
async def show_user_menu(callback: CallbackQuery, session: AsyncSession):
    """Show user main menu."""
    user_repo = UserRepository(session)
    user = await user_repo.get_by_tg_id(callback.from_user.id)
    
    if not user or not user.is_approved:
        # Try to delete if it's a photo message
        try:
            await callback.message.delete()
        except:
            pass
        
        await callback.bot.send_message(
            callback.from_user.id,
            "❌ У вас нет доступа.",
            reply_markup=get_request_access_keyboard()
        )
        await callback.answer()
        return
    
    # If it's a photo message (from connection), delete it and send new menu
    if callback.message.photo:
        await callback.message.delete()
        await callback.bot.send_message(
            callback.from_user.id,
            f"👋 Привет, {user.full_name}!\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    else:
        # If it's a text message, edit it
        await callback.message.edit_text(
            f"👋 Привет, {user.full_name}!\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )
    
    await callback.answer()
