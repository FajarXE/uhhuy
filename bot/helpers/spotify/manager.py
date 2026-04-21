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

    async def initialize_clients(self):
        logging.info("Spotify: Inisialisasi sistem...")
        conf_path = os.path.join(os.getcwd(), "config", "spotify")
        os.makedirs(conf_path, exist_ok=True)

        # Ambil data dari MongoDB
        saved_creds = await database.get_bot_setting("spotify_creds")
        saved_user = await database.get_bot_setting("spotify_username")

        if saved_creds:
            # Tulis ke file Metadata
            with open(os.path.join(conf_path, "credentials.json"), "w") as f:
                f.write(saved_creds)
            # Tulis ke file Streaming (Librespot) - Menggunakan data yang sama
            with open(os.path.join(conf_path, "librespot_credentials.json"), "w") as f:
                f.write(saved_creds)
            logging.info("Spotify: Sesi berhasil dimuat ke sistem file.")

        settings_data = {
            "username": saved_user or "",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "device_name": "Orpheus-Render-Bot"
        }
        with open(os.path.join(conf_path, "settings.json"), "w") as f:
            json.dump(settings_data, f)

        try:
            self.session = await asyncio.to_thread(ModuleInterface, MockOrpheusConfig(settings_data))
            logging.info(f"Spotify: Berhasil aktif (User: {saved_user})")
        except Exception as e:
            logging.error(f"Spotify Startup Error: {e}")

    async def complete_login(self, url):
        try:
            query = urlparse(url).query
            params = parse_qs(query)
            code = params.get('code', [None])[0]
            if not code: return False

            # Tukar kode menggunakan Client ID & Secret Anda
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
                    logging.error(f"Spotify Token Error: {token_data}")
                    return False

                # Ambil Username
                me = await client.get("https://api.spotify.com/v1/me", 
                                      headers={"Authorization": f"Bearer {token_data['access_token']}"})
                username = me.json().get('id')

            token_data['expires_at'] = int(time.time()) + token_data.get('expires_in', 3600)
            content = json.dumps(token_data)
            
            # Simpan ke Database
            await database.set_bot_setting("spotify_creds", content)
            await database.set_bot_setting("spotify_username", username)
            
            # Restart mesin dengan token baru
            await self.initialize_clients()
            return True
        except Exception as e:
            logging.error(f"Complete Login Error: {e}")
            return False

spotify_manager = SpotifyManager()
