# [GANTI SELURUH FILE: bot/helpers/highresaudio/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config
from bot.helpers.database.mongo_async import database # Import Database

try:
    from .api import HighResAudioApi
except ImportError:
    class HighResAudioApi: 
        def close_session(self): pass
    LOGGER.critical("HighResAudio: Gagal mengimpor 'HighResAudioApi' dari '.api'.")

class HighResAudioError(Exception):
    pass

class HighResAudioLoginManager:
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self.user_clients = {}
        self._client_cycler = None
        
    async def initialize_clients(self):
        # 1. INISIALISASI AKUN GLOBAL (BOT)
        if self.account_configs:
            LOGGER.info(f"HighResAudio Manager: Menginisialisasi {len(self.account_configs)} akun global...")
            tasks = []
            for account in self.account_configs:
                tasks.append(self._login_task(account))
            
            results = await asyncio.gather(*tasks)
            self.clients = [client for client in results if client is not None]
            
            if self.clients:
                LOGGER.info(f"HighResAudio Manager: Berhasil login ke {len(self.clients)} akun global.")
                self._client_cycler = itertools.cycle(self.clients)
            else:
                LOGGER.error("HighResAudio Manager: Gagal login ke SEMUA akun global.")
        else:
            LOGGER.warning("HighResAudio Manager: Tidak ada akun global (Bot) yang dikonfigurasi.")

        # 2. MUAT AKUN PENGGUNA DARI DATABASE
        # Kita menggunakan database.initialize_users() yang ada di mongo_async.py Anda
        LOGGER.info("HighResAudio Manager: Memuat sesi pengguna dari database...")
        
        try:
            # initialize_users mengembalikan dict: {user_id: {data_dict}, ...}
            users_dict = await database.initialize_users()
            
            count_relogin = 0
            for user_id, user_data in users_dict.items():
                # Ambil string auth 'email:password'
                hra_data = user_data.get('highresaudio_auth')
                
                if hra_data and ":" in hra_data:
                    try:
                        email, password = hra_data.split(":", 1)
                        # Login diam-diam (Silent Login)
                        # save_db=False karena data sudah ada di DB
                        success, _ = await self.add_user_account(user_id, email, password, save_db=False)
                        if success:
                            count_relogin += 1
                    except Exception as e:
                        LOGGER.warning(f"Gagal restore sesi HRA untuk user {user_id}: {e}")

            if count_relogin > 0:
                LOGGER.info(f"HighResAudio Manager: Berhasil memulihkan {count_relogin} sesi pengguna.")
                
        except Exception as e:
            LOGGER.error(f"HighResAudio Manager: Error saat memuat database: {e}")

    async def _login_task(self, account: dict):
        proxy = account.get('proxy')
        client = HighResAudioApi(
            exception=HighResAudioError,
            proxy=proxy 
        )
        try:
            await asyncio.to_thread(
                client.auth,
                username=account['email'], 
                password=account['password']
            )
            return client
        except Exception as e:
            LOGGER.error(f"HighResAudio Manager: Gagal login ke Akun Global {account['email']}. Error: {e}")
            if hasattr(client, 'close_session'):
                client.close_session()
            return None

    # Tambahkan parameter save_db agar fleksibel
    async def add_user_account(self, user_id: int, email, password, save_db=True):
        LOGGER.info(f"HighResAudio: User {user_id} mencoba login akun {email}...")
        
        client = HighResAudioApi(
            exception=HighResAudioError,
            proxy=None 
        )
        
        try:
            await asyncio.to_thread(
                client.auth,
                username=email,
                password=password
            )
            
            if user_id in self.user_clients:
                try: self.user_clients[user_id].close_session()
                except: pass
            
            self.user_clients[user_id] = client
            
            # Simpan ke Database (Hanya jika save_db=True)
            # Ini akan memanggil save_user_settings di mongo_async.py Anda
            if save_db:
                auth_str = f"{email}:{password}"
                await database.save_user_settings(user_id, {'highresaudio_auth': auth_str})
            
            LOGGER.info(f"HighResAudio: User {user_id} berhasil login.")
            return True, "Login Berhasil!"
            
        except Exception as e:
            LOGGER.error(f"HighResAudio: User {user_id} gagal login: {e}")
            if hasattr(client, 'close_session'):
                client.close_session()
            return False, str(e)

    async def remove_user_account(self, user_id: int):
        # 1. Hapus Sesi Memory
        if user_id in self.user_clients:
            try: self.user_clients[user_id].close_session()
            except: pass
            del self.user_clients[user_id]
            
        # 2. Hapus dari Database
        await database.save_user_settings(user_id, {'highresaudio_auth': None})

    def get_client(self, user_id: int = None) -> HighResAudioApi | None:
        if user_id and user_id in self.user_clients:
            return self.user_clients[user_id]
        
        if self._client_cycler:
            try:
                return next(self._client_cycler)
            except StopIteration:
                pass
                
        return None

    async def shutdown(self):
        LOGGER.info("HighResAudio Manager: Memulai shutdown...")
        for client in self.clients:
            if hasattr(client, 'close_session'):
                try: client.close_session()
                except: pass
        for uid, client in self.user_clients.items():
            if hasattr(client, 'close_session'):
                try: client.close_session()
                except: pass
        
        self.clients = []
        self.user_clients = {}
        self._client_cycler = None

highresaudio_manager = HighResAudioLoginManager(Config.HIGHRESAUDIO_ACCOUNTS)
