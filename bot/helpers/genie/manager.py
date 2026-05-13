# [FILE: bot/helpers/genie/manager.py]

from bot.logger import LOGGER
from bot.helpers.database.mongo_async import database
from bot.settings import bot_set

class GenieManager:
    def __init__(self):
        self.quality = 'flac24' # Default fallback
        
    async def initialize_clients(self):
        # Memuat kualitas global dari database saat bot start
        settings = await database.get_variable()
        if settings and 'GENIE_QUALITY' in settings:
            self.quality = settings['GENIE_QUALITY']
        LOGGER.info(f"Genie Manager initialized with default quality: {self.quality}")

    async def setup_quality(self, user_id: int, quality: str):
        # Menyimpan pengaturan kualitas spesifik untuk user
        bot_set.user_data.setdefault(user_id, {})['genie_qual'] = quality
        
    def get_user_quality(self, user_id: int) -> str:
        user_dict = bot_set.user_data.get(user_id, {})
        return user_dict.get('genie_qual', self.quality)

    async def shutdown(self):
        pass

genie_manager = GenieManager()
