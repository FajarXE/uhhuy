# [UPDATE: bot/helpers/spotify/manager.py]

import os
import asyncio
import logging
from bot import Config
from bot.helpers.database.mongo_async import database
from .interface import ModuleInterface

class SpotifyManager:
    def __init__(self):
        self.session = None

    async def initialize_clients(self):
        """Dijalankan saat bot startup"""
        logging.info("Spotify: Memeriksa database untuk sesi lama...")
        
        # 1. Ambil token dari MongoDB
        saved_creds = await database.get_bot_setting("spotify_creds")
        
        conf_path = os.path.join(os.getcwd(), "config", "spotify")
        os.makedirs(conf_path, exist_ok=True)
        token_file = os.path.join(conf_path, "credentials.json")

        if saved_creds:
            with open(token_file, "w") as f:
                f.write(saved_creds)
            logging.info("Spotify: Sesi berhasil dipulihkan dari Database.")

        # 2. Inisialisasi ModuleInterface OrpheusDL
        try:
            settings = {
                'client_id': Config.SPOTIFY_CLIENT_ID, 
                'client_secret': Config.SPOTIFY_CLIENT_SECRET
            }
            # MockConfig adalah class pembantu untuk menyuplai settings ke Orpheus
            from .manager_utils import MockOrpheusConfig 
            mock_config = MockOrpheusConfig(settings)
            
            self.session = await asyncio.to_thread(ModuleInterface, mock_config)
        except Exception as e:
            logging.error(f"Spotify Startup Error: {e}")

    async def complete_login(self, url):
        """Menukar URL dari user menjadi token dan simpan ke DB"""
        if not self.session:
            return False
            
        try:
            # Gunakan fungsi internal OrpheusDL untuk memproses URL login
            # Catatan: Nama fungsi mungkin berbeda tergantung versi, biasanya 'handle_auth_url'
            await asyncio.to_thread(self.session.handle_auth_url, url)
            
            # Jika berhasil, Orpheus akan menulis file credentials.json secara otomatis
            token_file = os.path.join(os.getcwd(), "config", "spotify", "credentials.json")
            
            if os.path.exists(token_file):
                with open(token_file, "r") as f:
                    content = f.read()
                
                # SIMPAN KE MONGODB
                await database.set_bot_setting("spotify_creds", content)
                return True
        except Exception as e:
            logging.error(f"Spotify Login Exchange Error: {e}")
        
        return False

# Inisialisasi instance global
spotify_manager = SpotifyManager()
