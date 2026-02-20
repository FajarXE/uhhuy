import aiohttp
import asyncio
import random
from datetime import timedelta, datetime
from urllib.parse import urlparse, parse_qs
from bot.logger import LOGGER

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.warning("Modul 'aiohttp_socks' tidak ditemukan. Proxy SOCKS/SOCKS5H tidak akan berjalan.")
    ProxyConnector = None

# [KONFIGURASI USER-AGENT]
# 1. Browser: Digunakan saat Login & Refresh Token (Meniru aktivitas web)
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
# 2. App: Digunakan saat Download & API Call (Sesuai dengan Client ID Serato)
APP_USER_AGENT = "Serato DJ Lite/3.2.1 (Windows NT 10.0; Win64; x64)"

class BeatsourceError(Exception):
    def __init__(self, message):
        self.message = message
        super(BeatsourceError, self).__init__(message)

class BeatsourceAPI:
    def __init__(self):
        self.API_URL = "https://api.beatsource.com/v4/"
        # Client ID Serato DJ
        self.client_id = "ryZ8LuyQVPqbK2mBX2Hwt4qSMtnWuTYSqBPO92yQ"
        # [PENTING] Redirect URI wajib ada dan cocok dengan Client ID
        self.redirect_uri = "seratodjlite://beatsource"

        self.access_token = None
        self.refresh_token = None
        self.expires = None
        
        self.email = None
        self.password_cache = None
        self.proxy = None
        self.session = None 

    async def _init_session(self):
        """Inisialisasi sesi dengan identitas Browser."""
        if self.session is None or self.session.closed:
            connector = None
            if self.proxy and ProxyConnector:
                try:
                    proxy_url = self.proxy
                    use_rdns = False
                    if proxy_url.startswith("socks5h://"):
                        proxy_url = proxy_url.replace("socks5h://", "socks5://")
                        use_rdns = True
                    
                    connector = ProxyConnector.from_url(proxy_url, rdns=use_rdns)
                    LOGGER.debug(f"BeatsourceAPI: Menggunakan Proxy untuk {self.email}")
                except Exception as e:
                    LOGGER.error(f"BeatsourceAPI: Gagal Proxy: {e}")

            # Default menggunakan Browser UA untuk sesi dasar (Login/Cookies)
            self.session = aiohttp.ClientSession(
                headers={'User-Agent': BROWSER_USER_AGENT},
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                connector=connector
            )

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_headers(self, use_access_token: bool = False):
        """
        Logika Split Identity:
        - Jika akses API (use_access_token=True) -> Pakai APP_USER_AGENT
        - Jika browsing/login -> Pakai BROWSER_USER_AGENT
        """
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
        
        try:
            # 1. Login POST (Mendapatkan cookie sessionid)
            login_url = f"{self.API_URL}auth/login/"
            login_payload = {"username": email, "password": password}
            
            await asyncio.sleep(random.uniform(1.5, 2.5)) # Simulasi jeda manusia
            
            async with self.session.post(login_url, json=login_payload) as r_login:
                if r_login.status != 200:
                    try:
                        err = await r_login.json()
                        if "non_field_errors" in err:
                            raise BeatsourceError(f"Login gagal: {err['non_field_errors'][0]}")
                    except: pass
                    raise BeatsourceError(f"Login step 1 gagal: HTTP {r_login.status}")

            cookies = self.session.cookie_jar.filter_cookies(self.API_URL)
            if 'sessionid' not in cookies:
                raise BeatsourceError("Login gagal: Cookie sessionid tidak ditemukan.")

            # 2. Authorize GET (Mendapatkan Auth Code)
            auth_url = f"{self.API_URL}auth/o/authorize/"
            auth_params = {
                "client_id": self.client_id,
                "response_type": "code"
                # [PERBAIKAN] redirect_uri DIHAPUS, mengikuti logika OrpheusDL
            }
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            async with self.session.get(auth_url, params=auth_params, allow_redirects=False) as r_auth:
                if r_auth.status != 302:
                    error_text = await r_auth.text()
                    raise BeatsourceError(f"Auth step 2 gagal (No redirect): {r_auth.status}. Server: {error_text}")
                
                location = r_auth.headers.get('Location')
                if not location:
                    raise BeatsourceError("Auth step 2 gagal: Header Location hilang.")
                
                try:
                    parsed = urlparse(location)
                    code = parse_qs(parsed.query).get('code', [None])[0]
                except: code = None
                
                if not code:
                    raise BeatsourceError("Gagal mengambil auth code dari URL.")

            # 3. Token POST (Tukar Code dengan Token)
            token_url = f"{self.API_URL}auth/o/token/"
            token_payload = {
                "client_id": self.client_id,
                "code": code,
                "grant_type": "authorization_code"
                # [PERBAIKAN] redirect_uri DIHAPUS dari payload token
            }
            
            await asyncio.sleep(random.uniform(0.5, 1.0))
            
            async with self.session.post(token_url, data=token_payload) as r_token:
                if r_token.status != 200:
                    error_text = await r_token.text()
                    raise BeatsourceError(f"Token exchange gagal: HTTP {r_token.status}. Detail: {error_text}")
                
                js = await r_token.json()
                self.access_token = js['access_token']
                self.refresh_token = js['refresh_token']
                self.expires = datetime.now() + timedelta(seconds=js['expires_in'])
                LOGGER.info(f"Beatsource: Login berhasil untuk {email}")

        except Exception as e:
            await self.close_session()
            raise e

    async def refresh(self):
        await self._init_session()
        data = {
            'client_id': self.client_id,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
        }
        
        # Refresh biasanya butuh Content-Type form-urlencoded
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        async with self.session.post(f'{self.API_URL}auth/o/token/', data=data, headers=headers) as r:
            if r.status != 200:
                raise BeatsourceError("Gagal refresh token (Invalid Grant)")
            
            js = await r.json()
            self.access_token = js['access_token']
            self.refresh_token = js.get('refresh_token', self.refresh_token)
            self.expires = datetime.now() + timedelta(seconds=js['expires_in'])

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
                    raise BeatsourceError("Sesi habis, gagal login ulang.")

        # Delay keamanan
        await asyncio.sleep(random.uniform(0.5, 1.5))

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # _get_headers(True) akan menggunakan APP_USER_AGENT
                async with self.session.get(f'{self.API_URL}{endpoint}', params=params, headers=self._get_headers(True)) as r:
                    
                    if r.status == 200:
                        return await r.json()

                    if r.status in [500, 502, 503, 504]:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        raise ConnectionError(f"Server Error: {r.status}")
                    
                    if r.status == 401:
                        raise BeatsourceError("Unauthorized (401)")
                    
                    if r.status == 403:
                        try:
                            d = await r.json()
                            if "Territory" in str(d): raise BeatsourceError("Region Locked")
                        except: pass
                        raise BeatsourceError(f"Forbidden (403): {await r.text()}")
                    
                    if r.status == 404:
                        raise BeatsourceError(f"Not Found (404): {endpoint}")
                    
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

    async def get_track_download(self, track_id: str, quality: str):
        return await self._get(f'catalog/tracks/{track_id}/download', params={'quality': quality})
