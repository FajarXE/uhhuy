# [GANTI FILE: bot/helpers/kkbox/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

# --- MODIFIKASI: Hapus impor 'bot_set' untuk memutus impor melingkar ---
# from ..settings import bot_set 
# --- BATAS MODIFIKASI ---

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("KKBox Manager: Gagal mengimpor 'database'. Fungsi pemuatan kualitas mungkin gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()

try:
    from .api import KkboxAPI
except ImportError:
    LOGGER.critical("KKBox: Gagal mengimpor 'KkboxAPI' dari 'bot/helpers/kkbox/api.py'. File inti tidak ada.")
    class KkboxAPI:
        def __init__(self, *args, **kwargs): 
            pass
        def login(self, *args, **kwargs): 
            raise NotImplementedError("File 'KkboxAPI' inti tidak ditemukan atau tidak bisa diimpor.")
        def close_session(self): 
            pass

# Pengecualian kustom sederhana untuk diteruskan
class KKBoxError(Exception):
    pass

class KKBoxLoginManager:
    """
    Mengelola kumpulan instans klien KkboxAPI yang sudah login.
    Juga mengelola pengaturan kualitas default dan per-pengguna.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        self.user_clients = {}
        
        if not Config.KKBOX_KC1_KEY or not Config.KKBOX_SECRET_KEY:
            LOGGER.error("KKBox Manager: Kunci KC1 atau Secret tidak diatur di Config!")
            self.kc1_key = ""
            self.secret_key = ""
        else:
            self.kc1_key = Config.KKBOX_KC1_KEY
            self.secret_key = Config.KKBOX_SECRET_KEY
        
        self.quality = "hifi" 
        # --- MODIFIKASI: Kita masih butuh cache lokal ini ---
        # Cache ini akan diisi oleh bot_set di file user_settings.py
        self.user_data = {} 
        # --- BATAS MODIFIKASI ---

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun KKBox dari Config
        dan memuat pengaturan kualitas default.
        """
        
        # --- MODIFIKASI: Hanya muat pengaturan default. ---
        try:
            all_settings = await database.get_variable() 
            if not all_settings: all_settings = {}
            db_quality = all_settings.get('KKBOX_QUALITY') 
            if db_quality in ["128k", "192k", "320k", "hifi", "hires"]:
                self.quality = db_quality
                LOGGER.info(f"KKBox Manager: Kualitas default dimuat dari DB: {self.quality}")
            else:
                LOGGER.info(f"KKBox Manager: Kualitas default DB tidak ada/valid, menggunakan: {self.quality}")

            # Pengaturan pengguna akan dimuat oleh 'bot_set' dan disinkronkan oleh 'user_settings.py'
            LOGGER.info(f"KKBox Manager: Pengaturan kualitas pengguna akan dimuat nanti.")

        except Exception as e:
            LOGGER.error(f"KKBox Manager: Gagal memuat kualitas default dari DB: {e}. Menggunakan default: {self.quality}")
        # --- BATAS MODIFIKASI ---

        if not self.account_configs:
            LOGGER.warning("KKBox Manager: Tidak ada akun untuk diinisialisasi.")
            return

        LOGGER.info(f"KKBox Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("KKBox Manager: Gagal login ke SEMUA akun KKBox.")
            return

        LOGGER.info(f"KKBox Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def add_user_account(self, user_id: int, auth_data: dict):
        """Menyimpan sesi KKBox privat milik pengguna."""
        email = auth_data.get('email')
        password = auth_data.get('password')
        proxy = auth_data.get('proxy')

        client = KkboxAPI(
            exception=KKBoxError,
            kc1_key=self.kc1_key,
            secret_key=self.secret_key
        )
        
        if proxy:
            client.s.proxies.update({'http': proxy, 'https': proxy})

        try:
            await asyncio.to_thread(client.login, email, password)
            
            if user_id not in self.user_clients:
                self.user_clients[user_id] = {'clients': [], 'cycler': None}
                
            self.user_clients[user_id]['clients'].append(client)
            self.user_clients[user_id]['cycler'] = itertools.cycle(self.user_clients[user_id]['clients'])
            
            return True, "Login Berhasil"
        except Exception as e:
            return False, str(e)

    async def remove_specific_user_account(self, user_id: int, target_email: str):
        """Menghapus akun spesifik dari pool Private Session."""
        if user_id in self.user_clients:
            pool = self.user_clients[user_id]
            client_to_close = next((c for c in pool['clients'] if getattr(c, 'email', '') == target_email), None)
            
            if client_to_close:
                try: await asyncio.to_thread(client_to_close.close_session)
                except: pass
                
                pool['clients'].remove(client_to_close)
                
                if pool['clients']:
                    pool['cycler'] = itertools.cycle(pool['clients'])
                else:
                    del self.user_clients[user_id]
            return True
        return False

    def has_private_session(self, user_id: int) -> bool:
        return user_id in self.user_clients and len(self.user_clients[user_id]['clients']) > 0

    def get_user_client(self, user_id: int) -> KkboxAPI | None:
        """Mendapatkan klien KHUSUS milik user dengan Load Balancing."""
        pool = self.user_clients.get(user_id)
        if pool and pool['clients']:
            return next(pool['cycler'])
        return None

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun (menggunakan asyncio.to_thread)."""
        
        client = KkboxAPI(
            exception=KKBoxError,
            kc1_key=self.kc1_key, 
            secret_key=self.secret_key
        )
        
        proxy_url = account.get("proxy") 
        if proxy_url:
            try:
                proxies = {
                    'http': proxy_url,
                    'https': proxy_url
                }
                client.s.proxies.update(proxies) 
                LOGGER.info(f"KKBox Akun #{account['id']}: Berhasil menerapkan proxy spesifik.")
            except Exception as e:
                LOGGER.error(f"KKBox Akun #{account['id']}: Gagal mengatur proxy: {e}")
        
        try:
            await asyncio.to_thread(
                client.login,
                email=account['email'], 
                password=account['password']
            )
            LOGGER.info(f"KKBox Manager: Berhasil login ke Akun #{account['id']}")
            return client
        except Exception as e:
            LOGGER.error(f"KKBox Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            return None

    def get_client(self) -> KkboxAPI | None:
        if not self._client_cycler:
            LOGGER.error("KKBox Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("KKBox Manager: Kumpulan klien kosong.")
            return None
    
    # --- MODIFIKASI: setup_quality HANYA menyimpan ke RAM LOKAL ---
    # File user_settings.py akan bertanggung jawab memanggil ini DAN menyimpan ke DB
    async def setup_quality(self, user_id: int, qual: str = None):
        if qual in ["128k", "192k", "320k", "hifi", "hires"]:
            self.user_data.setdefault(user_id, {})['kkbox_qual'] = qual
            LOGGER.debug(f"KKBox Manager: Memperbarui cache RAM lokal untuk user {user_id} ke {qual}")
            
    # --- BATAS MODIFIKASI ---

    def get_user_quality(self, user_id: int) -> str:
        # --- MODIFIKASI: Baca dari cache RAM LOKAL ---
        # (user_settings.py akan bertanggung jawab mengisi cache ini)
        user_qual = self.user_data.get(user_id, {}).get('kkbox_qual') 
        # --- BATAS MODIFIKASI ---
        
        if user_qual in ["128k", "192k", "320k", "hifi", "hires"]:
            return user_qual
        return self.quality 

    # --- TAMBAHAN BARU: Metode Shutdown ---
    async def shutdown(self):
        """Menutup semua sesi klien KkboxAPI (requests) yang dikelola."""
        LOGGER.info(f"KKBox Manager: Memulai shutdown... Menutup {len(self.clients)} sesi klien 'requests'.")
        tasks = []
        for client in self.clients:
            if hasattr(client, 'close_session'):
                # Panggil 'close_session' (sinkron) di thread terpisah
                tasks.append(asyncio.to_thread(client.close_session))
        
        # Jalankan semua tugas penutupan secara bersamaan
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            LOGGER.error(f"KKBox Manager: Terjadi error saat shutdown: {e}")
            
        self.clients = []
        self._client_cycler = None
        LOGGER.info("KKBox Manager: Semua sesi klien 'requests' telah ditutup.")
    # --- AKHIR TAMBAHAN ---

kkbox_manager = KKBoxLoginManager(Config.KKBOX_ACCOUNTS)
