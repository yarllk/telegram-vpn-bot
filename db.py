"""asyncpg database layer for the VPN bot."""
import asyncpg
import os
from datetime import datetime, timezone, timedelta


async def create_pool():
    return await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=5)


async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id      BIGINT PRIMARY KEY,
                marzban_username TEXT NOT NULL,
                trial_used       BOOLEAN DEFAULT FALSE,
                trial_started    TIMESTAMPTZ,
                subscription_end TIMESTAMPTZ,
                reminded         BOOLEAN DEFAULT FALSE,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)


async def get_user(pool, telegram_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1", telegram_id
        )


async def create_user(pool, telegram_id: int, marzban_username: str, trial_started: datetime):
    """Create a new user with 8-hour trial subscription."""
    subscription_end = trial_started + timedelta(hours=8)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (telegram_id, marzban_username, trial_used, trial_started, subscription_end)
            VALUES ($1, $2, TRUE, $3, $4)
            ON CONFLICT (telegram_id) DO NOTHING
            """,
            telegram_id, marzban_username, trial_started, subscription_end
        )


async def update_subscription(pool, telegram_id: int, subscription_end: datetime):
    """Update subscription end date and reset reminder flag."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET subscription_end = $1, reminded = FALSE
            WHERE telegram_id = $2
            """,
            subscription_end, telegram_id
        )


async def set_reminded(pool, telegram_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET reminded = TRUE WHERE telegram_id = $1",
            telegram_id
        )


async def get_expiring_unreminded(pool):
    """Users with <= 1 hour left on subscription, not yet reminded."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT * FROM users
            WHERE reminded = FALSE
              AND subscription_end IS NOT NULL
              AND subscription_end <= NOW() + INTERVAL '1 hour'
              AND subscription_end > NOW()
            """
        )


async def get_expired(pool):
    """Users whose subscription has expired."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT * FROM users
            WHERE subscription_end IS NOT NULL
              AND subscription_end <= NOW()
            """
        )
