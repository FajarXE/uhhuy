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
        logging.info("Spotify: Memulihkan sesi...")
        conf_path = os.path.join(os.getcwd(), "config", "spotify")
        os.makedirs(conf_path, exist_ok=True)

        # Ambil semua data dari MongoDB
        saved_creds = await database.get_bot_setting("spotify_creds")
        saved_user = await database.get_bot_setting("spotify_username")
        saved_librespot = await database.get_bot_setting("spotify_librespot")

        if saved_creds:
            with open(os.path.join(conf_path, "credentials.json"), "w") as f:
                f.write(saved_creds)
        
        if saved_librespot:
            with open(os.path.join(conf_path, "librespot_credentials.json"), "w") as f:
                f.write(saved_librespot)

        settings_data = {
            "username": saved_user or "",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "device_name": "Orpheus-Mobile-Bot"
        }
        
        with open(os.path.join(conf_path, "settings.json"), "w") as f:
            json.dump(settings_data, f)

        try:
            self.session = await asyncio.to_thread(ModuleInterface, MockOrpheusConfig(settings_data))
            logging.info(f"Spotify: Siap digunakan (User: {saved_user})")
        except Exception as e:
            logging.error(f"Spotify Startup Error: {e}")

    async def complete_login(self, url):
        """Handler Pintar untuk menukar token di HP"""
        try:
            query = urlparse(url).query
            params = parse_qs(query)
            code = params.get('code', [None])[0]
            if not code: return False

            async with httpx.AsyncClient() as client:
                # 1. COBA TUKAR SEBAGAI LIBRESPOT (STREAMING)
                # Menggunakan Client ID resmi Spotify Desktop
                resp_lib = await client.post("https://accounts.spotify.com/api/token", data={
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": "http://127.0.0.1:4381/login",
                    "client_id": "6502050e435848529362d85418dc4491" # Official ID
                })
                
                if resp_lib.status_code == 200:
                    content = resp_lib.text
                    await database.set_bot_setting("spotify_librespot", content)
                    await self.initialize_clients()
                    return "STREAMING"

                # 2. JIKA GAGAL, TUKAR SEBAGAI WEB API (METADATA)
                auth_str = f"{Config.SPOTIFY_CLIENT_ID}:{Config.SPOTIFY_CLIENT_SECRET}"
                b64_auth = base64.b64encode(auth_str.encode()).decode()
                resp_web = await client.post("https://accounts.spotify.com/api/token", data={
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": "http://127.0.0.1:4381/login"
                }, headers={"Authorization": f"Basic {b64_auth}"})
                
                if resp_web.status_code == 200:
                    token_data = resp_web.json()
                    me_resp = await client.get("https://api.spotify.com/v1/me", 
                                               headers={"Authorization": f"Bearer {token_data['access_token']}"})
                    username = me_resp.json().get('id')
                    
                    token_data['expires_at'] = int(time.time()) + token_data.get('expires_in', 3600)
                    content = json.dumps(token_data)
                    await database.set_bot_setting("spotify_creds", content)
                    await database.set_bot_setting("spotify_username", username)
                    await self.initialize_clients()
                    return "METADATA"

            return False
        except Exception as e:
            logging.error(f"Login Error: {e}")
            return False

spotify_manager = SpotifyManager()
