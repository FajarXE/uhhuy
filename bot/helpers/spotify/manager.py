# [FILE: bot/helpers/spotify/manager.py]

import os, time, json, logging, asyncio, httpx, base64, hashlib, secrets
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
        self._pkce_verifier = None # Tempat simpan rahasia sementara

    async def initialize_clients(self):
        logging.info("Spotify: Memulai inisialisasi...")
        conf_path = os.path.join(os.getcwd(), "config", "spotify")
        os.makedirs(conf_path, exist_ok=True)

        saved_creds = await database.get_bot_setting("spotify_creds")
        saved_user = await database.get_bot_setting("spotify_username")
        saved_librespot = await database.get_bot_setting("spotify_librespot")

        if saved_creds:
            with open(os.path.join(conf_path, "credentials.json"), "w") as f:
                f.write(saved_creds)
        if saved_librespot:
            with open(os.path.join(conf_path, "librespot_credentials.json"), "w") as f:
                f.write(saved_librespot)

        settings = {"username": saved_user or "", "client_id": Config.SPOTIFY_CLIENT_ID, 
                    "client_secret": Config.SPOTIFY_CLIENT_SECRET, "device_name": "Orpheus-Bot"}
        
        with open(os.path.join(conf_path, "settings.json"), "w") as f:
            json.dump(settings, f)

        try:
            self.session = await asyncio.to_thread(ModuleInterface, MockOrpheusConfig(settings))
            logging.info(f"Spotify: Berhasil dimuat (User: {saved_user})")
        except Exception as e:
            logging.error(f"Spotify Startup Error: {e}")

    def get_streaming_link(self):
        """Membuat link login PKCE resmi Spotify Desktop"""
        self._pkce_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(hashlib.sha256(self._pkce_verifier.encode()).digest()).decode().replace('=', '')
        
        scope = "streaming%20user-read-playback-state%20user-modify-playback-state%20user-read-currently-playing%20user-library-read%20user-library-modify%20playlist-read-private"
        client_id = "6502050e435848529362d85418dc4491" # Official Spotify Desktop ID
        
        return (f"https://accounts.spotify.com/authorize?response_type=code&client_id={client_id}"
                f"&redirect_uri=http://127.0.0.1:4381/login&scope={scope}"
                f"&code_challenge={code_challenge}&code_challenge_method=S256")

    async def complete_login(self, url):
        query = urlparse(url).query
        params = parse_qs(query)
        code = params.get('code', [None])[0]
        if not code: return False

        async with httpx.AsyncClient() as client:
            # 1. TUKAR SEBAGAI STREAMING (PKCE)
            if self._pkce_verifier:
                resp = await client.post("https://accounts.spotify.com/api/token", data={
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": "http://127.0.0.1:4381/login",
                    "client_id": "6502050e435848529362d85418dc4491",
                    "code_verifier": self._pkce_verifier
                })
                if resp.status_code == 200:
                    await database.set_bot_setting("spotify_librespot", resp.text)
                    self._pkce_verifier = None
                    await self.initialize_clients()
                    return "STREAMING"

            # 2. TUKAR SEBAGAI METADATA (Normal OAuth)
            auth_b64 = base64.b64encode(f"{Config.SPOTIFY_CLIENT_ID}:{Config.SPOTIFY_CLIENT_SECRET}".encode()).decode()
            resp = await client.post("https://accounts.spotify.com/api/token", data={
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": "http://127.0.0.1:4381/login"
            }, headers={"Authorization": f"Basic {auth_b64}"})
            
            if resp.status_code == 200:
                token_data = resp.json()
                me = await client.get("https://api.spotify.com/v1/me", headers={"Authorization": f"Bearer {token_data['access_token']}"})
                username = me.json().get('id')
                token_data['expires_at'] = int(time.time()) + token_data['expires_in']
                await database.set_bot_setting("spotify_creds", json.dumps(token_data))
                await database.set_bot_setting("spotify_username", username)
                await self.initialize_clients()
                return "METADATA"
        return False

spotify_manager = SpotifyManager()
