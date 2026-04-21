# [REVISI: bot/helpers/spotify/manager.py]

import os
import time
import json
import logging
import asyncio
import httpx
import base64
from urllib.parse import urlparse, parse_qs
from bot import Config
from bot.helpers.database.mongo_async import database
from .interface import ModuleInterface 

# --- Mock Object tetap sama seperti sebelumnya ---
class MockPrinter:
    def print(self, *args, **kwargs): pass

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
        # ... (Logika initialize_clients tetap sama seperti sebelumnya) ...
        # Pastikan tetap memulihkan file credentials.json dari MongoDB
        logging.info("Spotify: Memeriksa database untuk sesi lama...")
        saved_creds = await database.get_bot_setting("spotify_creds")
        conf_path = os.path.join(os.getcwd(), "config", "spotify")
        os.makedirs(conf_path, exist_ok=True)
        token_file = os.path.join(conf_path, "credentials.json")

        if saved_creds:
            with open(token_file, "w") as f:
                f.write(saved_creds)
            logging.info("Spotify: Sesi berhasil dipulihkan.")

        try:
            settings_dict = {'client_id': Config.SPOTIFY_CLIENT_ID, 'client_secret': Config.SPOTIFY_CLIENT_SECRET}
            self.session = await asyncio.to_thread(ModuleInterface, MockOrpheusConfig(settings_dict))
            logging.info("Spotify: Inisialisasi berhasil.")
        except Exception as e:
            logging.error(f"Spotify Init Error: {e}")

    async def complete_login(self, url):
        """Menukar URL redirect menjadi token secara manual (Lebih Akurat)"""
        try:
            # 1. Ekstrak 'code' dari URL
            query = urlparse(url).query
            params = parse_qs(query)
            code = params.get('code', [None])[0]
            
            if not code:
                logging.error("Spotify Auth: Tidak ditemukan kode di URL.")
                return False

            # 2. Siapkan data untuk ditukarkan ke Spotify API
            token_url = "https://accounts.spotify.com/api/token"
            redirect_uri = "http://127.0.0.1:4381/login"
            
            # Auth Header (Client ID : Client Secret dalam Base64)
            auth_str = f"{Config.SPOTIFY_CLIENT_ID}:{Config.SPOTIFY_CLIENT_SECRET}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {b64_auth}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri
            }

            # 3. Kirim permintaan Token ke Spotify
            async with httpx.AsyncClient() as client:
                response = await client.post(token_url, data=data, headers=headers)
                token_data = response.json()

            if "access_token" not in token_data:
                logging.error(f"Spotify API Error: {token_data}")
                return False

            # 4. Tambahkan timestamp expired (dibutuhkan OrpheusDL)
            token_data['expires_at'] = int(time.time()) + token_data.get('expires_in', 3600)

            # 5. Simpan ke File Lokal (Agar ModuleInterface bisa langsung pakai)
            conf_dir = os.path.join(os.getcwd(), "config", "spotify")
            os.makedirs(conf_dir, exist_ok=True)
            token_file = os.path.join(conf_dir, "credentials.json")
            
            content = json.dumps(token_data)
            with open(token_file, "w") as f:
                f.write(content)

            # 6. Simpan ke Database MongoDB (Agar permanen di Render)
            await database.set_bot_setting("spotify_creds", content)
            
            # 7. Re-inisialisasi agar session menggunakan token baru
            await self.initialize_clients()
            
            return True

        except Exception as e:
            logging.error(f"Spotify Login Error: {e}")
            return False

spotify_manager = SpotifyManager()
