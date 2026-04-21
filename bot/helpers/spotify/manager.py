# [FILE: bot/helpers/spotify/manager.py]

import logging
import asyncio
from bot import Config
from .interface import ModuleInterface 

class SpotifyManager:
    def __init__(self):
        self.session = None
        self.quality = "VERY_HIGH"

    async def initialize_clients(self):
        logging.info("Spotify: Memulai inisialisasi...")
        try:
            module_settings = {
                'client_id': Config.SPOTIFY_CLIENT_ID,
                'client_secret': Config.SPOTIFY_CLIENT_SECRET,
            }
            
            # Hapus flags=None, lemparkan module_settings langsung
            self.session = await asyncio.to_thread(
                ModuleInterface, 
                module_settings
            )
            
            logging.info("Spotify: Inisialisasi berhasil.")
        except Exception as e:
            logging.error(f"Spotify Init Error: {e}")

    async def shutdown(self):
        if self.session:
            logging.info("Spotify: Menutup sesi...")
            try:
                if hasattr(self.session, 'cleanup'):
                    await asyncio.to_thread(self.session.cleanup)
                elif hasattr(self.session, 'close'):
                    await asyncio.to_thread(self.session.close)
            except Exception as e:
                logging.debug(f"Spotify shutdown catch: {e}")

spotify_manager = SpotifyManager()
