# [GANTI SELURUH FILE: bot/helpers/lyrics/manager.py]

import logging
from bot.helpers.lyrics.apis import MusixmatchAPI, LRCLibAPI, GeniusAPI
from bot.settings import bot_set

LOGGER = logging.getLogger(__name__)

class LyricsManager:
    def __init__(self):
        self.musixmatch = MusixmatchAPI()
        self.lrclib = LRCLibAPI()
        self.genius = GeniusAPI()
    
    async def fetch_lyrics(self, metadata: dict, user_id: int, force: bool = False):
        """
        Mengambil lirik berdasarkan pengaturan pengguna.
        Mengembalikan string lirik atau None.
        """
        user_settings = bot_set.user_data.get(user_id) or bot_set.user_data.get(str(user_id)) or {}
        
        if not force:
            embed_lyrics = bool(user_settings.get('lyrics_status', False))
            send_file_lyrics = bool(user_settings.get('send_lyrics_file', False))
            if not (embed_lyrics or send_file_lyrics):
                return None

        provider = user_settings.get('lyrics_provider', 'lrclib') 
        l_type = user_settings.get('lyrics_type', 'plain') 
        
        title = str(metadata.get('title') or '')
        artist = str(metadata.get('artist') or '')
        album = str(metadata.get('album') or '')
        
        duration_raw = metadata.get('duration')
        try:
            duration = int(float(duration_raw)) if duration_raw else 0
        except Exception:
            duration = 0

        plain = None
        synced = None

        LOGGER.info(f"Mencari lirik ({provider}) untuk: {title} - {artist}")

        try:
            if provider == 'musixmatch':
                plain, synced = await self.musixmatch.get_lyrics(title, artist, album, duration)
            elif provider == 'lrclib':
                plain, synced = await self.lrclib.get_lyrics(title, artist, album, duration)
            elif provider == 'genius':
                plain, synced = await self.genius.get_lyrics(title, artist, album, duration)
            
            if l_type == 'synced':
                if synced: return synced
                if plain: return plain 
            else:
                if plain: return plain
                if synced: return synced 
                
        except Exception as e:
            LOGGER.error(f"Gagal mengambil lirik: {e}")
            return None
        
        return None

lyrics_manager = LyricsManager()
