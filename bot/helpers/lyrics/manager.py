# [GANTI SELURUH FILE: bot/helpers/lyrics/manager.py]

import logging
# --- PERBAIKAN: Impor GeniusAPI ---
from bot.helpers.lyrics.apis import MusixmatchAPI, LRCLibAPI, GeniusAPI
from bot.settings import bot_set

LOGGER = logging.getLogger(__name__)

class LyricsManager:
    def __init__(self):
        self.musixmatch = MusixmatchAPI()
        self.lrclib = LRCLibAPI()
        # --- PERBAIKAN: Inisialisasi Genius ---
        self.genius = GeniusAPI()
    
    async def fetch_lyrics(self, metadata: dict, user_id: int):
        """
        Mengambil lirik berdasarkan pengaturan pengguna.
        Mengembalikan string lirik atau None.
        """
        user_settings = bot_set.user_data.get(user_id, {})
        
        if not user_settings.get('lyrics_status', False):
            return None

        provider = user_settings.get('lyrics_provider', 'lrclib') 
        l_type = user_settings.get('lyrics_type', 'plain') 
        
        title = str(metadata.get('title') or '')
        artist = str(metadata.get('artist') or '')
        album = str(metadata.get('album') or '')
        
        duration_raw = metadata.get('duration')
        try:
            if duration_raw: duration = int(float(duration_raw))
            else: duration = 0
        except: duration = 0

        plain = None
        synced = None

        LOGGER.info(f"Mencari lirik ({provider}) untuk: {title} - {artist}")

        try:
            if provider == 'musixmatch':
                plain, synced = await self.musixmatch.get_lyrics(title, artist, album, duration)
            elif provider == 'lrclib':
                plain, synced = await self.lrclib.get_lyrics(title, artist, album, duration)
            elif provider == 'genius':
                # --- PERBAIKAN: Panggil fungsi dari class Genius ---
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
