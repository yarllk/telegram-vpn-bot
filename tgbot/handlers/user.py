"""Handler for /start command — issues 8-hour trial on first launch."""
import logging
import uuid
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import db
from marzban_api_client.api.user import add_user, get_user
from marzban_api_client.models import UserCreate, ProxySettings, UserStatusCreate

logger = logging.getLogger(__name__)
router = Router()

TRIAL_HOURS = 8
INBOUND_TAG = "vless-ws-tls"  # matches your Marzban inbound


def vpn_key_message(links: list[str]) -> str:
    links_text = "\n".join(f"<code>{l}</code>" for l in links)
    return (
        "✅ <b>Вам выдан пробный доступ на 8 часов!</b>\n\n"
        "🔑 <b>Ваш VPN-ключ:</b>\n"
        f"{links_text}\n\n"
        "📱 Импортируйте ключ в приложение <b>v2rayTUN</b> (iOS/Android) "
        "или <b>Hiddify</b> (Windows/Mac).\n\n"
        "⏰ Через 7 часов придёт напоминание о продлении."
    )


def already_active_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔑 Мой ключ", callback_data="my_key"),
        InlineKeyboardButton(text="💳 Подписка", callback_data="open_payment"),
    ]])


def trial_ended_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💳 Оформить подписку", callback_data="open_payment")
    ]])


@router.message(CommandStart())
async def cmd_start(message: Message, pool, marz_cache):
    user_id = message.from_user.id
    existing = await db.get_user(pool, user_id)

    # --- Already has an active subscription ---
    if existing and existing["subscription_end"] and existing["subscription_end"] > datetime.now(timezone.utc):
        remaining = existing["subscription_end"] - datetime.now(timezone.utc)
        hours = int(remaining.total_seconds() // 3600)
        await message.answer(
            f"✅ <b>У вас активная подписка!</b>\n"
            f"Осталось примерно <b>{hours} ч.</b>\n\n"
            "Используйте кнопки ниже:",
            parse_mode="HTML",
            reply_markup=already_active_keyboard()
        )
        return

    # --- Trial already used, no active sub ---
    if existing and existing["trial_used"]:
        await message.answer(
            "👋 С возвращением!\n\n"
            "Ваш пробный период уже использован.\n"
            "Оформите подписку для продолжения 👇",
            parse_mode="HTML",
            reply_markup=trial_ended_keyboard()
        )
        return

    # --- New user: issue trial ---
    await message.answer("⏳ Создаю ваш VPN-аккаунт...")

    marzban_username = f"tg_{user_id}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    try:
        client = await marz_cache.get_client()

        # Create user in Marzban with 8-hour expiry
        expire_ts = int((now.timestamp()) + TRIAL_HOURS * 3600)
        new_user = await add_user.asyncio(
            client=client,
            body=UserCreate(
                username=marzban_username,
                proxies={INBOUND_TAG: ProxySettings()},
                expire=expire_ts,
                status=UserStatusCreate.ACTIVE,
                data_limit=0,
                data_limit_reset_strategy="no_reset",
                inbounds={INBOUND_TAG: [INBOUND_TAG]},
            )
        )

        if new_user is None:
            raise ValueError("Marzban returned None for new user")

        # Save to DB
        await db.create_user(pool, user_id, marzban_username, now)

        # Extract VLESS links
        links = list(new_user.links) if new_user.links else []
        if not links:
            links = [f"vless://...@{marzban_username} (ключ создан в Marzban)"]

        await message.answer(
            vpn_key_message(links),
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Trial creation failed for {user_id}: {e}")
        await message.answer(
            "❌ Не удалось создать VPN-аккаунт. Попробуйте через минуту или напишите в поддержку."
        )
