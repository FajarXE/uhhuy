# [FILE: bot/helpers/spotify/manager.py]

import os, time, json, logging, asyncio, httpx, base64
from urllib.parse import urlparse, parse_qs
from bot import Config
from bot.helpers.database.mongo_async import database
from .interface import ModuleInterface 

class MockPrinter:
    def print(self, *args, **kwargs): pass
    def oprint(self, *args, **kwargs): pass

class MockOrpheusConfig:
    def __init__(self, settings_dict):
        self.module_settings = settings_dict
        self.module_error = None
        self.global_settings = {}
        self.printer_controller = MockPrinter()

class SpotifyManager:
    def __init__(self):
        self.session = None
        # Path disesuaikan dengan folder aplikasi Anda
        self.conf_path = os.path.join(os.getcwd(), "bot", "config", "spotify")

    async def initialize_clients(self):
        logging.info(f"Spotify: Sinkronisasi folder konfigurasi ke {self.conf_path}")
        os.makedirs(self.conf_path, exist_ok=True)

        saved_creds = await database.get_bot_setting("spotify_creds")
        saved_user = await database.get_bot_setting("spotify_username")

        if saved_creds:
            # Menyediakan file credentials untuk metadata dan streaming
            with open(os.path.join(self.conf_path, "credentials.json"), "w") as f:
                f.write(saved_creds)
            with open(os.path.join(self.conf_path, "librespot_credentials.json"), "w") as f:
                f.write(saved_creds)

        settings_data = {
            "username": saved_user or "",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "device_name": "Orpheus-Render"
        }
        
        with open(os.path.join(self.conf_path, "settings.json"), "w") as f:
            json.dump(settings_data, f)

        try:
            self.session = await asyncio.to_thread(ModuleInterface, MockOrpheusConfig(settings_data))
            logging.info(f"Spotify: Mesin berhasil dimuat (User: {saved_user})")
        except Exception as e:
            logging.error(f"Spotify Startup Error: {e}")

    async def complete_login(self, url):
        try:
            query = urlparse(url).query
            params = parse_qs(query)
            code = params.get('code', [None])[0]
            if not code:
                return False

            auth_str = f"{Config.SPOTIFY_CLIENT_ID}:{Config.SPOTIFY_CLIENT_SECRET}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            
            async with httpx.AsyncClient() as client:
                resp = await client.post("https://accounts.spotify.com/api/token", data={
                    "grant_type": "authorization_code", 
                    "code": code,
                    "redirect_uri": "http://127.0.0.1:4381/login"
                }, headers={"Authorization": f"Basic {b64_auth}"})
                
                token_data = resp.json()
                if "access_token" not in token_data:
                    return False

                me = await client.get("https://api.spotify.com/v1/me", 
                                      headers={"Authorization": f"Bearer {token_data['access_token']}"})
                username = me.json().get('id')

            token_data['expires_at'] = int(time.time()) + token_data.get('expires_in', 3600)
            
            # Simpan hasil login ke database MongoDB
            await database.set_bot_setting("spotify_creds", json.dumps(token_data))
            await database.set_bot_setting("spotify_username", username)
            
            # Jalankan ulang inisialisasi agar file session terupdate
            await self.initialize_clients()
            return True
        except Exception as e:
            logging.error(f"Login Error: {e}")
            return False

spotify_manager = SpotifyManager()
