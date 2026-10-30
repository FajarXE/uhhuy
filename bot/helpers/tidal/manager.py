# [GANTI FILE: bot/helpers/tidal/manager.py]

import asyncio
import itertools
import random
from bot.logger import LOGGER
from config import Config
from .tidal_api import TidalApi 

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
    1. Global Clients (Dikelola Admin, digunakan bersama/round-robin)
    2. User Clients (Dikelola User, private session, Multi-Account dengan Load Balancing)
    """
    def __init__(self):
        self.clients = [] 
        self._client_cycler = None
        self.user_clients = {}
        
        self.quality = "LOSSLESS" 
        self.spatial = "OFF"
        self.mqa_fix = Config.TIDAL_FIX_MQA
        self.convert_m4a = Config.TIDAL_CONVERT_M4A
        
        self.user_data = {}       

    async def initialize_clients(self):
        """Memuat pengaturan global dan akun Global (Admin) dari database."""
        if hasattr(self, 'clients') and self.clients:
            for old_client in self.clients:
                try: 
                    if hasattr(old_client, 'close'):
                        await old_client.close()
                    elif hasattr(old_client, 'session') and old_client.session:
                        await old_client.session.close()
                except Exception: 
                    pass
        
        self.clients = [] 
        LOGGER.info("Tidal Manager: Menginisialisasi klien Global...")
        
        try:
            all_settings = await database.get_variable()
            if not all_settings:
                all_settings = {}
                
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
            
            accounts_list = all_settings.get("TIDAL_ACCOUNTS_LIST", [])
            
        except Exception as e:
            LOGGER.error(f"Tidal Manager: Gagal memuat data dari DB: {e}. Menggunakan default.")
            accounts_list = []

        if not accounts_list:
            LOGGER.warning("Tidal Manager: Tidak ada akun Global di database.")
            return

        LOGGER.info(f"Tidal Manager: Mencoba login ke {len(accounts_list)} akun Global...")
        tasks = [self._login_task(auth_data, i + 1) for i, auth_data in enumerate(accounts_list)]
        
        results = await asyncio.gather(*tasks)
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Tidal Manager: Gagal login ke SEMUA akun Global.")
            return

        random.shuffle(self.clients)
        self._client_cycler = itertools.cycle(self.clients)
        LOGGER.info(f"Tidal Manager: {len(self.clients)} Akun Global aktif.")

    async def _login_task(self, auth_data: dict, account_id: int):
        """Helper untuk login satu akun."""
        client = TidalApi()
        try:
            await client.login_from_saved(auth_data)
            return client
        except Exception as e:
            LOGGER.error(f"Tidal Manager: Gagal login Akun #{account_id}: {e}")
            try:
                await client.close()
            except Exception:
                pass
            return None

    def get_client(self) -> TidalApi | None:
        """Mendapatkan klien Global secara bergilir (Round-Robin)."""
        if not self.clients:
            return None
        if not self._client_cycler:
            self._client_cycler = itertools.cycle(self.clients)
        try:
            return next(self._client_cycler)
        except StopIteration:
            return None

    async def get_user_client(self, user_id: int) -> TidalApi | None:
        """Mendapatkan 1 klien milik user (Private Session) menggunakan Load Balancing (Cycler)."""
        await self._ensure_user_clients_loaded(user_id)
        pool = self.user_clients.get(user_id)
        if pool and pool['clients']:
            return next(pool['cycler'])
        return None

    async def get_all_user_clients(self, user_id: int) -> list[TidalApi]:
        """Mendapatkan seluruh daftar klien milik user untuk fallback jika salah satu terkena Region Lock."""
        await self._ensure_user_clients_loaded(user_id)
        pool = self.user_clients.get(user_id)
        if pool and pool['clients']:
            return list(pool['clients'])
        return []

    async def _ensure_user_clients_loaded(self, user_id: int):
        if user_id in self.user_clients and self.user_clients[user_id].get('clients'):
            return

        user_data = await database.get_user_settings(user_id)
        if not user_data:
            return
            
        accounts_list = user_data.get('tidal_accounts', [])
        if not accounts_list and user_data.get('tidal_auth'):
            accounts_list = [user_data['tidal_auth']]
            
        if not accounts_list:
            return
            
        LOGGER.info(f"Tidal Manager: Memuat {len(accounts_list)} sesi privat untuk User {user_id}...")
        clients = []
        for auth_data in accounts_list:
            client = TidalApi()
            try:
                await client.login_from_saved(auth_data)
                clients.append(client)
            except Exception as e:
                LOGGER.error(f"Tidal Manager: Gagal memuat 1 sesi privat user {user_id}: {e}")
                try:
                    await client.close()
                except Exception:
                    pass
        
        if clients:
            self.user_clients[user_id] = {
                'clients': clients,
                'cycler': itertools.cycle(clients)
            }

    async def add_user_account(self, user_id: int, auth_data: dict):
        """Menyimpan sesi user baru ke Memory."""
        client = TidalApi()
        try:
            await client.login_from_saved(auth_data)
            
            if user_id not in self.user_clients:
                self.user_clients[user_id] = {'clients': [], 'cycler': None}
            
            # Hindari duplikasi user_id di dalam pool
            existing = self.user_clients[user_id]['clients']
            for old_c in list(existing):
                if str(old_c.user_id) == str(client.user_id):
                    try:
                        await old_c.close()
                    except Exception:
                        pass
                    existing.remove(old_c)

            existing.append(client)
            self.user_clients[user_id]['cycler'] = itertools.cycle(existing)
            
            return True, "Login Berhasil"
        except Exception as e:
            try:
                await client.close()
            except Exception:
                pass
            return False, str(e)

    async def remove_specific_user_account(self, user_id: int, target_uid: str):
        """Menghapus 1 akun spesifik dari pool Private Session User."""
        target_uid = str(target_uid)
        
        if user_id in self.user_clients:
            pool = self.user_clients[user_id]
            client_to_close = None
            
            for c in pool['clients']:
                if str(c.user_id) == target_uid:
                    client_to_close = c
                    break
                    
            if client_to_close:
                try:
                    await client_to_close.close()
                except Exception:
                    pass
                pool['clients'].remove(client_to_close)
                
                if pool['clients']:
                    pool['cycler'] = itertools.cycle(pool['clients'])
                else:
                    del self.user_clients[user_id]
        return True

    async def remove_user_account(self, user_id: int):
        """Menghapus SEMUA sesi user private."""
        if user_id in self.user_clients:
            for client in self.user_clients[user_id]['clients']:
                try:
                    await client.close()
                except Exception:
                    pass
            del self.user_clients[user_id]
        
        await database.save_user_settings(user_id, {'tidal_accounts': [], 'tidal_auth': None})
        return True

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

    async def setup_quality(self, user_id: int=0, qual: str="", spatial: str="") -> None:
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        if qual:
            self.user_data[user_id]["tidal_qual"] = qual
        if spatial:
            self.user_data[user_id]["tidal_spatial"] = spatial

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
        combined_dict = {}
        try:
            from bot.settings import bot_set
            bot_user_dict = bot_set.user_data.get(user_id) or bot_set.user_data.get(str(user_id)) or {}
            combined_dict.update(bot_user_dict)
        except Exception:
            pass

        local_user_dict = self.user_data.get(user_id) or self.user_data.get(str(user_id)) or {}
        combined_dict.update(local_user_dict)
        
        user_qual = combined_dict.get('tidal_qual') or self.quality
        user_spatial = combined_dict.get('tidal_spatial') or self.spatial
        user_mqa_fix = combined_dict.get('tidal_mqa_fix') or self.mqa_fix
        user_convert_m4a = combined_dict.get('tidal_convert_m4a') or self.convert_m4a
        
        return user_qual, user_spatial, user_mqa_fix, user_convert_m4a
    
    async def get_user_qualities_dict(self, user_id: int) -> dict:
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

    async def shutdown(self):
        """Menutup semua sesi klien TidalApi (Global & User) serta sesi metadata."""
        LOGGER.info(f"Tidal Manager: Shutdown... Menutup {len(self.clients)} Global Clients.")
        
        tasks = []
        for client in self.clients:
            tasks.append(client.close())
            
        for pool in self.user_clients.values():
            for client in pool['clients']:
                tasks.append(client.close())

        try:
            from .metadata import close_tidal_meta_session
            tasks.append(close_tidal_meta_session())
        except Exception:
            pass
        
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                LOGGER.error(f"Tidal Manager: Error saat shutdown: {e}")
            
        self.clients = []
        self.user_clients = {}
        self._client_cycler = None
        LOGGER.info("Tidal Manager: Semua sesi ditutup.")


tidal_manager = TidalLoginManager()
