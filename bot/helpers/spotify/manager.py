# [FILE: bot/helpers/spotify/manager.py]

import os
import logging
import asyncio
from bot import Config
from bot.helpers.database.mongo_async import database
from .interface import ModuleInterface 

# --- REVISI MOCK OBJECT (VERSI LENGKAP) ---
class MockPrinter:
    """Mencegah error saat OrpheusDL mencoba memanggil fungsi cetak"""
    def print(self, *args, **kwargs):
        # Biarkan kosong karena kita sudah pakai logging bot sendiri
        pass

class MockOrpheusConfig:
    def __init__(self, settings_dict):
        self.module_settings = settings_dict
        self.module_error = None
        self.global_settings = {}
        # FIX: Tambahkan printer_controller dengan fungsi print kosong
        self.printer_controller = MockPrinter() 
# ------------------------------------------

class SpotifyManager:
    def __init__(self):
        self.session = None

    async def initialize_clients(self):
        logging.info("Spotify: Memeriksa database untuk sesi lama...")
        
        # Ambil token dari MongoDB
        saved_creds = await database.get_bot_setting("spotify_creds")
        
        conf_path = os.path.join(os.getcwd(), "config", "spotify")
        os.makedirs(conf_path, exist_ok=True)
        token_file = os.path.join(conf_path, "credentials.json")

        if saved_creds:
            with open(token_file, "w") as f:
                f.write(saved_creds)
            logging.info("Spotify: Sesi berhasil dipulihkan dari Database.")

        try:
            # 1. Siapkan settings
            settings_dict = {
                'client_id': Config.SPOTIFY_CLIENT_ID,
                'client_secret': Config.SPOTIFY_CLIENT_SECRET,
            }
            
            # 2. Bungkus ke MockConfig yang sudah diperbaiki lagi
            mock_config = MockOrpheusConfig(settings_dict)
            
            # 3. Inisialisasi ModuleInterface
            # Menggunakan thread agar tidak memblokir event loop utama
            self.session = await asyncio.to_thread(ModuleInterface, mock_config)
            
            logging.info("Spotify: Inisialisasi berhasil.")
        except Exception as e:
            logging.error(f"Spotify Init Error: {e}")

    async def complete_login(self, url):
        """Menukar URL redirect menjadi token dan simpan ke DB"""
        if not self.session:
            return False
            
        try:
            # Tukar URL menjadi file credentials.json
            await asyncio.to_thread(self.session.handle_auth_url, url)
            
            token_file = os.path.join(os.getcwd(), "config", "spotify", "credentials.json")
            if os.path.exists(token_file):
                with open(token_file, "r") as f:
                    content = f.read()
                
                # Simpan ke MongoDB agar permanen
                await database.set_bot_setting("spotify_creds", content)
                return True
        except Exception as e:
            logging.error(f"Spotify Login Error: {e}")
        return False

spotify_manager = SpotifyManager()
