# [GANTI FILE: bot/helpers/deezer/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config
from .dzapi import DeezerAPI

# Import Database & Settings untuk persistensi MongoDB
from bot.helpers.database.mongo_async import database
from bot.settings import bot_set

# --- Definisikan Error Kustom ---
class DeezerError(Exception):
    pass

class DeezerLoginManager:
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = []        # Global Clients (Config)
        self.user_clients = {}   # Private Clients Cache {user_id: [Client1, Client2]}
        self._client_cycler = None
        self.quality = "FLAC" 
        self.user_data = {} 

    async def initialize_clients(self):
        """Login akun Global (dari Config)."""
        # 1. Muat Kualitas Default dari DB
        try:
            all_settings = await database.get_variable()
            db_quality = all_settings.get('DEEZER_QUALITY') if all_settings else None
            if db_quality in ["FLAC", "MP3_320", "MP3_128"]:
                self.quality = db_quality
        except Exception as e:
            LOGGER.error(f"Deezer Manager: Gagal memuat kualitas DB: {e}")

        # 2. Login Akun Global
        if not self.account_configs:
            LOGGER.warning("Deezer Manager: Tidak ada akun Global (Config).")
            return

        LOGGER.info(f"Deezer Manager: Menginisialisasi {len(self.account_configs)} akun Global...")
        tasks = [self._login_task(acc) for acc in self.account_configs]
        results = await asyncio.gather(*tasks)
        self.clients = [c for c in results if c is not None]
        
        if self.clients:
            self._client_cycler = itertools.cycle(self.clients)
            LOGGER.info(f"Deezer Manager: {len(self.clients)} Akun Global Siap.")

    async def _login_task(self, account: dict):
        client = DeezerAPI()
        try:
            await client.login(arl=account['arl'])
            return client
        except Exception as e:
            LOGGER.error(f"Deezer Global Login Failed: {e}")
            await client.close()
            return None

    def get_client(self) -> DeezerAPI | None:
        """Ambil klien Global (Round Robin)."""
        if not self._client_cycler: return None
        try:
            return next(self._client_cycler)
        except: return None

    # --- PENGATURAN KUALITAS ---
    async def setup_quality(self, user_id: int, qual: str = None):
        if user_id not in self.user_data: self.user_data[user_id] = {}
        if qual in ["FLAC", "MP3_320", "MP3_128"]:
            self.user_data[user_id]['deezer_qual'] = qual
            # Simpan juga ke MongoDB permanen agar sinkron dengan qopy/settings
            await database.save_user_settings(user_id, {'deezer_qual': qual})

    def get_user_quality(self, user_id: int) -> str:
        # Cek Memory (bot_set) dulu karena user_settings.py menyimpannya di sana
        if user_id in bot_set.user_data and 'deezer_qual' in bot_set.user_data[user_id]:
            return bot_set.user_data[user_id]['deezer_qual']
        # Fallback ke cache internal manager
        return self.user_data.get(user_id, {}).get('deezer_qual', self.quality)

    # ==========================================
    # LOGIKA PRIVATE ACCOUNT (MULTI-LOGIN)
    # ==========================================

    async def add_user_account(self, tg_user_id, arl):
        """Menambahkan akun pribadi ke MongoDB."""
        # 1. Validasi Login
        temp_client = DeezerAPI()
        try:
            await temp_client.login(arl=arl)
            user_data = temp_client.user
            dz_user_id = user_data['USER']['USER_ID']
            dz_name = user_data['USER']['BLOG_NAME'] # Username Deezer
            label = f"{dz_name} ({dz_user_id})"
        except Exception as e:
            await temp_client.close()
            return False, f"Login Gagal: {str(e)}"
        
        await temp_client.close()

        tg_user_id = int(tg_user_id)
        
        # 2. Update Memory & DB
        if tg_user_id not in bot_set.user_data:
            bot_set.user_data[tg_user_id] = {}
            
        current_accounts = bot_set.user_data[tg_user_id].get('deezer_accounts', [])
        
        # Hapus duplikat jika ID Deezer sama
        new_list = [acc for acc in current_accounts if str(acc.get('user_id')) != str(dz_user_id)]
        
        new_account = {
            "user_id": str(dz_user_id),
            "arl": arl,
            "label": dz_name
        }
        new_list.append(new_account)
        
        bot_set.user_data[tg_user_id]['deezer_accounts'] = new_list
        await database.save_user_settings(tg_user_id, {'deezer_accounts': new_list})
        
        # Reset cache agar dimuat ulang
        if tg_user_id in self.user_clients:
            for c in self.user_clients[tg_user_id]:
                await c.close()
            del self.user_clients[tg_user_id]
            
        return True, f"Akun {label} berhasil disimpan!"

    async def remove_specific_account(self, tg_user_id, target_dz_uid):
        tg_user_id = int(tg_user_id)
        target_dz_uid = str(target_dz_uid)
        
        if tg_user_id not in bot_set.user_data: return False
            
        current_accounts = bot_set.user_data[tg_user_id].get('deezer_accounts', [])
        new_list = [acc for acc in current_accounts if str(acc.get('user_id')) != target_dz_uid]
        
        if len(new_list) < len(current_accounts):
            bot_set.user_data[tg_user_id]['deezer_accounts'] = new_list
            await database.save_user_settings(tg_user_id, {'deezer_accounts': new_list})
            
            if tg_user_id in self.user_clients:
                for c in self.user_clients[tg_user_id]:
                    await c.close()
                del self.user_clients[tg_user_id]
            return True
        return False

    def has_private_session(self, tg_user_id):
        tg_user_id = int(tg_user_id)
        if tg_user_id in bot_set.user_data:
            accounts = bot_set.user_data[tg_user_id].get('deezer_accounts', [])
            return len(accounts) > 0
        return False

    async def get_user_clients(self, tg_user_id):
        """Mengembalikan LIST objek DeezerAPI yang aktif untuk user ini."""
        tg_user_id = int(tg_user_id)
        
        # Cek Cache
        if tg_user_id in self.user_clients:
            active = [c for c in self.user_clients[tg_user_id] if c.session and not c.session.closed]
            if active: return active
        
        # Load dari DB/Memory
        loaded_clients = []
        if tg_user_id in bot_set.user_data:
            accounts = bot_set.user_data[tg_user_id].get('deezer_accounts', [])
            
            for acc in accounts:
                client = DeezerAPI()
                try:
                    await client.login(arl=acc['arl'])
                    # Labeling untuk log
                    client.user['USER']['BLOG_NAME'] += " (Pribadi)"
                    loaded_clients.append(client)
                except Exception as e:
                    LOGGER.error(f"Gagal login ulang Deezer User {tg_user_id}: {e}")
                    await client.close()
            
            if loaded_clients:
                self.user_clients[tg_user_id] = loaded_clients
                
        return loaded_clients

    async def shutdown(self):
        # Tutup Global
        for c in self.clients: await c.close()
        # Tutup Private
        for uid, clients in self.user_clients.items():
            for c in clients: await c.close()
        self.clients = []
        self.user_clients = {}
        try:
            from .metadata import close_meta_session
            await close_meta_session()
        except Exception:
            pass

deezer_manager = DeezerLoginManager(Config.DEEZER_ACCOUNTS)
