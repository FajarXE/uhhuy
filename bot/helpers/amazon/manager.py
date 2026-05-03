# [BUAT FILE BARU: bot/helpers/amazon/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from .amazon_api import AmazonApi
from bot.helpers.database.mongo_async import database

class AmazonManager:
    def __init__(self):
        self.clients = []
        self._client_cycler = None
        self.user_clients = {}
        self.quality = "HD" # HD (Lossless/FLAC) atau UHD (Hi-Res)

    async def initialize_clients(self):
        LOGGER.info("Amazon: Menginisialisasi klien Global...")
        try:
            all_settings = await database.get_variable()
            self.quality = all_settings.get('AMAZON_QUALITY', 'HD')
            accounts_list = all_settings.get("AMAZON_ACCOUNTS_LIST", [])
        except Exception:
            accounts_list = []

        if not accounts_list:
            LOGGER.warning("Amazon: Tidak ada akun Global.")
            return

        for auth_data in accounts_list:
            client = AmazonApi(region=auth_data.get('region', 'jp'))
            try:
                await client.login_from_saved(auth_data)
                self.clients.append(client)
            except Exception as e:
                LOGGER.error(f"Amazon: Gagal login akun Global: {e}")

        if self.clients:
            self._client_cycler = itertools.cycle(self.clients)
            LOGGER.info(f"Amazon: {len(self.clients)} Klien Global aktif.")

    def get_client(self, region=None):
        if not self.clients:
            return None
        # Sederhananya menggunakan cycler, atau filter by region jika diperlukan
        return next(self._client_cycler)

    def has_private_session(self, user_id):
        return user_id in self.user_clients

    async def setup_quality(self, user_id, quality):
        # Menyimpan pengaturan kualitas user ke DB
        await database.save_user_settings(user_id, {'amazon_qual': quality})

    async def shutdown(self):
        for client in self.clients:
            await client.close()
        self.clients = []

amazon_manager = AmazonManager()
