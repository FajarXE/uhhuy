# [GANTI FILE: bot/helpers/moov/mvapi.py]

import aiohttp
import asyncio
import uuid
import time
from bot.logger import LOGGER

# --- Konektor Proxy ---
try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.warning("Modul 'aiohttp-socks' tidak ditemukan. Proxy SOCKS5 mungkin tidak jalan.")
    ProxyConnector = None
# ----------------------

class MoovAPI:
    def __init__(self, proxy=None):
        self.base_url = "https://mtg.now.com/moov/api"
        self.session = None
        self.proxy = proxy
        
        # CREDENTIAL STORAGE
        self.email = None
        self.password = None
        
        # LOCKING & STATE
        self._lock = asyncio.Lock() # Kunci untuk mencegah tabrakan login
        self.last_login_time = 0
        
        self.device_id = str(uuid.uuid4())

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10.0.0; PIXEL 2XL Build/NOF26V; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.136 Mobile Safari/537.36/Moov',
            'Referer': 'https://moov.hk/',
            'Origin': 'https://moov.hk'
        }

    async def _get_session(self, force_new=False):
        # Kita tidak mengunci di sini untuk request biasa agar cepat
        # Kunci hanya digunakan saat force_new (reset session)
        
        if force_new:
            if self.session and not self.session.closed:
                await self.session.close()
            self.session = None

        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=30)
            
            if self.proxy:
                if not ProxyConnector:
                    LOGGER.error("Proxy diset tapi aiohttp-socks tidak ada.")
                    self.session = aiohttp.ClientSession(timeout=timeout)
                else:
                    proxy_url = self.proxy
                    use_rdns = False 
                    if proxy_url.startswith("socks5h://"):
                        proxy_url = proxy_url.replace("socks5h://", "socks5://")
                        use_rdns = True
                    
                    # LOGGER.info(f"MoovAPI: Creating Session (RDNS={use_rdns})")
                    connector = ProxyConnector.from_url(proxy_url, rdns=use_rdns)
                    self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            else:
                self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def login(self, email, password):
        self.email = email
        self.password = password
        
        # --- CRITICAL SECTION: HANYA 1 PROSES BOLEH LOGIN ---
        async with self._lock:
            # Cek jika baru saja login (misal < 10 detik lalu) oleh thread lain
            # Jika ya, skip login ulang, langsung return True
            if time.time() - self.last_login_time < 15:
                # LOGGER.info("Moov: Login dilewati (baru saja direfresh oleh thread lain).")
                return True

            # Buat sesi baru (memutus sesi lama yang mungkin error)
            session = await self._get_session(force_new=True)
            
            # Reset Device ID setiap login baru untuk menghindari ban
            self.device_id = str(uuid.uuid4())
            
            data = {
                'deviceid': self.device_id,
                'devicetype': 'Android',
                'clientver': '3.0.7',
                'brand': 'Android',
                'model': 'PIXEL+2XL',
                'os': 'Android',
                'osver': '10.0.0',
                'devicename': 'Google+PIXEL+2XL',
                'connect': 'WiFi',
                'lang': 'en_US',
                'loginid': email,
                'notifyid': '',
                'password': password,
                'autologin': 'true'
            }
            
            try:
                async with session.post(
                    f"{self.base_url}/user/loginstatuscheck", 
                    headers=self.headers, 
                    data=data
                ) as resp:
                    if resp.headers.get('Content-Type') == "application/xml;charset=UTF-8":
                        LOGGER.info(f"Moov: Re-Login Sukses ({email})")
                        self.last_login_time = time.time()
                        return True
                    
                    text = await resp.text()
                    LOGGER.error(f"Moov Login Failed: {text[:100]}...")
                    return False
            except Exception as e:
                LOGGER.error(f"Moov Login Exception: {e}")
                return False

    async def _ensure_active_session(self):
        if not self.session or self.session.closed:
            # Jika sesi mati total, coba buat baru tanpa login dulu
            await self._get_session()

    async def get_album_meta(self, album_id):
        await self._ensure_active_session()
        # Gunakan lock sebentar untuk mengambil session pointer yang aman
        session = await self._get_session()
            
        params = {
            'profileId': album_id,
            'features': '24bit',
            'deviceType': 'phones3',
            'refType': 'PAB',
            'checksum': ''
        }
        try:
            async with session.get(f"{self.base_url}/profile/getProfile", headers=self.headers, params=params) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data.get('dataObject')
        except Exception as e:
            LOGGER.error(f"Moov API Error (Album {album_id}): {e}")
            return None

    async def get_playlist_meta(self, pid):
        await self._ensure_active_session()
        session = await self._get_session()
        
        attempts = []
        if str(pid).startswith("PC"):
             attempts = [
                {"endpoint": "profile/getProfile", "refType": "PP"}, 
                {"endpoint": "profile/getProfile", "refType": "PC"}, 
                {"endpoint": "profile/getProfile", "refType": "PAB"}, 
                {"endpoint": "profile/getProfile", "refType": "CAT"}, 
                {"endpoint": "playlist/getProfile", "refType": "CAT"} 
            ]
        elif str(pid).startswith("PP"):
             attempts = [
                {"endpoint": "profile/getProfile", "refType": "PP"},
                {"endpoint": "profile/getProfile", "refType": "PAB"},
                {"endpoint": "profile/getProfile", "refType": "CAT"}
             ]
        else:
             attempts = [
                {"endpoint": "playlist/getProfile", "refType": "CAT"},
                {"endpoint": "profile/getProfile", "refType": "CAT"},
                {"endpoint": "profile/getProfile", "refType": "PAB"}
            ]

        for config in attempts:
            endpoint = config['endpoint']
            ref_type = config['refType']
            
            params = {
                'profileId': pid,
                'features': '24bit',
                'deviceType': 'phones3',
                'refType': ref_type,
                'checksum': ''
            }
            try:
                async with session.get(f"{self.base_url}/{endpoint}", headers=self.headers, params=params) as resp:
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                        except: continue
                        data_obj = data.get('dataObject')
                        if data_obj and (data_obj.get('modules') or data_obj.get('tracks') or data_obj.get('products')):
                            return data_obj
            except: continue
        return None

    async def get_product_meta(self, product_id):
        await self._ensure_active_session()
        session = await self._get_session()
        params = {'productId': product_id, 'deviceType': 'phones3'}
        try:
            async with session.get(f"{self.base_url}/product/getProduct", headers=self.headers, params=params) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data.get('dataObject')
        except: return None

    async def get_track_file_meta(self, track_id, quality='LL', album_id=None):
        # Retry loop: 0 = Normal attempt, 1 = Retry after Login
        for attempt_no in range(2): 
            # Pastikan session ada
            await self._ensure_active_session()
            session = await self._get_session()
            
            stream_headers = {
                'User-Agent': 'okhttp/4.8.0',
                'Referer': 'https://moov.hk/'
            }
            
            attempts_config = []
            if album_id:
                attempts_config.append({'cat': 'product', 'refid': album_id, 'refType': 'PAB'})
                attempts_config.append({'cat': 'song', 'refid': album_id, 'refType': 'PAB'})
                attempts_config.append({'cat': 'album', 'refid': album_id, 'refType': 'PAB'})
            
            attempts_config.append({'cat': 'product', 'refid': '', 'refType': ''})
            attempts_config.append({'cat': 'song', 'refid': '', 'refType': ''})
            attempts_config.append({'cat': 'video', 'refid': '', 'refType': ''})

            success_data = None

            for conf in attempts_config:
                # Cek jika sesi sudah ditutup oleh thread lain di tengah jalan
                if session.closed:
                     break 

                params = {
                    'clientver': '3.0.7',
                    'action': 'stream',
                    'streamtype': 'stdhls',
                    'preview': 'F',
                    'cat': conf['cat'], 
                    'pid': track_id,
                    'isUpSample': 'false',
                    'osver': '10.0.0',
                    'refid': conf['refid'],      
                    'quality': quality,
                    'devicetype': 'Android',
                    'connect': 'WiFi',
                    'refType': conf['refType'], 
                    'deviceid': self.device_id,
                    'application': 'moovnext',
                    'isStudioMaster': 'true'
                }
                
                try:
                    async with session.get(f"{self.base_url}/content/checkout", headers=stream_headers, params=params) as resp:
                        if resp.status != 200: 
                            continue
                        
                        data = await resp.json()
                        data_obj = data.get('result', {}).get('dataObject')
                        
                        if data_obj and data_obj.get('playUrl') and data_obj.get('contentKey'):
                            success_data = data_obj
                            break # Sukses, keluar dari loop config
                        
                except Exception:
                    # Jika error koneksi terjadi di sini, mungkin session mati
                    continue
            
            if success_data:
                return success_data

            # Jika sampai sini berarti semua config gagal atau session mati.
            # Lakukan Login hanya jika ini attempt pertama
            if attempt_no == 0:
                if self.email and self.password:
                    # LOGGER.warning(f"Moov Checkout Gagal ({track_id}). Requesting Login...")
                    # Panggil login dengan Lock yang aman
                    await self.login(self.email, self.password)
                    continue # Lanjut ke loop attempt_no = 1
                else:
                    break # Tidak ada kredensial, nyerah

        return {}

    async def get_lyrics(self, track_id):
        await self._ensure_active_session()
        session = await self._get_session()
        params = {'pid': track_id}
        try:
            async with session.get(f"{self.base_url}/lyric/getLyric", headers=self.headers, params=params) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data.get('dataObject', {}).get('lyric')
        except: return None

    async def close(self):
        if self.session:
            await self.session.close()
