# [GANTI SELURUH FILE: bot/helpers/beatport/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

# Database Import
try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Beatport Manager: Gagal mengimpor 'database'.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()

# [PERBAIKAN] Langsung import tanpa try-except. 
# Agar jika api.py error, kita langsung tahu (Fail Fast).
from .api import BeatportAPI, BeatportError

class BeatportLoginManager:
    def __init__(self, env_account_configs: list):
        self.env_account_configs = env_account_configs
        
        # GLOBAL CLIENTS (Dari .env)
        self.global_clients = [] 
        self._global_cycler = None
        
        # PRIVATE CLIENTS (Dari DB)
        self.user_clients = {} 
        
        self.quality = "lossless" 
        self.user_data = {} 

    @property
    def clients(self):
        """Properti kompatibilitas untuk menggabungkan semua klien."""
        return self.global_clients + list(self.user_clients.values())

    async def initialize_clients(self):
        """Memuat akun Global (.env) dan Akun User (DB)."""
        saved_tokens = {}
        user_sessions = {}
        
        try:
            all_settings = await database.get_variable() or {}
            
            # Load Global Quality
            db_quality = all_settings.get('BEATPORT_QUALITY')
            if db_quality in ["lossless", "high", "medium"]:
                self.quality = db_quality
            
            # Load Tokens Cache
            saved_tokens = all_settings.get('BEATPORT_TOKENS', {})
            
            # Load User Sessions
            raw_sessions = all_settings.get('BEATPORT_USER_SESSIONS', {})
            # [SAFETY] Pastikan konversi key ke int aman
            user_sessions = {}
            for k, v in raw_sessions.items():
                try: user_sessions[int(k)] = v
                except: pass
            
        except Exception as e:
            LOGGER.error(f"Beatport Manager: Gagal load DB settings: {e}")

        # 1. INIT GLOBAL CLIENTS (.env)
        self.global_clients = []
        tasks_env = []
        
        if self.env_account_configs:
            LOGGER.info(f"Beatport Manager: Loading {len(self.env_account_configs)} global accounts...")
            for account in self.env_account_configs:
                token_data = saved_tokens.get(account['email'])
                tasks_env.append(self._login_task(account, token_data))
            
            results_env = await asyncio.gather(*tasks_env)
            self.global_clients = [c for c in results_env if c]
            
            if self.global_clients:
                self._global_cycler = itertools.cycle(self.global_clients)

        # 2. INIT PRIVATE USER CLIENTS (DB)
        self.user_clients = {}
        tasks_user = []
        user_ids = []
        
        if user_sessions:
            LOGGER.info(f"Beatport Manager: Loading {len(user_sessions)} private user accounts...")
            for uid, account in user_sessions.items():
                token_data = saved_tokens.get(account['email'])
                tasks_user.append(self._login_task(account, token_data))
                user_ids.append(uid)
            
            results_user = await asyncio.gather(*tasks_user)
            
            for uid, client in zip(user_ids, results_user):
                if client:
                    self.user_clients[uid] = client
                    client.owner_id = uid 

        LOGGER.info(f"Beatport Manager Ready. Global: {len(self.global_clients)}, Private: {len(self.user_clients)}")
        await self.save_all_tokens()

    async def _login_task(self, account: dict, saved_token: dict = None):
        client = BeatportAPI()
        email, password = account['email'], account['password']
        
        # Proxy Setup
        proxy = account.get('proxy')
        if proxy: client.proxy = proxy

        # 1. Coba Pakai Token (Refresh)
        if saved_token and saved_token.get('refresh_token'):
            try:
                saved_token['email'] = email
                await client.load_session(saved_token)
                await client.refresh()
                return client
            except Exception:
                # Jika refresh gagal (token expired/revoked), lanjut ke login password
                pass
        
        # 2. Coba Login Password
        try:
            await client.login(email=email, password=password)
            return client
        except Exception as e:
            LOGGER.error(f"Beatport Login Failed {email}: {e}")
            await client.close_session()
            return None

    # --- USER MANAGEMENT ---

    async def add_user_account(self, user_id: int, email, password):
        """Login akun pribadi untuk User ID tertentu."""
        # 1. Cek Login
        temp_client = BeatportAPI()
        await temp_client.login(email, password)
        temp_client.owner_id = user_id
        
        # 2. Simpan ke Memory
        if user_id in self.user_clients:
            await self.user_clients[user_id].close_session()
        self.user_clients[user_id] = temp_client
        
        # 3. Simpan ke DB
        all_settings = await database.get_variable() or {}
        user_sessions = all_settings.get('BEATPORT_USER_SESSIONS', {})
        user_sessions[str(user_id)] = {"email": email, "password": password}
        
        await database.set_variable('BEATPORT_USER_SESSIONS', user_sessions)
        await self.save_all_tokens() 
        return True

    async def remove_user_account(self, user_id: int):
        """Hapus sesi pribadi user."""
        if user_id in self.user_clients:
            await self.user_clients[user_id].close_session()
            del self.user_clients[user_id]
        
        all_settings = await database.get_variable() or {}
        user_sessions = all_settings.get('BEATPORT_USER_SESSIONS', {})
        
        if str(user_id) in user_sessions:
            del user_sessions[str(user_id)]
            await database.set_variable('BEATPORT_USER_SESSIONS', user_sessions)
            return True
        return False

    def get_client(self, user_id: int = None) -> BeatportAPI | None:
        """
        Prioritas: Private Client -> Global Client
        """
        if user_id and user_id in self.user_clients:
            return self.user_clients[user_id]
            
        if self._global_cycler:
            try: return next(self._global_cycler)
            except: pass
            
        return None
    
    def has_private_session(self, user_id: int) -> bool:
        return user_id in self.user_clients

    async def save_all_tokens(self):
        tokens_map = {}
        all_active = list(self.global_clients) + list(self.user_clients.values())
        
        for client in all_active:
            if hasattr(client, 'email') and client.email and client.refresh_token:
                tokens_map[client.email] = {
                    'access_token': client.access_token,
                    'refresh_token': client.refresh_token,
                    'email': client.email
                }
        try:
            await database.set_variable('BEATPORT_TOKENS', tokens_map)
        except Exception: pass

    # --- Quality Helpers ---
    async def setup_quality(self, user_id: int, qual: str = None):
        if user_id not in self.user_data: self.user_data[user_id] = {}
        if qual in ["lossless", "high", "medium"]:
            self.user_data[user_id]['beatport_qual'] = qual

    def get_user_quality(self, user_id: int) -> str:
        return self.user_data.get(user_id, {}).get('beatport_qual', self.quality)

    async def shutdown(self):
        """Menutup semua sesi klien Beatport (Global & User) dengan aman saat bot dimatikan."""
        from bot.logger import LOGGER
        LOGGER.info(f"Beatport Manager: Shutdown... Menutup {len(self.global_clients)} Global Clients.")
        tasks = []
        
        # Kumpulkan tugas penutupan sesi Global
        for client in self.global_clients:
            if client: 
                tasks.append(client.close_session())
            
        # Kumpulkan tugas penutupan sesi Private User
        for client in self.user_clients.values():
            if client: 
                tasks.append(client.close_session())
            
        # Eksekusi secara paralel
        if tasks:
            try:
                import asyncio
                await asyncio.gather(*tasks)
            except Exception as e:
                LOGGER.error(f"Beatport Manager: Error saat shutdown: {e}")
                
        self.global_clients = []
        self.user_clients = {}
        self._global_cycler = None
        LOGGER.info("Beatport Manager: Semua sesi berhasil ditutup.")

beatport_manager = BeatportLoginManager(Config.BEATPORT_ACCOUNTS)
