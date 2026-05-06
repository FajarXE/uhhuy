# [FILE: bot/helpers/amazon/manager.py]

import asyncio
import itertools
import urllib.parse
import random
from bot.logger import LOGGER
from .amazon_api import AmazonApi
from bot.helpers.database.mongo_async import database
from bot.settings import bot_set

class AmazonManager:
    def __init__(self):
        self.clients = []
        self._client_cycler = None
        self.user_clients = {}  
        self.user_cyclers = {}  
        self.quality = "HD" 

    async def initialize_clients(self):
        LOGGER.info("Amazon: Menginisialisasi klien Global...")
        for old_client in self.clients:
            try: await old_client.close()
            except: pass
        self.clients = []
        
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
                client.load_tokens(auth_data.get('tokens', {}))
                self.clients.append(client)
            except Exception as e:
                LOGGER.error(f"Amazon: Gagal meload akun Global: {e}")

        if self.clients:
            self._client_cycler = itertools.cycle(self.clients)
            LOGGER.info(f"Amazon: {len(self.clients)} Klien Global aktif.")

    async def add_user_account(self, user_id: int, account_data: dict):
        region = account_data.get('region', 'us')
        tokens = account_data.get('tokens', {})
        
        client = AmazonApi(region=region)
        client.load_tokens(tokens)
        
        if user_id not in self.user_clients:
            self.user_clients[user_id] = []
            
        self.user_clients[user_id].append(client)
        self.user_cyclers[user_id] = itertools.cycle(self.user_clients[user_id])
        LOGGER.info(f"Amazon: Private session ditambahkan untuk user {user_id}")

    async def remove_specific_user_account(self, user_id: int, target_uid: str):
        if user_id in self.user_clients:
            new_clients = []
            for c in self.user_clients[user_id]:
                if c.tokens.get('customerId') == target_uid:
                    try: await c.close()
                    except: pass
                else:
                    new_clients.append(c)
            
            self.user_clients[user_id] = new_clients
            if new_clients:
                self.user_cyclers[user_id] = itertools.cycle(new_clients)
            else:
                del self.user_clients[user_id]
                if user_id in self.user_cyclers: del self.user_cyclers[user_id]
        LOGGER.info(f"Amazon: Akun {target_uid} dihapus untuk user {user_id}")

    async def remove_user_account(self, user_id: int):
        if user_id in self.user_clients:
            for c in self.user_clients[user_id]:
                try: await c.close()
                except: pass
            del self.user_clients[user_id]
            if user_id in self.user_cyclers: del self.user_cyclers[user_id]
            
        user_data = bot_set.user_data.get(user_id, {})
        if 'amazon_account' in user_data: user_data['amazon_account'] = None
        if 'amazon_accounts' in user_data: user_data['amazon_accounts'] = []
            
        await database.save_user_settings(user_id, {'amazon_accounts': [], 'amazon_account': None})
        LOGGER.info(f"Amazon: Semua private session dihapus untuk user {user_id}")

    def has_private_session(self, user_id):
        if user_id in self.user_clients and self.user_clients[user_id]:
            return True
        user_data = bot_set.user_data.get(user_id, {})
        if user_data.get('amazon_accounts') or user_data.get('amazon_account'):
            return True
        return False

    def get_client(self, user_id=None, url=None):
        """Mengambil client cerdas dengan Filter Region berdasarkan URL."""
        target_region = None
        if url:
            # Pisahkan domain dan jalurnya
            parsed_url = urllib.parse.urlparse(url)
            domain = parsed_url.netloc.lower()
            url_path = parsed_url.path.lower()
            
            if 'amazon.co.jp' in domain: target_region = 'jp'
            elif 'amazon.co.uk' in domain: target_region = 'uk'
            elif 'amazon.de' in domain: target_region = 'de'
            elif 'amazon.com.mx' in domain: target_region = 'mx'
            elif 'amazon.com.br' in domain: target_region = 'br'
            elif 'amazon.com.au' in domain: target_region = 'nz' # AU dan NZ berbagi server
            elif 'amazon.ca' in domain: target_region = 'ca'
            elif 'amazon.it' in domain: target_region = 'it'
            elif 'amazon.es' in domain: target_region = 'es'
            elif 'amazon.in' in domain: target_region = 'in'
            elif 'amazon.fr' in domain: target_region = 'fr'
            # Cek domain .ar ATAU jika ada unsur '-ar' (seperti /en-ar atau /es-ar) di jalurnya
            elif 'amazon.com.ar' in domain or '-ar' in url_path: target_region = 'ar'
            elif 'amazon.com' in domain: target_region = 'us'

        # 1. Cek Akun Pribadi
        if user_id:
            if user_id not in self.user_clients or not self.user_clients[user_id]:
                user_data = bot_set.user_data.get(user_id, {})
                acc_list = user_data.get('amazon_accounts', [])
                if not acc_list and user_data.get('amazon_account'):
                    acc_list = [user_data.get('amazon_account')]
                
                if acc_list:
                    clients = []
                    for acc_data in acc_list:
                        client = AmazonApi(region=acc_data.get('region', 'us'))
                        client.load_tokens(acc_data.get('tokens', {}))
                        clients.append(client)
                        
                    self.user_clients[user_id] = clients
                    self.user_cyclers[user_id] = itertools.cycle(clients)

            clients = self.user_clients.get(user_id, [])
            if clients:
                # --- SMART REGION MATCHING ---
                if target_region:
                    matching_clients = [c for c in clients if c.region.lower() == target_region or (target_region == 'nz' and c.region.lower() in ['au', 'nz'])]
                    if matching_clients:
                        return random.choice(matching_clients) # Load Balance hanya untuk akun di Region yang sama!
                
                # Fallback jika URL aneh / tidak terdeteksi
                return next(self.user_cyclers[user_id])
        
        # 2. Fallback ke Akun Global
        if not self.clients:
            return None
            
        if target_region:
            matching_global = [c for c in self.clients if c.region.lower() == target_region or (target_region == 'nz' and c.region.lower() in ['au', 'nz'])]
            if matching_global:
                return random.choice(matching_global)
                
        return next(self._client_cycler)

    async def setup_quality(self, user_id, quality):
        await database.save_user_settings(user_id, {'amazon_qual': quality})

    async def shutdown(self):
        for client in self.clients:
            try: await client.close()
            except: pass
        for clients_list in self.user_clients.values():
            for client in clients_list:
                try: await client.close()
                except: pass
        self.clients = []
        self.user_clients = {}
        self.user_cyclers = {}

amazon_manager = AmazonManager()
