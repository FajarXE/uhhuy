import aiohttp
import asyncio
import json
from bs4 import BeautifulSoup
from bot.logger import LOGGER

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.warning("Modul 'aiohttp_socks' tidak ditemukan. Proxy SOCKS/SOCKS5H tidak akan berjalan.")
    ProxyConnector = None

class HighResAudioApi:
    
    def __init__(self, exception, proxy: str = None):
        self.API_URL = 'https://streaming.highresaudio.com:8182/vault3/'
        self.STORE_URL = 'https://www.highresaudio.com/'
        
        self.exception = exception
        self.proxy = proxy
        self.session = None
        
        self.user_data_string = None 
        self.username = None 
        self.password = None

    async def _init_session(self):
        if self.session is None or self.session.closed:
            connector = None
            if self.proxy:
                if ProxyConnector and self.proxy.startswith('socks'):
                    try:
                        safe_proxy = self.proxy.replace("socks5h://", "socks5://").replace("socks4a://", "socks4://")
                        connector = ProxyConnector.from_url(safe_proxy)
                    except Exception as e:
                        LOGGER.error(f"HighResAudio: Gagal setup Proxy SOCKS: {e}")

            self.session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
                },
                connector=connector
            )

    async def _request(self, method: str, url: str, **kwargs):
        await self._init_session()
        
        # Setup HTTP proxy jika bukan SOCKS
        if self.proxy and not self.proxy.startswith('socks'):
            kwargs['proxy'] = self.proxy

        max_retries = 4
        for attempt in range(max_retries):
            try:
                async with self.session.request(method, url, **kwargs) as r:
                    r.raise_for_status()
                    text = await r.text()
                    
                    try:
                        data = json.loads(text)
                        return r.status, text, data
                    except:
                        return r.status, text, None
                        
            except aiohttp.ClientResponseError as e:
                if e.status in [500, 502, 503, 504] and attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                raise self.exception(f"HTTP Error {e.status}: {e.message}")
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                raise self.exception(f"Koneksi Gagal: {e}")

    async def auth(self, username: str, password: str) -> dict:
        LOGGER.info(f"HighResAudio: Mencoba login untuk {username} (Proxy: {'Ya' if self.proxy else 'Tidak'})...")
        
        self.username = username
        self.password = password

        status, text, data = await self._request('GET', f'{self.API_URL}user/login', params={
            'password': password,
            'username': username
        }, timeout=aiohttp.ClientTimeout(total=30))

        if not data:
            raise self.exception("Respons login bukan JSON valid.")

        if "has_subscription" not in data:
            raise self.exception('Akun tidak memiliki langganan aktif.')
        
        self.user_data_string = text
        LOGGER.info(f"HighResAudio: Login berhasil untuk {username}.")
        return data

    async def re_login(self):
        if self.username and self.password:
            LOGGER.info(f"HighResAudio: Menyegarkan sesi (Re-Login) otomatis untuk {self.username}...")
            return await self.auth(self.username, self.password)
        else:
            LOGGER.warning("HighResAudio: Gagal melakukan re-login, kredensial tidak ditemukan di memori.")

    async def get_album_id_from_url(self, url: str) -> str:
        status, text, data = await self._request('GET', url, timeout=aiohttp.ClientTimeout(total=30))
        
        soup = BeautifulSoup(text, "html.parser")
        element = soup.find(attrs={"data-id": True})
        
        if not element or not element.get('data-id'):
            raise self.exception('Gagal menemukan data-id dari halaman HTML.')
            
        return element['data-id']

    async def get_album_metadata(self, album_id: str) -> dict:
        if not self.user_data_string:
            if self.username and self.password:
                await self.re_login()
            else:
                raise self.exception("Klien tidak login (user_data tidak ada).")
            
        status, text, data = await self._request('GET', f'{self.API_URL}vault/album/', params={
            'album_id': album_id,
            'userData': self.user_data_string 
        }, timeout=aiohttp.ClientTimeout(total=30))
        
        if not data:
            raise self.exception("Respons metadata bukan JSON valid.")
                
        return data

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
