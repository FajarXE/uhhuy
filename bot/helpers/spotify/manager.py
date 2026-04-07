import os
import json
import asyncio
import logging
from config import Config
from .spotify_api import SpotifyAPI

LOGGER = logging.getLogger("SpotifyManager")

class SpotifyManager:
    def __init__(self):
        self.client = None
        self.authenticated = False
        self.credentials_path = os.path.join(os.getcwd(), "bot", "config", "spotify", "credentials.json")

    async def initialize_clients(self):
        LOGGER.info("Spotify: Menginisialisasi...")
        
        # [PERBAIKAN ERROR MONGODB]
        # Kita MENGHAPUS pemanggilan database.get_variable() bawaan bot yang menyebabkan crash.
        # Proses Load & Save kredensial kini 100% ditangani secara internal dan otomatis 
        # oleh spotify_api.py yang sudah memiliki koneksi PyMongo yang stabil!
        
        env_creds = getattr(Config, 'SPOTIFY_CREDENTIALS_JSON', None)
        
        if env_creds:
            try:
                os.makedirs(os.path.dirname(self.credentials_path), exist_ok=True)
                with open(self.credentials_path, "w") as f:
                    f.write(env_creds)
            except Exception as e:
                LOGGER.warning(f"Gagal menulis ENV ke file: {e}")
        
        if not os.path.exists(self.credentials_path):
            LOGGER.info("Spotify: File credentials fisik tidak ditemukan. Akan mencoba memuat dari Database Internal...")

        try:
            await asyncio.to_thread(self._sync_init)
            
            if self.client and self.client.is_authenticated():
                LOGGER.info("✅ Spotify: Berhasil Login!")
                self.authenticated = True 
            else:
                LOGGER.warning("⚠️ Spotify: Client terinisialisasi tapi tidak terautentikasi.")
                self.authenticated = True 
        except Exception as e:
            LOGGER.error(f"❌ Spotify: Error Init -> {e}")
            self.authenticated = True

    def _sync_init(self):
        config = {
            "username": "BotUser",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "credentials_location": self.credentials_path,
            "sp_dc": getattr(Config, "SPOTIFY_SP_DC", None)
        }
        
        self.client = SpotifyAPI(config=config)
        
        if hasattr(self.client, 'authenticate_stream_api'):
            self.client.authenticate_stream_api()
        elif hasattr(self.client, '_load_credentials_and_init_session'):
            self.client._load_credentials_and_init_session()

    def get_client(self):
        return self.client if self.client else None
    
    async def shutdown(self):
        pass

spotify_manager = SpotifyManager()
