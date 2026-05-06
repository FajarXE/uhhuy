# [GANTI FILE: bot/helpers/bugs/manager.py]

import asyncio
import itertools
import random
import string
import logging
from bot.logger import LOGGER
from config import Config

# Coba impor database
try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Bugs Manager: Gagal mengimpor 'database'. Fungsi pemuatan akan gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()

# Impor BugsApi dari file yang Anda sediakan
try:
    from .bugs_api import BugsApi
except ImportError:
    LOGGER.critical("Bugs: Gagal mengimpor 'BugsApi' dari 'bot/helpers/bugs/bugs_api.py'.")
    class BugsApi:
        def __init__(self, *args, **kwargs): pass
        def auth(self, *args, **kwargs): 
            raise NotImplementedError("File 'BugsApi' inti tidak ditemukan.")
        def get_account(self, *args, **kwargs): 
            raise NotImplementedError("File 'BugsApi' inti tidak ditemukan.")
        def set_session(self, *args, **kwargs): pass
        # --- Tambahkan stub close_session ---
        def close_session(self): pass
        # --- Akhir Tambahan ---


# Pengecualian kustom
class BugsError(Exception):
    pass

class BugsLoginManager:
    """
    Mengelola kumpulan instans klien BugsApi yang sudah login.
    Juga mengelola device_id dan pengaturan kualitas.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        self.device_id = None # Akan dimuat dari DB atau dibuat baru
        
        # Kualitas dari 'interface.py': ['flac', 'aac256', '320k', 'aac']
        self.quality = "flac" # Kualitas default bot
        # --- PERBAIKAN: Hapus 'flac24' ---
        self.valid_qualities = ["flac", "aac256", "320k", "aac"]
        # --- BATAS PERBAIKAN ---
        
        # Cache RAM untuk pengaturan kualitas per-pengguna
        self.user_data = {} 

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Bugs dari Config
        dan memuat pengaturan kualitas default.
        """
        
        all_settings = {}
        try:
            all_settings = await database.get_variable() 
            if not all_settings: all_settings = {}
            
            # 1. Muat atau Buat Device ID (Kritis untuk Bugs)
            self.device_id = all_settings.get('BUGS_DEVICE_ID')
            if not self.device_id:
                LOGGER.info("Bugs Manager: BUGS_DEVICE_ID tidak ditemukan, membuat yang baru...")
                # Logika dari interface.py untuk membuat device_id
                self.device_id = ''.join(random.choices(string.ascii_uppercase + string.ascii_lowercase + string.digits + '_', k=28))
                await database.set_variable('BUGS_DEVICE_ID', self.device_id)
            else:
                LOGGER.info("Bugs Manager: Berhasil memuat BUGS_DEVICE_ID dari database.")

            # 2. Muat Kualitas Default Bot
            db_quality = all_settings.get('BUGS_QUALITY') 
            if db_quality in self.valid_qualities:
                self.quality = db_quality
                LOGGER.info(f"Bugs Manager: Kualitas default dimuat dari DB: {self.quality}")
            else:
                LOGGER.info(f"Bugs Manager: Kualitas default DB tidak ada/valid, menggunakan: {self.quality}")

        except Exception as e:
            LOGGER.error(f"Bugs Manager: Gagal memuat device_id atau kualitas dari DB: {e}. Menggunakan default.")
            if not self.device_id:
                self.device_id = ''.join(random.choices(string.ascii_uppercase + string.ascii_lowercase + string.digits + '_', k=28))


        if not self.account_configs:
            LOGGER.warning("Bugs Manager: Tidak ada akun untuk diinisialisasi (BUGS_EMAIL_1, dll. tidak ada).")
            return

        LOGGER.info(f"Bugs Manager: Menginisialisasi {len(self.account_configs)} akun Bugs...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Bugs Manager: Gagal login ke SEMUA akun Bugs.")
            return

        LOGGER.info(f"Bugs Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun Bugs.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun Bugs (menggunakan asyncio.to_thread)."""
        
        # Ambil proxy dari dictionary jika ada, lalu lempar ke klien API
        proxy = account.get('proxy')
        client = BugsApi(proxy=proxy)
        
        try:
            # Atur device_id yang diperlukan SEBELUM otentikasi
            client.set_session({'device_id': self.device_id})

            # Jalankan login di thread
            await asyncio.to_thread(
                client.auth,
                username=account['email'], 
                password=account['password']
            )
            
            # Verifikasi langganan (mengadaptasi dari interface.py)
            account_data = await asyncio.to_thread(client.get_account)
            subscription = account_data.get('stream') or {}
            
            if not subscription.get('is_cellular_flac') and not subscription.get('is_premium'):
                raise BugsError('Akun memerlukan langganan Streaming (Premium) yang valid')

            # Simpan status premium FLAC ke objek klien agar bisa dicek oleh metadata.py
            client.account_flac_premium = subscription.get('is_flac_premium', False)
            
            LOGGER.info(f"Bugs Manager: Berhasil login ke Akun #{account['id']}. Premium FLAC: {client.account_flac_premium}")
            return client
            
        except Exception as e:
            LOGGER.error(f"Bugs Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            return None

    def get_client(self) -> BugsApi | None:
        """Mengambil klien Bugs yang sudah login dari kumpulan (pool)."""
        if not self._client_cycler:
            LOGGER.error("Bugs Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("Bugs Manager: Kumpulan klien kosong.")
            return None
    
    async def setup_quality(self, user_id: int, qual: str = None):
        """Menyimpan preferensi kualitas pengguna ke cache RAM LOKAL."""
        if qual in self.valid_qualities:
            self.user_data.setdefault(user_id, {})['bugs_qual'] = qual
            LOGGER.debug(f"Bugs Manager: Memperbarui cache RAM lokal untuk user {user_id} ke {qual}")
            
    def get_user_quality(self, user_id: int) -> str:
        """Mengambil preferensi kualitas dari cache RAM, atau mengembalikan default bot."""
        user_qual = self.user_data.get(user_id, {}).get('bugs_qual') 
        
        if user_qual in self.valid_qualities:
            return user_qual
        return self.quality 

    # --- TAMBAHAN BARU: Metode Shutdown ---
    async def shutdown(self):
        """Menutup semua sesi klien BugsApi (requests) yang dikelola."""
        LOGGER.info(f"Bugs Manager: Memulai shutdown... Menutup {len(self.clients)} sesi klien 'requests'.")
        tasks = []
        for client in self.clients:
            if hasattr(client, 'close_session'):
                # Panggil 'close_session' (sinkron) di thread terpisah
                tasks.append(asyncio.to_thread(client.close_session))
        
        # Jalankan semua tugas penutupan secara bersamaan
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            LOGGER.error(f"Bugs Manager: Terjadi error saat shutdown: {e}")
            
        self.clients = []
        self._client_cycler = None
        LOGGER.info("Bugs Manager: Semua sesi klien 'requests' telah ditutup.")
    # --- AKHIR TAMBAHAN ---


# Inisialisasi manajer global
bugs_manager = BugsLoginManager(Config.BUGS_ACCOUNTS)
