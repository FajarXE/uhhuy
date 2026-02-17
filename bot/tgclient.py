# [GANTI FILE: bot/tgclient.py]

import os
import aiohttp
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
            workers=100,
            # --- PENGATURAN STABILITAS RENDER ---
            ipv6=False,          # Wajib False di Render untuk cegah Errno 104
            sleep_threshold=60,  # Tunggu 60s jika kena FloodWait
            # ------------------------------------
            mongodb=dict(connection=AsyncClient(Config.DATABASE_URL), remove_peers=True)
        )

    async def start(self):
        await super().start()
        LOGGER.info("BOT : Started Successfully")

        # --- FITUR: Render Deploy Notification ---
        # Mengambil data status langsung dari Render API
        if Config.RENDER_API_KEY and Config.ADMINS:
            try:
                service_id = os.getenv("RENDER_SERVICE_ID") # Render otomatis mengisi ini
                
                if service_id:
                    headers = {"Authorization": f"Bearer {Config.RENDER_API_KEY}"}
                    # Ambil deploy terakhir
                    url = f"https://api.render.com/v1/services/{service_id}/deploys?limit=1"
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, headers=headers) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                # Pastikan data deploy ada
                                if isinstance(data, list) and len(data) > 0:
                                    latest = data[0]
                                    commit_msg = latest.get('commit', {}).get('message', 'No commit info')
                                    status = latest.get('status', 'unknown')
                                    
                                    # Icon Status
                                    icon = "🟢" if status == "live" else "⚠️"
                                    
                                    msg_text = (
                                        "<b>✅ DEPLOY SELESAI!</b>\n\n"
                                        f"<b>Service:</b> <code>{service_id}</code>\n"
                                        f"<b>Status:</b> {status.upper()} {icon}\n"
                                        f"<b>Commit:</b> <code>{commit_msg}</code>"
                                    )
                                    
                                    # Kirim ke Admin Pertama
                                    admin_id = list(Config.ADMINS)[0]
                                    try:
                                        await self.send_message(admin_id, msg_text)
                                    except Exception:
                                        pass
            except Exception as e:
                LOGGER.warning(f"Gagal memuat Render Deploy Info: {e}")
        # -----------------------------------------

    async def stop(self, block=False):
        try:
            await super().stop(block)
        except Exception:
            pass
        
        # Cleanup Session
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
