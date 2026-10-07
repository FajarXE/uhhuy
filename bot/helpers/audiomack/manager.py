# [BUAT FILE: bot/helpers/audiomack/manager.py]
import aiohttp
from bot.logger import LOGGER

class AudiomackManager:
    def __init__(self):
        self.clients = []
        self.quality = "HQ"
        self.api_url = "http://127.0.0.1:8000"
        
    async def initialize_clients(self):
        try:
            # Memastikan scraper FastAPI lokal sudah berjalan
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url) as resp:
                    if resp.status == 200:
                        LOGGER.info("Audiomack: Scraper Internal terhubung dengan baik.")
                        self.clients = [True]
                    else:
                        self.clients = []
        except Exception as e:
            LOGGER.warning(f"Audiomack API Internal tidak bisa dijangkau: {e}")
            self.clients = []

    async def setup_quality(self, user_id, quality):
        self.quality = quality

    def has_private_session(self, user_id):
        return False

    async def shutdown(self):
        pass

audiomack_manager = AudiomackManager()
