# [BUAT FILE BARU: bot/helpers/proxy_manager.py]

import asyncio
import random
from bot.logger import LOGGER

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    ProxyConnector = None

class ProxyPoolManager:
    def __init__(self):
        self.proxies = {}
        self._lock = asyncio.Lock()
        
    async def add_proxy(self, proxy_url):
        if not proxy_url: return
        async with self._lock:
            if proxy_url not in self.proxies:
                self.proxies[proxy_url] = {"fails": 0, "active": True}
                LOGGER.info(f"Proxy Pool: Proksi ditambahkan -> {proxy_url}")

    async def get_proxy(self, specific_proxy=None):
        """Mengambil proksi spesifik (jika diminta) atau auto-round-robin dari pool."""
        if specific_proxy:
            await self.add_proxy(specific_proxy)
            return specific_proxy
            
        async with self._lock:
            active_proxies = [url for url, data in self.proxies.items() if data["active"]]
            if not active_proxies:
                return None
            
            # Urutkan berdasarkan jumlah kegagalan terkecil
            active_proxies.sort(key=lambda x: self.proxies[x]["fails"])
            
            # Pilih secara acak dari 3 proksi terbaik untuk Load Balancing
            return random.choice(active_proxies[:3])

    async def report_fail(self, proxy_url):
        """Mencatat kegagalan. Jika gagal 3x, proksi dibekukan sementara."""
        if not proxy_url: return
        async with self._lock:
            if proxy_url in self.proxies:
                self.proxies[proxy_url]["fails"] += 1
                if self.proxies[proxy_url]["fails"] >= 3:
                    self.proxies[proxy_url]["active"] = False
                    LOGGER.warning(f"Proxy Pool: Proksi dibekukan (Mati) -> {proxy_url}")

    async def report_success(self, proxy_url):
        """Mereset hitungan kegagalan jika proksi berhasil digunakan."""
        if not proxy_url: return
        async with self._lock:
            if proxy_url in self.proxies:
                self.proxies[proxy_url]["fails"] = 0
                self.proxies[proxy_url]["active"] = True

    def format_for_aria2(self, proxy_url):
        """Sanitasi skema proksi khusus untuk kompatibilitas daemon Aria2c."""
        if not proxy_url: return None
        if proxy_url.startswith("socks5h://"):
            return proxy_url.replace("socks5h://", "socks5://", 1)
        elif proxy_url.startswith("socks4a://"):
            return proxy_url.replace("socks4a://", "socks4://", 1)
        return proxy_url

    def get_aiohttp_connector(self, proxy_url):
        """Membangun objek ProxyConnector siap pakai untuk aiohttp."""
        if not proxy_url or not ProxyConnector:
            return None
            
        if proxy_url.startswith('socks'):
            safe_proxy = proxy_url.replace('socks5h://', 'socks5://').replace('socks4a://', 'socks4://')
            try:
                return ProxyConnector.from_url(safe_proxy)
            except Exception as e:
                LOGGER.error(f"Proxy Pool: Gagal mem-parsing aiohttp-socks -> {e}")
                return None
        return None

# Singleton instance
proxy_manager = ProxyPoolManager()
