# [FILE: bot/helpers/amazon/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from .amazon_api import AmazonApi
from bot.helpers.database.mongo_async import database
from bot.settings import bot_set

class AmazonManager:
    def __init__(self):
        self.clients = []
        self._client_cycler = None
        self.user_clients = {}
        self.quality = "HD" 

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
                # [FIX] Menggunakan load_tokens agar customerId terekstrak otomatis
                client.load_tokens(auth_data.get('tokens', {}))
                self.clients.append(client)
            except Exception as e:
                LOGGER.error(f"Amazon: Gagal meload akun Global: {e}")

        if self.clients:
            self._client_cycler = itertools.cycle(self.clients)
            LOGGER.info(f"Amazon: {len(self.clients)} Klien Global aktif.")

    async def add_user_account(self, user_id: int, account_data: dict):
        """Memasukkan sesi private ke memori bot saat user baru login"""
        region = account_data.get('region', 'us')
        tokens = account_data.get('tokens', {})
        
        client = AmazonApi(region=region)
        # [FIX] Menggunakan load_tokens agar customerId terekstrak otomatis
        client.load_tokens(tokens)
        
        self.user_clients[user_id] = client
        LOGGER.info(f"Amazon: Private session ditambahkan untuk user {user_id}")

    async def remove_user_account(self, user_id: int):
        """Menghapus sesi private user"""
        if user_id in self.user_clients:
            await self.user_clients[user_id].close()
            del self.user_clients[user_id]
            
        await database.save_user_settings(user_id, {'amazon_account': None})
        LOGGER.info(f"Amazon: Private session dihapus untuk user {user_id}")

    def has_private_session(self, user_id):
        """Mengecek apakah user punya akun pribadi"""
        # Cek di memori sementara
        if user_id in self.user_clients:
            return True
            
        # Cek di memori permanen (jika bot habis direstart)
        user_data = bot_set.user_data.get(user_id, {})
        if user_data.get('amazon_account'):
            return True
            
        return False

    def get_client(self, user_id=None):
        """Mengambil client untuk unduhan. Prioritaskan akun pribadi user."""
        # 1. Cek Akun Pribadi
        if user_id:
            if user_id in self.user_clients:
                return self.user_clients[user_id]
            else:
                # Auto-Restore sesi dari database jika belum ada di memori
                user_data = bot_set.user_data.get(user_id, {})
                acc_data = user_data.get('amazon_account')
                if acc_data:
                    client = AmazonApi(region=acc_data.get('region', 'us'))
                    # [FIX] Menggunakan load_tokens agar customerId terekstrak otomatis
                    client.load_tokens(acc_data.get('tokens', {}))
                    self.user_clients[user_id] = client
                    return client
        
        # 2. Fallback ke Akun Global
        if not self.clients:
            return None
        return next(self._client_cycler)

    async def setup_quality(self, user_id, quality):
        await database.save_user_settings(user_id, {'amazon_qual': quality})

    async def shutdown(self):
        for client in self.clients:
            await client.close()
        for client in self.user_clients.values():
            await client.close()
        self.clients = []
        self.user_clients = {}

amazon_manager = AmazonManager()
