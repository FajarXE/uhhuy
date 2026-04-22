# [FILE: bot/helpers/spotify/manager.py]

import os, time, json, logging, asyncio, httpx, base64, secrets
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
        self.conf_path = os.path.join(os.getcwd(), "bot", "config", "spotify")
        # Proxy Anda
        self.proxy = "socks5h://hdzire:hdzire@85.17.40.203:1080"

    async def initialize_clients(self):
        logging.info("Spotify: Inisialisasi Stealth Mode via Proxy...")
        os.makedirs(self.conf_path, exist_ok=True)

        # Hapus cache lama agar bersih dari error 403 sebelumnya
        cache_path = os.path.join(self.conf_path, ".librespot_cache")
        if os.path.exists(cache_path):
            import shutil
            shutil.rmtree(cache_path, ignore_errors=True)

        saved_creds = await database.get_bot_setting("spotify_creds")
        saved_user = await database.get_bot_setting("spotify_username")
        
        # ID Perangkat unik agar terlihat seperti HP baru
        device_id = secrets.token_hex(20)

        if saved_creds:
            with open(os.path.join(self.conf_path, "credentials.json"), "w") as f:
                f.write(saved_creds)
            with open(os.path.join(self.conf_path, "librespot_credentials.json"), "w") as f:
                f.write(saved_creds)

        settings_data = {
            "username": saved_user or "",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "device_name": "iPhone 15 Pro",
            "device_id": device_id,
            "proxy": self.proxy,
            "bitrate": 320,
            "is_premium": True
        }
        
        with open(os.path.join(self.conf_path, "settings.json"), "w") as f:
            json.dump(settings_data, f)

        try:
            # Set environment proxy untuk library pendukung
            os.environ['HTTP_PROXY'] = self.proxy
            os.environ['HTTPS_PROXY'] = self.proxy
            
            self.session = await asyncio.to_thread(ModuleInterface, MockOrpheusConfig(settings_data))
            logging.info(f"Spotify: Mesin siap (User: {saved_user})")
        except Exception as e:
            logging.error(f"Spotify Startup Error: {e}")

    async def complete_login(self, url):
        try:
            query = urlparse(url).query
            params = parse_qs(query)
            code = params.get('code', [None])[0]
            if not code: return False

            auth_str = f"{Config.SPOTIFY_CLIENT_ID}:{Config.SPOTIFY_CLIENT_SECRET}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            
            # MENGGUNAKAN URL RESMI SPOTIFY
            async with httpx.AsyncClient(proxy=self.proxy, follow_redirects=True) as client:
                # 1. Tukar Token
                resp = await client.post("https://accounts.spotify.com/api/token", data={
                    "grant_type": "authorization_code", 
                    "code": code,
                    "redirect_uri": "http://127.0.0.1:4381/login"
                }, headers={"Authorization": f"Basic {b64_auth}"})
                
                if resp.status_code != 200:
                    logging.error(f"Spotify Token Error: {resp.text}")
                    return False

                token_data = resp.json()
                
                # 2. Ambil Info User (Cek Wilayah)
                me = await client.get("https://api.spotify.com/v1/me", 
                                      headers={"Authorization": f"Bearer {token_data['access_token']}"})
                me_json = me.json()
                username = me_json.get('id')
                country = me_json.get('country', 'Unknown')
                
                logging.info(f"✅ Login Sukses! Region Akun: {country}")

            token_data['expires_at'] = int(time.time()) + token_data.get('expires_in', 3600)
            await database.set_bot_setting("spotify_creds", json.dumps(token_data))
            await database.set_bot_setting("spotify_username", username)
            
            await self.initialize_clients()
            return True
        except Exception as e:
            logging.error(f"Login Error: {e}")
            return False

spotify_manager = SpotifyManager()
