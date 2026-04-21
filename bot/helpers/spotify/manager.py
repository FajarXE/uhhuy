# [FILE: bot/helpers/spotify/manager.py]

import os, time, json, logging, asyncio, httpx, base64
from urllib.parse import urlparse, parse_qs
from bot import Config
from bot.helpers.database.mongo_async import database
from .interface import ModuleInterface 

# --- REVISI MOCK OBJECT (MENAMBAHKAN OPRINT) ---
class MockPrinter:
    def print(self, *args, **kwargs): pass
    def oprint(self, *args, **kwargs): pass # FIX: Tambahkan oprint agar tidak error

class MockOrpheusConfig:
    def __init__(self, settings_dict):
        self.module_settings = settings_dict
        self.module_error = None
        self.global_settings = {}
        self.printer_controller = MockPrinter()
# ----------------------------------------------

class SpotifyManager:
    def __init__(self):
        self.session = None

    async def initialize_clients(self):
        logging.info("Spotify: Memeriksa database untuk sesi lama...")
        
        # Ambil token & username dari MongoDB
        saved_creds = await database.get_bot_setting("spotify_creds")
        saved_user = await database.get_bot_setting("spotify_username")
        
        conf_path = os.path.join(os.getcwd(), "config", "spotify")
        os.makedirs(conf_path, exist_ok=True)
        
        if saved_creds:
            with open(os.path.join(conf_path, "credentials.json"), "w") as f:
                f.write(saved_creds)
            logging.info("Spotify: Sesi berhasil dipulihkan.")

        try:
            # Masukkan username ke settings jika ada
            settings_dict = {
                'client_id': Config.SPOTIFY_CLIENT_ID, 
                'client_secret': Config.SPOTIFY_CLIENT_SECRET,
                'username': saved_user or "" # FIX: Librespot butuh username
            }
            
            self.session = await asyncio.to_thread(ModuleInterface, MockOrpheusConfig(settings_dict))
            logging.info(f"Spotify: Inisialisasi berhasil (User: {saved_user}).")
        except Exception as e:
            logging.error(f"Spotify Init Error: {e}")

    async def complete_login(self, url):
        """Menukar URL redirect menjadi token & ambil Username otomatis"""
        try:
            query = urlparse(url).query
            params = parse_qs(query)
            code = params.get('code', [None])[0]
            if not code: return False

            # 1. Tukar Code jadi Access Token
            token_url = "https://accounts.spotify.com/api/token"
            auth_str = f"{Config.SPOTIFY_CLIENT_ID}:{Config.SPOTIFY_CLIENT_SECRET}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            
            async with httpx.AsyncClient() as client:
                # Ambil Token
                resp = await client.post(token_url, data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "http://127.0.0.1:4381/login"
                }, headers={"Authorization": f"Basic {b64_auth}"})
                token_data = resp.json()

                if "access_token" not in token_data: return False

                # 2. AMBIL USERNAME OTOMATIS DARI SPOTIFY API
                me_resp = await client.get("https://api.spotify.com/v1/me", 
                                           headers={"Authorization": f"Bearer {token_data['access_token']}"})
                me_data = me_resp.json()
                username = me_data.get('id') # Ini adalah username asli Spotify Anda

            # 3. Simpan data
            token_data['expires_at'] = int(time.time()) + token_data.get('expires_in', 3600)
            content = json.dumps(token_data)
            
            await database.set_bot_setting("spotify_creds", content)
            await database.set_bot_setting("spotify_username", username)
            
            # Re-init dengan data baru
            await self.initialize_clients()
            return True
        except Exception as e:
            logging.error(f"Spotify Login Error: {e}")
            return False

spotify_manager = SpotifyManager()
