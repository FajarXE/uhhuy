# [GANTI FILE: bot/helpers/tidal/manager.py]

import asyncio
import itertools
import random
from bot.logger import LOGGER
from config import Config
from .tidal_api import TidalApi 

# Handling Import Database
try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Tidal Manager: Gagal mengimpor 'database'. Fungsi login/kualitas mungkin gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
        async def save_user_settings(self, *args, **kwargs): pass
        async def get_user_settings(self, *args, **kwargs): return {}
    database = DummyDatabase()


class TidalLoginManager:
    """
    Mengelola sesi Tidal:
    1. Global Clients (Dikelola Admin, digunakan bersama/random)
    2. User Clients (Dikelola User, private session, Multi-Account dengan Load Balancing)
    """
    def __init__(self):
        # --- GLOBAL POOL (ADMIN) ---
        self.clients = [] 
        self._client_cycler = None
        
        # --- PRIVATE POOL (USER) ---
        # Format Baru Mapping: user_id -> {'clients': [TidalApi, ...], 'cycler': itertools.cycle}
        self.user_clients = {}
        
        # --- DEFAULT SETTINGS ---
        self.quality = "LOSSLESS" 
        self.spatial = "OFF"
        self.mqa_fix = Config.TIDAL_FIX_MQA
        self.convert_m4a = Config.TIDAL_CONVERT_M4A
        
        self.user_data = {}       

    async def initialize_clients(self):
        """
        Memuat pengaturan global dan akun Global (Admin) dari database.
        """
        self.clients = [] 
        LOGGER.info("Tidal Manager: Menginisialisasi klien Global...")
        
        try:
            all_settings = await database.get_variable()
            if not all_settings:
                all_settings = {}
                
            # 1. Muat Pengaturan Default
            db_quality = all_settings.get('TIDAL_QUALITY')
            if db_quality in ["LOW", "HIGH", "LOSSLESS", "HI_RES"]:
                self.quality = db_quality
            
            db_spatial = all_settings.get('TIDAL_SPATIAL')
            if db_spatial:
                self.spatial = db_spatial
            
            db_mqa_fix = all_settings.get('TIDAL_MQA_FIX')
            if db_mqa_fix in ["ON", "OFF"]:
                self.mqa_fix = db_mqa_fix
            
            db_convert_m4a = all_settings.get('TIDAL_CONVERT_M4A')
            if db_convert_m4a in ["ON", "OFF"]:
                self.convert_m4a = db_convert_m4a
            
            # 2. Muat Daftar Akun Global
            accounts_list = all_settings.get("TIDAL_ACCOUNTS_LIST", [])
            
        except Exception as e:
            LOGGER.error(f"Tidal Manager: Gagal memuat data dari DB: {e}. Menggunakan default.")
            accounts_list = []

        if not accounts_list:
            LOGGER.warning("Tidal Manager: Tidak ada akun Global di database.")
            return

        # 3. Login ke semua akun Global
        LOGGER.info(f"Tidal Manager: Mencoba login ke {len(accounts_list)} akun Global...")
        tasks = []
        for i, auth_data in enumerate(accounts_list):
            tasks.append(self._login_task(auth_data, i + 1))
        
        results = await asyncio.gather(*tasks)
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Tidal Manager: Gagal login ke SEMUA akun Global.")
            return

        LOGGER.info(f"Tidal Manager: {len(self.clients)} Akun Global aktif.")
        
        # Setup Cycler untuk load balancing
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, auth_data: dict, account_id: int):
        """Helper untuk login satu akun."""
        client = TidalApi()
        try:
            await client.login_from_saved(auth_data)
            return client
        except Exception as e:
            LOGGER.error(f"Tidal Manager: Gagal login Akun #{account_id}: {e}")
            # --- [FIX] TUTUP SESI AGAR TIDAK BOCOR ---
            try: await client.close()
            except: pass
            return None

    # ==================================================================
    # LOGIKA KLIEN (GETTER)
    # ==================================================================

    def get_client(self) -> TidalApi | None:
        """
        Mendapatkan klien Global secara acak/bergilir.
        """
        if not self._client_cycler:
            if self.clients:
                 self._client_cycler = itertools.cycle(self.clients)
                 return next(self._client_cycler)
            return None
        
        try:
            clients_list = list(self.clients)
            if len(clients_list) > 1:
                random.shuffle(clients_list)
                self._client_cycler = itertools.cycle(clients_list)
            
            return next(self._client_cycler)
        except StopIteration:
            return None

    async def get_user_client(self, user_id: int) -> TidalApi | None:
        """
        Mendapatkan klien KHUSUS milik user (Private Session) menggunakan Load Balancing (Cycler).
        """
        # 1. Jika belum ada di memori, baca dari DB dan Load SEMUA akun user tersebut
        if user_id not in self.user_clients:
            user_data = await database.get_user_settings(user_id)
            if not user_data:
                return None
                
            # Mengambil dari list format baru, fallback ke format lama jika transisi
            accounts_list = user_data.get('tidal_accounts', [])
            if not accounts_list and user_data.get('tidal_auth'):
                accounts_list = [user_data['tidal_auth']]
                
            if not accounts_list:
                return None
                
            LOGGER.info(f"Tidal Manager: Memuat {len(accounts_list)} sesi privat untuk User {user_id}...")
            clients = []
            for auth_data in accounts_list:
                client = TidalApi()
                try:
                    await client.login_from_saved(auth_data)
                    clients.append(client)
                except Exception as e:
                    LOGGER.error(f"Tidal Manager: Gagal memuat 1 sesi privat user {user_id}: {e}")
                    # --- [FIX] TUTUP SESI AGAR TIDAK BOCOR ---
                    try: await client.close()
                    except: pass
            
            if clients:
                # Simpan list ke memory lengkap dengan cycler-nya
                self.user_clients[user_id] = {
                    'clients': clients,
                    'cycler': itertools.cycle(clients)
                }
            else:
                return None
                
        # 2. Putar akun (Load Balancing per User)
        pool = self.user_clients.get(user_id)
        if pool and pool['clients']:
            return next(pool['cycler'])
        return None

    # ==================================================================
    # MANAJEMEN AKUN (ADD/REMOVE)
    # ==================================================================

    # --- USER PRIVATE ---
    async def add_user_account(self, user_id: int, auth_data: dict):
        """Menyimpan sesi user baru ke Memory."""
        client = TidalApi()
        try:
            await client.login_from_saved(auth_data)
            
            # Jika user belum punya pool akun sama sekali, buatkan
            if user_id not in self.user_clients:
                self.user_clients[user_id] = {'clients': [], 'cycler': None}
                
            # Tambahkan ke daftar akun user di memori
            self.user_clients[user_id]['clients'].append(client)
            self.user_clients[user_id]['cycler'] = itertools.cycle(self.user_clients[user_id]['clients'])
            
            return True, "Login Berhasil"
        except Exception as e:
            return False, str(e)

    async def remove_specific_user_account(self, user_id: int, target_uid: str):
        """Menghapus 1 akun spesifik dari pool Private Session User."""
        target_uid = str(target_uid)
        
        # Hapus dari Memory
        if user_id in self.user_clients:
            pool = self.user_clients[user_id]
            client_to_close = None
            
            for c in pool['clients']:
                if str(c.user_id) == target_uid:
                    client_to_close = c
                    break
                    
            if client_to_close:
                try: await client_to_close.close()
                except: pass
                pool['clients'].remove(client_to_close)
                
                # Refresh Cycler atau Hapus List kalau kosong
                if pool['clients']:
                    pool['cycler'] = itertools.cycle(pool['clients'])
                else:
                    del self.user_clients[user_id]
        return True

    async def remove_user_account(self, user_id: int):
        """(Legacy/Fallback) Menghapus SEMUA sesi user private."""
        if user_id in self.user_clients:
            for client in self.user_clients[user_id]['clients']:
                try: await client.close()
                except: pass
            del self.user_clients[user_id]
        
        await database.save_user_settings(user_id, {'tidal_accounts': [], 'tidal_auth': None})
        return True

    # --- GLOBAL ADMIN (REMOVE SPECIFIC) ---
    async def remove_specific_account(self, target_user_id: str) -> bool:
        """Menghapus akun Global tertentu berdasarkan User ID."""
        target_user_id = str(target_user_id)
        client_removed = False

        client_to_close = None
        for client in self.clients:
            if str(client.user_id) == target_user_id:
                client_to_close = client
                break
        
        if client_to_close:
            await client_to_close.close()
            self.clients.remove(client_to_close)
            LOGGER.info(f"Tidal Manager: Klien Global {target_user_id} dihapus dari memori.")
            client_removed = True
            
            if self.clients:
                self._client_cycler = itertools.cycle(self.clients)
            else:
                self._client_cycler = None

        all_settings = await database.get_variable()
        accounts_list = all_settings.get("TIDAL_ACCOUNTS_LIST", [])
        
        original_len = len(accounts_list)
        new_accounts_list = [
            acc for acc in accounts_list 
            if str(acc.get('user_id')) != target_user_id
        ]
        
        if len(new_accounts_list) < original_len:
            await database.set_variable('TIDAL_ACCOUNTS_LIST', new_accounts_list)
            LOGGER.info(f"Tidal Manager: Akun Global {target_user_id} dihapus dari Database.")
            client_removed = True

        return client_removed

    # ==================================================================
    # PENGATURAN KUALITAS & LAINNYA
    # ==================================================================

    async def setup_user_settings(self, user_id: int, qual: str = None, spatial: str = None, mqa_fix: str = None, convert_m4a: str = None):
        """Mengatur cache kualitas, mqa, & convert untuk pengguna tertentu."""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
            
        if qual in ["LOW", "HIGH", "LOSSLESS", "HI_RES"]:
            self.user_data[user_id]['tidal_qual'] = qual
            
        if spatial in ['OFF', 'ATMOS AC3 JOC', 'ATMOS AC4', 'Sony 360RA']:
            self.user_data[user_id]['tidal_spatial'] = spatial
            
        if mqa_fix in ['ON', 'OFF']:
            self.user_data[user_id]['tidal_mqa_fix'] = mqa_fix
            
        if convert_m4a in ['ON', 'OFF']:
            self.user_data[user_id]['tidal_convert_m4a'] = convert_m4a

    def get_user_quality_settings(self, user_id: int) -> tuple[str, str, str, str]:
        """Mendapatkan kualitas, spasial, mqa, & convert untuk pengguna."""
        user_dict = self.user_data.get(user_id, {})
        
        user_qual = user_dict.get('tidal_qual', self.quality)
        user_spatial = user_dict.get('tidal_spatial', self.spatial)
        user_mqa_fix = user_dict.get('tidal_mqa_fix', self.mqa_fix)
        user_convert_m4a = user_dict.get('tidal_convert_m4a', self.convert_m4a)
        
        return user_qual, user_spatial, user_mqa_fix, user_convert_m4a
    
    async def get_user_qualities_dict(self, user_id: int) -> dict:
        """Mendapatkan dict kualitas dengan tanda centang (helper tombol)."""
        user_qual, _, __, ___ = self.get_user_quality_settings(user_id)
        qualities = {
            "LOW": "LOW",
            "HIGH": "HIGH",
            "LOSSLESS": "LOSSLESS",
            "HI_RES": "HI_RES"
        }
        if user_qual in qualities:
            qualities[user_qual] += " ✅"
        return qualities

    async def get_user_spatial_dict(self, user_id: int) -> str:
        _, user_spatial, __, ___ = self.get_user_quality_settings(user_id)
        return user_spatial

    # ==================================================================
    # SHUTDOWN
    # ==================================================================

    async def shutdown(self):
        """Menutup semua sesi klien TidalApi (Global & User)."""
        LOGGER.info(f"Tidal Manager: Shutdown... Menutup {len(self.clients)} Global Clients.")
        
        tasks = []
        # Close Global
        for client in self.clients:
            tasks.append(client.close())
            
        # Close User Private (Nested List)
        for pool in self.user_clients.values():
            for client in pool['clients']:
                tasks.append(client.close())
        
        if tasks:
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                LOGGER.error(f"Tidal Manager: Error saat shutdown: {e}")
            
        self.clients = []
        self.user_clients = {}
        self._client_cycler = None
        LOGGER.info("Tidal Manager: Semua sesi ditutup.")


tidal_manager = TidalLoginManager()
