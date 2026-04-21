# [FILE: bot/helpers/spotify/manager.py]

import logging
import json
import os
import asyncio
from bot import Config

# Ganti import menjadi ModuleInterface (nama asli dari OrpheusDL)
from .interface import ModuleInterface 

class SpotifyManager:
    def __init__(self):
        self.session = None
        self.quality = "VERY_HIGH" # Default prioritas tinggi (320kbps Ogg)

    async def initialize_clients(self):
        logging.info("Spotify: Memulai inisialisasi...")
        try:
            # OrpheusDL mengharapkan dictionary bernama module_settings
            module_settings = {
                'client_id': Config.SPOTIFY_CLIENT_ID,
                'client_secret': Config.SPOTIFY_CLIENT_SECRET,
                # Anda bisa menyuntikkan path/token lain di sini jika dibutuhkan oleh desktop_api
            }
            
            # Kita lempar ke thread terpisah agar proses login/init OrpheusDL
            # yang bersifat sinkron tidak mencekik event loop uvloop
            self.session = await asyncio.to_thread(
                ModuleInterface, 
                flags=None, 
                module_settings=module_settings
            )
            
            logging.info("Spotify: Inisialisasi berhasil.")
        except Exception as e:
            logging.error(f"Spotify Init Error: {e}")

    async def shutdown(self):
        # OrpheusDL tidak selalu memiliki fungsi close() async bawaan,
        # jadi kita pastikan pembersihannya aman tanpa menyebabkan error.
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
