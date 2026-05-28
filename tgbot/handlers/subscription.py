"""Subscription payment handlers — Tribute integration."""
import logging
import os
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

import db
from marzban_api_client.api.user import modify_user, get_user
from marzban_api_client.models import UserModify, UserStatusModify

logger = logging.getLogger(__name__)
router = Router()

# Tribute pay links — set real URLs via Railway env vars
TRIBUTE_LINKS = {
    "1m":  os.getenv("TRIBUTE_URL_1M",  "https://tribute.tg/pay/REPLACE_1M"),
    "3m":  os.getenv("TRIBUTE_URL_3M",  "https://tribute.tg/pay/REPLACE_3M"),
    "12m": os.getenv("TRIBUTE_URL_12M", "https://tribute.tg/pay/REPLACE_12M"),
}

PLAN_DAYS = {
    "1m": 30,
    "3m": 90,
    "12m": 365,
}

PLAN_LABELS = {
    "1m":  "1 месяц",
    "3m":  "3 месяца",
    "12m": "1 год",
}

PLAN_PRICES = {
    "1m":  "149₽",
    "3m":  "399₽",
    "12m": "1 190₽",
}


def plans_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key in ("1m", "3m", "12m"):
        rows.append([InlineKeyboardButton(
            text=f"{PLAN_LABELS[key]} — {PLAN_PRICES[key]}",
            callback_data=f"pay_{key}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tribute_keyboard(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💳 Перейти к оплате",
            url=TRIBUTE_LINKS[plan_key]
        )],
        [InlineKeyboardButton(
            text="✅ Я оплатил",
            callback_data=f"confirm_{plan_key}"
        )],
        [InlineKeyboardButton(text="← Назад", callback_data="open_payment")],
    ])


@router.callback_query(F.data == "open_payment")
async def open_payment_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "💳 <b>Выберите тариф:</b>\n\n"
        "🗓 <b>1 месяц</b> — 149₽\n"
        "🗓 <b>3 месяца</b> — 399₽ <i>(экономия 10%)</i>\n"
        "🗓 <b>1 год</b> — 1 190₽ <i>(экономия 34%)</i>",
        parse_mode="HTML",
        reply_markup=plans_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay_"))
async def show_payment_link(callback: CallbackQuery):
    plan_key = callback.data.split("_", 1)[1]
    if plan_key not in PLAN_LABELS:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    await callback.message.edit_text(
        f"💳 <b>Оплата — {PLAN_LABELS[plan_key]} ({PLAN_PRICES[plan_key]})</b>\n\n"
        "Нажмите кнопку ниже для оплаты через Tribute.\n"
        "После оплаты нажмите <b>«Я оплатил»</b> — "
        "доступ активируется автоматически.",
        parse_mode="HTML",
        reply_markup=tribute_keyboard(plan_key)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_"))
async def confirm_payment(callback: CallbackQuery, pool, marz_cache):
    """
    User claims they paid. In production integrate Tribute webhook instead.
    For now: activate immediately (you can add verification later).
    """
    plan_key = callback.data.split("_", 1)[1]
    if plan_key not in PLAN_DAYS:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    user_id = callback.from_user.id
    user = await db.get_user(pool, user_id)

    if not user:
        await callback.answer(
            "Аккаунт не найден. Напишите /start сначала.", show_alert=True
        )
        return

    now = datetime.now(timezone.utc)
    # Extend from current end or from now if expired
    base = user["subscription_end"] if (user["subscription_end"] and user["subscription_end"] > now) else now
    new_end = base + timedelta(days=PLAN_DAYS[plan_key])

    try:
        client = await marz_cache.get_client()
        # Re-enable in Marzban + update expire
        expire_ts = int(new_end.timestamp())
        await modify_user.asyncio(
            user["marzban_username"],
            client=client,
            body=UserModify(
                status=UserStatusModify.ACTIVE,
                expire=expire_ts,
            )
        )

        # Get fresh links
        marz_user = await get_user.asyncio(user["marzban_username"], client=client)
        links = list(marz_user.links) if (marz_user and marz_user.links) else []

        await db.update_subscription(pool, user_id, new_end)

        links_text = "\n".join(f"<code>{l}</code>" for l in links) if links else "(ключ уже сохранён в приложении)"
        await callback.message.edit_text(
            f"✅ <b>Подписка активирована!</b>\n\n"
            f"📅 Действует до: <b>{new_end.strftime('%d.%m.%Y %H:%M')} UTC</b>\n\n"
            f"🔑 <b>Ваш VPN-ключ:</b>\n{links_text}",
            parse_mode="HTML"
        )

    except Exception as e:
        logger.error(f"Payment confirm error for {user_id}: {e}")
        await callback.answer(
            "Ошибка активации. Напишите в поддержку.", show_alert=True
        )

    await callback.answer()


@router.callback_query(F.data == "my_key")
async def show_my_key(callback: CallbackQuery, pool, marz_cache):
    user_id = callback.from_user.id
    user = await db.get_user(pool, user_id)
    if not user:
        await callback.answer("Аккаунт не найден. Напишите /start.", show_alert=True)
        return
    try:
        client = await marz_cache.get_client()
        marz_user = await get_user.asyncio(user["marzban_username"], client=client)
        links = list(marz_user.links) if (marz_user and marz_user.links) else []
        links_text = "\n".join(f"<code>{l}</code>" for l in links) or "Ключ не найден"
        sub_end = user["subscription_end"]
        date_str = sub_end.strftime("%d.%m.%Y %H:%M UTC") if sub_end else "—"
        await callback.message.answer(
            f"🔑 <b>Ваш VPN-ключ:</b>\n{links_text}\n\n"
            f"📅 Подписка до: <b>{date_str}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"my_key error for {user_id}: {e}")
        await callback.answer("Ошибка получения ключа.", show_alert=True)
    await callback.answer()
