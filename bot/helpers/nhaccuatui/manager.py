# [FILE BARU: bot/helpers/nhaccuatui/manager.py]

import asyncio
from playwright.async_api import async_playwright
from bot.logger import LOGGER

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.nhaccuatui.com/",
}

class NhacCuaTuiManager:
    def __init__(self):
        self.quality = "320"
        self.user_qual = {}
        self.clients = ["playwright_scraper"]
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def initialize_clients(self):
        """Inisialisasi manajer saat bot dinyalakan."""
        self.clients = ["playwright_scraper"]
        LOGGER.info("NhacCuaTui Manager: Siap (Lazy Playwright Browser).")

    async def get_browser(self):
        """Membuka atau menggunakan kembali instance Chromium headless."""
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                if self._pw is None:
                    self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
            return self._browser

    async def setup_quality(self, user_id: int, qual: str = None):
        if qual in ["128", "320"]:
            self.user_qual[user_id] = qual
        elif user_id not in self.user_qual:
            self.user_qual[user_id] = self.quality

    def get_user_quality(self, user_id: int) -> str:
        from bot.settings import bot_set
        user_dict = bot_set.user_data.get(user_id, {})
        return user_dict.get("nhaccuatui_qual") or self.user_qual.get(user_id) or self.quality

    async def shutdown(self):
        async with self._lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None
        LOGGER.info("NhacCuaTui Manager: Browser Playwright berhasil ditutup.")

nhaccuatui_manager = NhacCuaTuiManager()
