# [GANTI FILE: bot/helpers/qobuz/qopy.py]

import time
import hashlib
import aiohttp
import aiolimiter
import asyncio
import traceback
import json
import os

from config import Config
from .bundle import Bundle
from bot.logger import LOGGER

# [BARU] Import Database & Settings untuk persistensi MongoDB
from bot.helpers.database.mongo_async import database
from bot.settings import bot_set

class QoClient:
    def __init__(self, email=None, password=None, user_id=None, user_token=None):
        self.email = email
        self.password = password
        self.user_id = str(user_id) if user_id else None
        self.user_token = user_token
        self.uat = None
        self.label = None
        self.sec = None
        self.id = None
        self.secrets = None
        self.session = None
        self.ratelimit = aiolimiter.AsyncLimiter(30, 60)
        self.base = "https://www.qobuz.com/api.json/0.2/"
        self.quality = 6 # Default 6 (Lossless)
        
    async def api_call(self, epoint, **kwargs):
        if epoint == "user/login":
            if kwargs.get('email'):
                params = {
                    "email": kwargs["email"],
                    "password": kwargs["pwd"],
                    "app_id": self.id,
                }
            else:
                params = {
                    "user_id": kwargs["userid"],
                    "user_auth_token": kwargs["usertoken"],
                    "app_id": self.id,
                }
        elif epoint == "track/get":
            params = {"track_id": kwargs["id"]}
        elif epoint == "album/get":
            params = {"album_id": kwargs["id"]}
        elif epoint == "playlist/get":
            params = {
                "extra": "tracks",
                "playlist_id": kwargs["id"],
                "limit": 99999,
                "offset": kwargs["offset"],
            }
        elif epoint == "artist/get":
            params = {
                "app_id": self.id,
                "artist_id": kwargs["id"],
                "limit": 99999,
                "offset": kwargs["offset"],
                "extra": "albums",
            }
        elif epoint == "label/get":
            params = {
                "label_id": kwargs["id"],
                "limit": 99999,
                "offset": kwargs["offset"],
                "extra": "albums",
            }
        elif epoint == "favorite/getUserFavorites":
            unix = int(time.time())
            r_sig = "favoritegetUserFavorites" + str(unix) + kwargs["sec"]
            
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {
                "app_id": self.id,
                "user_auth_token": self.uat,
                "type": "albums",
                "request_ts": unix,
                "request_sig": r_sig_hashed,
            }
        elif epoint == "track/getFileUrl":
            unix = int(time.time())
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            
            if int(fmt_id) not in (5, 6, 7, 27):
                LOGGER.warning(f"QOBUZ: Format ID {fmt_id} tidak valid, fallback ke 6 (Lossless).")
                fmt_id = 6
            
            r_sig = "trackgetFileUrlformat_id{}intentstreamtrack_id{}{}{}".format(
                fmt_id, track_id, unix, kwargs.get("sec", self.sec)
            )
            
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {
                "request_ts": unix,
                "request_sig": r_sig_hashed,
                "track_id": track_id,
                "format_id": fmt_id,
                "intent": "stream",
            }
        else:
            params = kwargs

        return await self.session_call(epoint, params)

    async def session_call(self, epoint, params):
        async with self.ratelimit:
            async with self.session.get(self.base + epoint, params=params) as r:
                if epoint == "user/login":
                    if r.status == 401:
                        raise Exception('QOBUZ : Kredensial tidak valid.')
                    elif r.status == 400:
                        raise Exception("QOBUZ : Invalid App ID/Request. Cek kembali User ID dan Token.")
                
                if r.status == 403:
                    raise Exception(f"{r.status}, message='Forbidden / Geo-blocked', url='{r.url}'")
                
                try:
                    return await r.json()
                except aiohttp.ContentTypeError:
                    LOGGER.error(f"QOBUZ: Respons bukan JSON diterima dari {epoint} (Status: {r.status})")
                    return None

    async def multi_meta(self, epoint, key, id, type):
        total = 1
        offset = 0
        while total > 0:
            j = await self.api_call(epoint, id=id, offset=offset, type=type)
            
            if j is None:
                LOGGER.error(f"QOBUZ Error: Panggilan API ke {epoint} untuk ID {id} gagal (menerima None).")
                return

            try:
                if type in ["tracks", "albums"]:
                    j_iterable = j.get(type)
                    if j_iterable is None:
                        LOGGER.warning(f"QOBUZ Info: Respons untuk {epoint} tidak memiliki kunci '{type}'.")
                        yield {type: {'items': [], key: 0}}
                        return
                else:
                    j_iterable = j

                if offset == 0:
                    total_items = j_iterable.get(key)
                    if total_items is None:
                        yield j 
                        return
                        
                    yield j 
                    total = total_items - 99999
                else:
                    yield j 
                    total -= 99999
                offset += 99999
            
            except Exception as e:
                LOGGER.error(f"QOBUZ Multi-Meta Parsing Gagal untuk {epoint}: {e}")
                return 

    async def auth(self):
        if self.email:
            usr_info = await self.api_call(
                "user/login", 
                email=self.email, 
                pwd=self.password)
        elif self.user_id:
            usr_info = await self.api_call(
                "user/login", 
                userid=self.user_id,
                usertoken=self.user_token)
        else:
            raise Exception("QOBUZ : No credentials provided.")
        
        if not usr_info:
            raise Exception("QOBUZ : Gagal login, respons API kosong.")
            
        if not usr_info.get("user"):
             raise Exception(f"QOBUZ : Gagal login. Respons: {usr_info}")

        if not usr_info["user"].get("credential") or not usr_info["user"]["credential"].get("parameters"):
            raise Exception("QOBUZ : Akun Free tidak dapat mendownload track.")
        
        self.uat = usr_info["user_auth_token"]
        self.session.headers.update({"X-User-Auth-Token": self.uat})
        self.label = usr_info["user"]["credential"]["parameters"]["short_label"]
        
        # Override user_id jika login via email, untuk referensi
        if not self.user_id:
            self.user_id = str(usr_info["user"]["id"])

        LOGGER.info(f"QOBUZ : Login sebagai {self.user_id}. Status: {self.label}")

    async def test_secret(self, sec):
        test_epoint = "track/getFileUrl"
        unix = int(time.time())
        # Track ID Random untuk test sign
        r_sig = "trackgetFileUrlformat_id5intentstreamtrack_id5966783{}{}".format(unix, sec)
        r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
        
        params = {
            "request_ts": unix,
            "request_sig": r_sig_hashed,
            "track_id": 5966783, 
            "format_id": 5,
            "intent": "stream",
        }
        
        try:
            async with self.ratelimit:
                async with self.session.get(self.base + test_epoint, params=params) as r:
                    if r.status == 200:
                        return True
                    return False
        except Exception as e:
            LOGGER.debug(f"Test Secret Failed: {e}")
            return False

    def get_tokens(self):
        bundle = Bundle()
        self.id = str(bundle.get_app_id())
        self.secrets = [
            secret for secret in bundle.get_secrets().values() if secret
        ]

    async def login(self):
        self.get_tokens()
        
        # --- LOGIKA SOCKS PROXY CONNECTOR GLOBAL ---
        connector = None
        if getattr(Config, 'QOBUZ_PROXY', None):
            try:
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(Config.QOBUZ_PROXY)
            except ImportError:
                LOGGER.warning("QOBUZ: Modul aiohttp_socks tidak terinstall! Mengabaikan Proxy.")
        # -------------------------------------------

        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=60)
        ) 
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0",
                "X-App-Id": self.id,
            }
        )
        await self.auth()
        await self.cfg_setup()

    async def cfg_setup(self):
        for secret in self.secrets:
            if not secret:
                continue
            if await self.test_secret(secret):
                self.sec = secret
                break
        if self.sec is None:
            raise Exception("QOBUZ : Can't find any valid app secret") 

    async def get_track_url(self, id, user: dict):
        tg_user_id = user.get("user_id")
        quality = self.quality
        
        if tg_user_id:
            # Baca langsung dari RAM (Memory yang disinkronkan)
            user_settings = bot_set.user_data.get(int(tg_user_id), {})
            quality = user_settings.get("qobuz_qual", self.quality)

        return await self.api_call("track/getFileUrl", id=id, fmt_id=quality)

    async def get_album_meta(self, id):
        return await self.api_call("album/get", id=id)

    async def get_track_meta(self, id):
        return await self.api_call("track/get", id=id)

    async def get_artist_meta(self, id):
        res = []
        async for data in self.multi_meta("artist/get", "total", id, "albums"): 
            res.append(data)
        return res

    async def get_plist_meta(self, id):
        res = []
        async for data in self.multi_meta("playlist/get", "total", id, "tracks"): 
            res.append(data)
        return res

    async def get_label_meta(self, id):
        res = []
        async for data in self.multi_meta("label/get", "total", id, "albums"):
            res.append(data)
        return res

    async def setup_quality(self, user_id: int=0, qual: int=0) -> None:
        try:
            user_id = int(user_id)
            qual = int(qual)
            
            # 1. Simpan ke Memory (agar akses cepat)
            if user_id not in bot_set.user_data:
                bot_set.user_data[user_id] = {}
            bot_set.user_data[user_id]['qobuz_qual'] = qual
            
            # 2. Simpan ke MongoDB (Permanen)
            await database.save_user_settings(user_id, {'qobuz_qual': qual})
        except Exception as e:
            LOGGER.error(f"QOBUZ: Gagal setup quality: {e}")

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()


