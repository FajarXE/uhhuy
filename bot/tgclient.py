# [FILE: bot/tgclient.py]

from config import Config
from pyrogram import Client
from .logger import LOGGER
from .settings import bot_set

plugins = dict(root="bot/modules")

class Bot(Client):
    def __init__(self):
        super().__init__(
            name=Config.BOT_USERNAME,
            api_id=Config.APP_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.TG_BOT_TOKEN,
            plugins=plugins,
            workdir=Config.WORK_DIR,
            in_memory=True,  # [FIX] Konsisten dengan mode In-Memory (bebas SQLite lock)
            ipv6=False,
            workers=20,
            sleep_threshold=30
        )

    async def start(self):
        await super().start()
        LOGGER.info("BOT : Started Successfully")

        try:
            if Config.ADMINS:
                admin_id = list(Config.ADMINS)[0]
                await self.send_message(
                    admin_id,
                    "✅ **Bot Restart (Memory Mode)!**\n\n"
                    "Database Session dialihkan ke RAM (In-Memory) untuk mencegah crash database."
                )
        except Exception as e:
            LOGGER.warning(f"Gagal mengirim notif startup: {e}")

    async def stop(self, block=False):
        try:
            await super().stop(block)
        except Exception:
            pass
        
        if hasattr(bot_set, 'clients') and bot_set.clients:
            for client in bot_set.clients:
                try:
                    if hasattr(client, 'session') and client.session:
                        await client.session.close()
                except Exception:
                    pass
            
        LOGGER.info('BOT : Exited Successfully ! Bye..........')

aio = Bot()
