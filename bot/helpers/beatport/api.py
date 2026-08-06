import aiohttp
import asyncio
import random
from datetime import timedelta, datetime
from bot.logger import LOGGER

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.warning("Modul 'aiohttp_socks' tidak ditemukan. Proxy SOCKS/SOCKS5H tidak akan berjalan.")
    ProxyConnector = None

BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
APP_USER_AGENT = "Serato DJ Lite/3.2.1 (Windows NT 10.0; Win64; x64)"

class BeatportError(Exception):
    def __init__(self, message):
        self.message = message
        super(BeatportError, self).__init__(message)

class BeatportAPI:
    def __init__(self):
        self.API_URL = "https://api.beatport.com/v4/"
        self.client_id = "Zy2K9Wvy6DkUds7g8s1GNMHfk17E5Ch2BWHlyaGY"
        self.redirect_uri = "seratodjlite://beatport"

        self.access_token = None
        self.refresh_token = None
        self.expires = None
        
        self.email = None
        self.password_cache = None
        self.proxy = None
        self.session = None 

    async def _init_session(self):
        if self.session is None or self.session.closed:
            connector = None
            
            if self.proxy:
                if ProxyConnector:
                    try:
                        proxy_url = self.proxy
                        use_rdns = False
                        if proxy_url.startswith("socks5h://"):
                            proxy_url = proxy_url.replace("socks5h://", "socks5://")
                            use_rdns = True
                        
                        connector = ProxyConnector.from_url(proxy_url, rdns=use_rdns)
                        LOGGER.debug(f"BeatportAPI: Menggunakan Proxy untuk {self.email}")
                    except Exception as e:
                        LOGGER.error(f"BeatportAPI: Gagal Proxy: {e}")
                else:
                    LOGGER.error("BeatportAPI: Proxy diset tapi 'aiohttp_socks' belum diinstall.")

            self.session = aiohttp.ClientSession(
                headers={'User-Agent': BROWSER_USER_AGENT},
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                connector=connector
            )

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_headers(self, use_access_token: bool = False):
        headers = {}
        if use_access_token and self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
            headers['User-Agent'] = APP_USER_AGENT
        else:
            headers['User-Agent'] = BROWSER_USER_AGENT
        return headers

    async def load_session(self, token_data: dict):
        await self._init_session()
        self.access_token = token_data.get('access_token')
        self.refresh_token = token_data.get('refresh_token')
        self.email = token_data.get('email')
        self.expires = datetime.now() - timedelta(seconds=10)

    async def login(self, email: str, password: str):
        self.email = email
        self.password_cache = password
        await self._init_session()
        
        params_auth = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
        }
        
        await asyncio.sleep(random.uniform(1.0, 2.0))
        
        async with self.session.get(f"{self.API_URL}auth/o/authorize/", params=params_auth, allow_redirects=False) as r:
            if r.status != 302:
                try: err_text = await r.text()
                except: err_text = "Unknown"
                raise BeatportError(f"Auth step 1 gagal ({r.status}): {err_text}")
            
            base_url = str(r.url).replace(r.request_info.url.path_qs, '')
            referer = base_url + r.headers['location']

        json_login = {"username": email, "password": password}
        
        await asyncio.sleep(random.uniform(1.5, 2.5))
        
        async with self.session.post(f"{self.API_URL}auth/login/", json=json_login, headers={"Referer": referer}) as r:
            if r.status != 200:
                try:
                    err_json = await r.json()
                except: pass
                raise BeatportError(f"Login gagal (Cek password / Captcha): {r.status}")

        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        async with self.session.get(f"{self.API_URL}auth/o/authorize/", params=params_auth, allow_redirects=False) as r:
            if r.status != 302:
                raise BeatportError(f"Auth step 3 gagal ({r.status})")
            
            location = r.headers.get('location')
            if not location or 'code=' not in location:
                 raise BeatportError("Gagal mendapatkan Auth Code dari header location.")
            
            code = location.split('code=')[1]

        data_token = {
            "client_id": self.client_id,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        
        await asyncio.sleep(random.uniform(0.5, 1.0))
        
        async with self.session.post(f"{self.API_URL}auth/o/token/", data=data_token) as r:
            if r.status != 200:
                raise BeatportError(f"Auth step 4 gagal: {await r.text()}")
            
            resp_json = await r.json()
            self.access_token = resp_json['access_token']
            self.refresh_token = resp_json['refresh_token']
            self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
            LOGGER.info(f"Beatport: Login berhasil untuk {email}")

    async def refresh(self):
        await self._init_session()
        data = {
            'client_id': self.client_id,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
        }
        
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        async with self.session.post(f'{self.API_URL}auth/o/token/', data=data) as r:
            if r.status != 200:
                raise BeatportError("Gagal refresh token (Invalid Grant)")
            
            resp_json = await r.json()
            self.access_token = resp_json['access_token']
            self.refresh_token = resp_json['refresh_token']
            self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])

    async def _get(self, endpoint: str, params: dict = None):
        await self._init_session()
        if not params: params = {}

        if self.expires and datetime.now() > self.expires:
            try:
                await self.refresh()
            except:
                if self.email and self.password_cache:
                    await self.login(self.email, self.password_cache)
                else:
                    raise BeatportError("Sesi habis.")

        await asyncio.sleep(random.uniform(0.5, 1.5))

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.session.get(f'{self.API_URL}{endpoint}', params=params, headers=self._get_headers(True)) as r:
                    
                    if r.status == 200:
                        return await r.json()

                    if r.status in [500, 502, 503, 504]:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        raise ConnectionError(f"Server Error: {r.status}")

                    if r.status == 401:
                        raise BeatportError("Unauthorized (401)")
                    
                    if r.status == 403:
                        try:
                            err_data = await r.json()
                            msg = str(err_data).lower()
                            if "territory" in msg or "region" in msg:
                                raise BeatportError("Region Locked (Gunakan VPN/Proxy)")
                        except: pass
                        raise BeatportError(f"Forbidden (403): Akses ditolak.")
                    
                    if r.status == 404:
                        raise BeatportError(f"Not Found (404): {endpoint}")
                    
                    raise ConnectionError(f"API Error {r.status}")

            except aiohttp.ClientConnectorError:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                raise

    async def get_account(self): return await self._get('auth/o/introspect')
    async def get_track(self, track_id: str): return await self._get(f'catalog/tracks/{track_id}')
    async def get_release(self, release_id: str): return await self._get(f'catalog/releases/{release_id}')
    
    async def get_release_tracks(self, release_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/releases/{release_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_playlist(self, playlist_id: str): return await self._get(f'catalog/playlists/{playlist_id}')
    
    async def get_playlist_tracks(self, playlist_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/playlists/{playlist_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_chart(self, chart_id: str): return await self._get(f'catalog/charts/{chart_id}')
    
    async def get_chart_tracks(self, chart_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/charts/{chart_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_artist(self, artist_id: str): return await self._get(f'catalog/artists/{artist_id}')

    async def get_artist_releases(self, artist_id: str, page: int = 1, per_page: int = 100):
        # Menggunakan endpoint releases dengan filter artist_id
        return await self._get('catalog/releases/', params={'artist_id': artist_id, 'page': page, 'per_page': per_page})
    
    async def get_artist_tracks(self, artist_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/artists/{artist_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_track_download(self, track_id: str, quality: str):
        return await self._get(f'catalog/tracks/{track_id}/download', params={'quality': quality})
