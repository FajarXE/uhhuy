# [FILE: bot/helpers/spotify/manager.py]

import os, time, json, logging, asyncio, httpx, base64
from urllib.parse import urlparse, parse_qs
from bot import Config
from bot.helpers.database.mongo_async import database
from .interface import ModuleInterface 

# --- REVISI MOCK OBJECT (FIX OPRINT) ---
class MockPrinter:
    def print(self, *args, **kwargs): pass
    def oprint(self, *args, **kwargs): pass # Menghindari error oprint

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
        
        # 1. Ambil semua data dari MongoDB
        saved_creds = await database.get_bot_setting("spotify_creds")
        saved_user = await database.get_bot_setting("spotify_username")
        saved_librespot = await database.get_bot_setting("spotify_librespot")
        
        conf_path = os.path.join(os.getcwd(), "config", "spotify")
        os.makedirs(conf_path, exist_ok=True)
        
        # 2. Suntikkan File Credentials Web API
        if saved_creds:
            with open(os.path.join(conf_path, "credentials.json"), "w") as f:
                f.write(saved_creds)

        # 3. Suntikkan File Credentials Librespot (Streaming)
        if saved_librespot:
            with open(os.path.join(conf_path, "librespot_credentials.json"), "w") as f:
                f.write(saved_librespot)
            logging.info("Spotify: Sesi Librespot dipulihkan.")

        # 4. PAKSA BUAT settings.json (Penting untuk Librespot)
        settings_data = {
            "username": saved_user or "",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "device_name": "OrpheusDL-Bot"
        }
        with open(os.path.join(conf_path, "settings.json"), "w") as f:
            json.dump(settings_data, f)

        try:
            mock_config = MockOrpheusConfig(settings_data)
            self.session = await asyncio.to_thread(ModuleInterface, mock_config)
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

            # 1. Tukar Code jadi Access Token (Web API)
            token_url = "https://accounts.spotify.com/api/token"
            auth_str = f"{Config.SPOTIFY_CLIENT_ID}:{Config.SPOTIFY_CLIENT_SECRET}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(token_url, data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "http://127.0.0.1:4381/login"
                }, headers={"Authorization": f"Basic {b64_auth}"})
                token_data = resp.json()

                if "access_token" not in token_data: return False

                # 2. Ambil Username
                me_resp = await client.get("https://api.spotify.com/v1/me", 
                                           headers={"Authorization": f"Bearer {token_data['access_token']}"})
                username = me_resp.json().get('id')

            # 3. Simpan Web Token & Username ke MongoDB
            token_data['expires_at'] = int(time.time()) + token_data.get('expires_in', 3600)
            content = json.dumps(token_data)
            await database.set_bot_setting("spotify_creds", content)
            await database.set_bot_setting("spotify_username", username)
            
            # 4. AUTO-GENERATE Librespot Creds (Jika memungkinkan dari token)
            # Beberapa versi Orpheus bisa mengonversi ini, kita siapkan foldernya
            await self.initialize_clients()
            return True
        except Exception as e:
            logging.error(f"Spotify Login Error: {e}")
            return False

    async def save_librespot_session(self):
        """Panggil ini setelah download sukses pertama kali untuk backup session"""
        try:
            lib_file = os.path.join(os.getcwd(), "config", "spotify", "librespot_credentials.json")
            if os.path.exists(lib_file):
                with open(lib_file, "r") as f:
                    content = f.read()
                await database.set_bot_setting("spotify_librespot", content)
                logging.info("Spotify: Librespot session di-backup ke MongoDB.")
        except: pass

spotify_manager = SpotifyManager()
