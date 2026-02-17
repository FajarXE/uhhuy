# [FILE: bot/tgclient.py]

from config import Config
from pyrogram import Client
from async_pymongo import AsyncClient
from .logger import LOGGER
from .settings import bot_set

# Import manager dengan aman
try:
    from bot import BOT_QOBUZ_CLIENTS 
except ImportError:
    BOT_QOBUZ_CLIENTS = {}

try: from .helpers.deezer.manager import deezer_manager
except ImportError: deezer_manager = None

try: from .helpers.beatport.manager import beatport_manager
except ImportError: beatport_manager = None

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
            in_memory=True,
            ipv6=False,
            workers=100,
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
                except Exception: pass
        
        # Cleanup Qobuz
        if BOT_QOBUZ_CLIENTS:
            for client in BOT_QOBUZ_CLIENTS.values():
                try: await client.close_session() 
                except: pass
            
        # Cleanup Deezer
        if deezer_manager and hasattr(deezer_manager, 'clients'):
            for client in deezer_manager.clients:
                try: 
                    if client.session and not client.session.closed:
                        await client.session.close()
                except: pass
                
        # Cleanup Beatport
        if beatport_manager and hasattr(beatport_manager, 'clients'):
            for client in beatport_manager.clients:
                try:
                    if hasattr(client, 'session') and client.session and not client.session.closed:
                        await client.session.close()
                except: pass
            
        LOGGER.info('BOT : Exited Successfully ! Bye..........')

aio = Bot()
