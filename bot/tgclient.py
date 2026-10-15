# [FILE: bot/tgclient.py]

import asyncio
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
        # [FIX] Auto-Retry saat membuat koneksi MTProto ke Data Center Telegram
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                await super().start()
                break
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                if attempt == max_retries:
                    LOGGER.critical(f"BOT : Gagal terhubung ke server Telegram setelah {max_retries} percobaan!")
                    raise e
                wait_time = attempt * 3
                LOGGER.warning(
                    f"BOT : Koneksi ke DC Telegram terputus (Percobaan {attempt}/{max_retries}). "
                    f"Mencoba lagi dalam {wait_time} detik..."
                )
                await asyncio.sleep(wait_time)

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
                    if hasattr(client, 'session') and client.session and not client.session.closed:
                        await client.session.close()
                except Exception:
                    pass
            
        LOGGER.info('BOT : Exited Successfully ! Bye..........')

aio = Bot()
