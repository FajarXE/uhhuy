# [GANTI FILE: bot/helpers/lyrics/manager.py]

import logging
from bot.helpers.lyrics.apis import MusixmatchAPI, LRCLibAPI
from bot.settings import bot_set

LOGGER = logging.getLogger(__name__)

class LyricsManager:
    def __init__(self):
        self.musixmatch = MusixmatchAPI()
        self.lrclib = LRCLibAPI()
    
    async def fetch_lyrics(self, metadata: dict, user_id: int):
        """
        Mengambil lirik berdasarkan pengaturan pengguna.
        Mengembalikan string lirik atau None.
        """
        user_settings = bot_set.user_data.get(user_id, {})
        
        # 1. Cek apakah Lirik ON/OFF (Default: OFF)
        if not user_settings.get('lyrics_status', False):
            # LOGGER.info(f"Lyrics OFF untuk user {user_id}") # Optional log
            return None

        # 2. Ambil pengaturan
        provider = user_settings.get('lyrics_provider', 'lrclib') # Default LRCLib
        l_type = user_settings.get('lyrics_type', 'plain') # Default Plain
        
        # --- PERBAIKAN UTAMA: Sanitasi Data ---
        # Pastikan tidak ada nilai None yang masuk ke API
        title = str(metadata.get('title') or '')
        artist = str(metadata.get('artist') or '')
        album = str(metadata.get('album') or '')
        
        # Durasi harus integer (detik)
        duration_raw = metadata.get('duration')
        try:
            if duration_raw:
                duration = int(float(duration_raw))
            else:
                duration = 0
        except:
            duration = 0
        # --------------------------------------

        plain = None
        synced = None

        LOGGER.info(f"Mencari lirik ({provider}) untuk: {title} - {artist}")

        try:
            if provider == 'musixmatch':
                plain, synced = await self.musixmatch.get_lyrics(title, artist, album, duration)
            elif provider == 'lrclib':
                plain, synced = await self.lrclib.get_lyrics(title, artist, album, duration)
            elif provider == 'genius':
                # Fallback ke LRCLib untuk sementara
                plain, synced = await self.lrclib.get_lyrics(title, artist, album, duration)
            
            # 3. Kembalikan tipe yang diminta
            if l_type == 'synced':
                if synced: return synced
                if plain: return plain # Fallback ke plain
            else:
                if plain: return plain
                if synced: return synced # Fallback ke synced
                
        except Exception as e:
            LOGGER.error(f"Gagal mengambil lirik: {e}")
            return None
        
        return None

lyrics_manager = LyricsManager()