# ==========================================
# QOBUZ MANAGER (MONGODB PERSISTENCE)
# ==========================================

class QobuzManager:
    def __init__(self):
        self.user_clients = {} # Cache Sesi Aktif

    def _read_db(self):
        return {} 

    async def add_user_account(self, tg_user_id, q_user_id, q_token):
        """Menambahkan akun ke MongoDB dan Memory."""
        temp_client = QoClient(user_id=q_user_id, user_token=q_token)
        try:
            await temp_client.login()
            label = temp_client.label
        except Exception as e:
            await temp_client.close_session()
            return False, f"Login Gagal: {str(e)}"
        
        await temp_client.close_session()

        tg_user_id = int(tg_user_id)
        
        # 1. Pastikan dictionary user ada di Memory
        if tg_user_id not in bot_set.user_data:
            bot_set.user_data[tg_user_id] = {}
            
        current_accounts = bot_set.user_data[tg_user_id].get('qobuz_accounts', [])
        
        # 2. Update List (Hapus jika ada yang sama, lalu tambahkan yang baru)
        new_list = [acc for acc in current_accounts if str(acc['user_id']) != str(q_user_id)]
        
        new_account = {
            "user_id": str(q_user_id),
            "token": q_token,
            "label": label
        }
        new_list.append(new_account)
        
        # 3. Simpan ke Memory & MongoDB
        bot_set.user_data[tg_user_id]['qobuz_accounts'] = new_list
        await database.save_user_settings(tg_user_id, {'qobuz_accounts': new_list})
        
        # 4. Reset Cache
        if tg_user_id in self.user_clients:
            for c in self.user_clients[tg_user_id]:
                await c.close_session()
            del self.user_clients[tg_user_id]
            
        return True, f"Akun {label} berhasil disimpan permanen!"

    async def remove_specific_account(self, tg_user_id, target_q_uid):
        tg_user_id = int(tg_user_id)
        target_q_uid = str(target_q_uid)
        
        if tg_user_id not in bot_set.user_data:
            return False
            
        current_accounts = bot_set.user_data[tg_user_id].get('qobuz_accounts', [])
        
        # Filter: Ambil semua KECUALI yang target_q_uid
        new_list = [acc for acc in current_accounts if str(acc['user_id']) != target_q_uid]
        
        # Jika panjang list berubah, berarti ada yang dihapus
        if len(new_list) < len(current_accounts):
            bot_set.user_data[tg_user_id]['qobuz_accounts'] = new_list
            await database.save_user_settings(tg_user_id, {'qobuz_accounts': new_list})
            
            # Reset cache agar sesi yang dihapus benar-benar hilang dari memori
            if tg_user_id in self.user_clients:
                for c in self.user_clients[tg_user_id]:
                    await c.close_session()
                del self.user_clients[tg_user_id]
            return True
            
        return False

    def has_private_session(self, tg_user_id):
        # Cek langsung dari Memory bot_set
        tg_user_id = int(tg_user_id)
        if tg_user_id in bot_set.user_data:
            accounts = bot_set.user_data[tg_user_id].get('qobuz_accounts', [])
            return len(accounts) > 0
        return False

    async def get_user_clients(self, tg_user_id):
        tg_user_id = int(tg_user_id)
        
        # 1. Cek Cache Memory (Sesi yang sedang aktif)
        if tg_user_id in self.user_clients:
            active_clients = [c for c in self.user_clients[tg_user_id] if c.session and not c.session.closed]
            if active_clients:
                return active_clients
        
        # 2. Jika tidak ada di cache, buat instance baru dari data MongoDB (via bot_set)
        loaded_clients = []
        if tg_user_id in bot_set.user_data:
            accounts = bot_set.user_data[tg_user_id].get('qobuz_accounts', [])
            
            for acc in accounts:
                client = QoClient(user_id=acc['user_id'], user_token=acc['token'])
                try:
                    await client.login()
                    client.label = f"{client.label} (Pribadi)"
                    loaded_clients.append(client)
                except Exception as e:
                    LOGGER.error(f"Gagal login ulang akun user {tg_user_id} (ID: {acc['user_id']}): {e}")
            
            if loaded_clients:
                self.user_clients[tg_user_id] = loaded_clients
                
        return loaded_clients

    async def setup_quality(self, user_id, quality):
        user_id = int(user_id)
        if user_id not in bot_set.user_data:
            bot_set.user_data[user_id] = {}
        bot_set.user_data[user_id]['qobuz_qual'] = int(quality)
        await database.save_user_settings(user_id, {'qobuz_qual': int(quality)})

# Instance Global
qobuz_manager = QobuzManager()
