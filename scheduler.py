"""Background scheduler: reminds users 1h before expiry, disables expired accounts."""
import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import db

logger = logging.getLogger(__name__)


def payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💳 Оплатить подписку", callback_data="open_payment")
    ]])


async def scheduler_loop(bot: Bot, pool, marz_cache):
    """Runs every 5 minutes. Sends reminders and disables expired users."""
    while True:
        try:
            # 1) Remind users with <= 1h left
            expiring = await db.get_expiring_unreminded(pool)
            for user in expiring:
                try:
                    await bot.send_message(
                        user["telegram_id"],
                        "⏰ <b>Остался 1 час!</b>\n\n"
                        "Ваш VPN-доступ истекает через час.\n"
                        "Продлите подписку, чтобы не потерять доступ 👇",
                        parse_mode="HTML",
                        reply_markup=payment_keyboard()
                    )
                    await db.set_reminded(pool, user["telegram_id"])
                except Exception as e:
                    logger.error(f"Reminder error for {user['telegram_id']}: {e}")

            # 2) Disable expired users in Marzban
            expired = await db.get_expired(pool)
            for user in expired:
                try:
                    from marzban_api_client.api.user import modify_user
                    from marzban_api_client.models import UserModify, UserStatusModify

                    client = await marz_cache.get_client()
                    await modify_user.asyncio(
                        user["marzban_username"],
                        client=client,
                        body=UserModify(status=UserStatusModify.DISABLED)
                    )
                    # Clear subscription_end so it doesn't keep triggering
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE users SET subscription_end = NULL WHERE telegram_id = $1",
                            user["telegram_id"]
                        )
                    await bot.send_message(
                        user["telegram_id"],
                        "❌ <b>Ваш VPN-доступ отключён.</b>\n\n"
                        "Для восстановления доступа оформите подписку 👇",
                        parse_mode="HTML",
                        reply_markup=payment_keyboard()
                    )
                except Exception as e:
                    logger.error(f"Disable error for {user['telegram_id']}: {e}")

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")

        await asyncio.sleep(300)  # check every 5 minutes
