# [GANTI FILE: bot/helpers/audiomack/manager.py]
import aiohttp
from bot.logger import LOGGER

class AudiomackManager:
    def __init__(self):
        # Langsung set True agar bot tahu modul ini aktif secara lokal
        self.clients = [True] 
        self.quality = "HQ"
        self.api_url = "http://127.0.0.1:8000"
        
    async def initialize_clients(self):
        # Hapus logika pengecekan aiohttp di sini agar tidak memblokir saat boot lambat
        LOGGER.info("Audiomack: Mode API Internal (Monolith) dimuat.")
        self.clients = [True]

    async def setup_quality(self, user_id, quality):
        self.quality = quality

    def has_private_session(self, user_id):
        return False

    async def shutdown(self):
        pass

audiomack_manager = AudiomackManager()
