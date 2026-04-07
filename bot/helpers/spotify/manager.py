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
        # Path kredensial
        self.credentials_path = os.path.join(os.getcwd(), "bot", "config", "spotify", "credentials.json")

    async def initialize_clients(self):
        """
        Dijalankan saat startup. Memuat kredensial dari ENV, Database, atau File.
        """
        LOGGER.info("Spotify: Menginisialisasi...")
        
        # --- [1] AMBIL DATA DARI DATABASE (MONGODB) ---
        from bot.helpers.database.mongo_async import database
        
        # Ambil Token Login OAuth
        saved_creds = await database.get_variable("SPOTIFY_CREDENTIALS_JSON")
        if saved_creds:
            Config.SPOTIFY_CREDENTIALS_JSON = saved_creds
            LOGGER.info("Spotify: Kredensial login dimuat dari Database.")
            
        # Ambil Cookie sp_dc (Untuk FLAC)
        saved_sp_dc = await database.get_variable("SPOTIFY_SP_DC")
        if saved_sp_dc:
            Config.SPOTIFY_SP_DC = saved_sp_dc
            LOGGER.info("Spotify: Cookie sp_dc dimuat dari Database.")

        # --- [2] PENANGANAN FILE KREDENSIAL ---
        env_creds = getattr(Config, 'SPOTIFY_CREDENTIALS_JSON', None)
        
        if env_creds:
            try:
                os.makedirs(os.path.dirname(self.credentials_path), exist_ok=True)
                with open(self.credentials_path, "w") as f:
                    f.write(env_creds)
            except Exception as e:
                LOGGER.warning(f"Gagal menulis kredensial ke file: {e}")
        
        if not os.path.exists(self.credentials_path):
            LOGGER.warning("Spotify: File credentials.json tidak ditemukan. Harap login via /spotify_login.")
            self.authenticated = False
            return

        # --- [3] INISIALISASI API ---
        try:
            # Jalankan di thread agar tidak memblokir bot saat booting
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
        """Fungsi sinkronus untuk init API"""
        config = {
            "username": "BotUser",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "credentials_location": self.credentials_path,
            # Teruskan SP_DC ke API agar bisa digunakan oleh Desktop API (PlayPlay)
            "sp_dc": getattr(Config, "SPOTIFY_SP_DC", None)
        }
        
        self.client = SpotifyAPI(config=config)
        
        # Load sesi
        if hasattr(self.client, 'authenticate_stream_api'):
            self.client.authenticate_stream_api()
        elif hasattr(self.client, '_load_credentials_and_init_session'):
            self.client._load_credentials_and_init_session()

    def get_client(self):
        return self.client if self.client else None
    
    async def shutdown(self):
        if self.client:
            # Tambahkan logika close session jika diperlukan oleh librespot-python
            pass

# Instance Global
spotify_manager = SpotifyManager()
