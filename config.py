from dataclasses import dataclass

from environs import Env


@dataclass
class TgBot:
    token: str
    admin_id: int

    @staticmethod
    def from_env(env: Env):
        token = env.str("BOT_TOKEN")
        admin_id = env.int("ADMIN")

        return TgBot(token=token, admin_id=admin_id)


@dataclass
class Webhook:
    url: str
    domain: str
    use_webhook: bool

    @staticmethod
    def from_env(env: Env):
        url = env.str("SERVER_URL", default="")
        domain = env.str("DOMAIN", default="localhost")
        use_webhook = env.bool("USE_WEBHOOK", default=False)
        return Webhook(url=url, domain=domain, use_webhook=use_webhook)


@dataclass
class Marzban:
    base_url: str
    username: str
    password: str
    token_expire: int
    verify_ssl: bool

    @staticmethod
    def from_env(env: Env):
        return Marzban(
            base_url=env.str("MARZBAN_BASE_URL"),
            username=env.str("MARZBAN_USERNAME"),
            password=env.str("MARZBAN_PASSWORD"),
            token_expire=env.int("MARZBAN_TOKEN_EXPIRE", 1440),
            verify_ssl=env.bool("MARZ_HAS_CERTIFICATE", True),
        )


@dataclass
class Config:
    tg_bot: TgBot
    webhook: Webhook
    marzban: Marzban


def load_config():
    env = Env()
    # On Railway / Heroku-style PaaS env vars are injected, so a missing
    # .env file is OK — environs.Env.read_env handles that silently.
    env.read_env(".env")
    return Config(
        tg_bot=TgBot.from_env(env),
        webhook=Webhook.from_env(env),
        marzban=Marzban.from_env(env),
    )
