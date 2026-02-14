# [GANTI SELURUH FILE: bot/helpers/highresaudio/api.py]

import requests
import json
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bot.logger import LOGGER

class HighResAudioApi:
    
    def __init__(self, exception, proxy: str = None):
        self.API_URL = 'https://streaming.highresaudio.com:8182/vault3/'
        self.STORE_URL = 'https://www.highresaudio.com/'
        self.STREAM_REFERER_URL = 'https://stream-app.highresaudio.com/album/'
        
        self.exception = exception
        self.proxy = proxy
        self.s = requests.Session()
        
        # --- KONFIGURASI PROXY ---
        if self.proxy:
            self.s.proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
        # -------------------------
        
        # --- Strategi Retry Otomatis ---
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)
        
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        })
        
        self.user_data_string = None 
        # Variable untuk menyimpan kredensial agar bisa re-login
        self.username = None 
        self.password = None

    def auth(self, username: str, password: str) -> dict:
        LOGGER.info(f"HighResAudio: Mencoba login untuk {username} (Proxy: {'Ya' if self.proxy else 'Tidak'})...")
        
        # Simpan kredensial di memory untuk keperluan auto-relogin nanti
        self.username = username
        self.password = password

        try:
            r = self.s.get(f'{self.API_URL}user/login', params={
                'password': password,
                'username': username
            }, timeout=30)

            r.raise_for_status()
            data = r.json()

            if "has_subscription" not in data:
                raise self.exception('Akun tidak memiliki langganan aktif.')
            
            self.user_data_string = r.text
            
            LOGGER.info(f"HighResAudio: Login berhasil untuk {username}.")
            return data

        except requests.exceptions.RequestException as e:
            LOGGER.error(f"HighResAudio: Gagal login ({username}): {e}")
            raise self.exception(f"Gagal login HighResAudio: {e}")
        except Exception as e:
            LOGGER.error(f"HighResAudio: Error saat login: {e}")
            raise self.exception(f"Error login HighResAudio: {e}")

    def re_login(self):
        """
        Fungsi untuk memaksa login ulang menggunakan kredensial yang tersimpan.
        Dipanggil saat sesi dianggap kedaluwarsa atau sebelum memulai unduhan baru.
        """
        if self.username and self.password:
            LOGGER.info(f"HighResAudio: Menyegarkan sesi (Re-Login) otomatis untuk {self.username}...")
            return self.auth(self.username, self.password)
        else:
            LOGGER.warning("HighResAudio: Gagal melakukan re-login, kredensial tidak ditemukan di memori.")

    def get_album_id_from_url(self, url: str) -> str:
        try:
            r = self.s.get(url, timeout=30)
            r.raise_for_status()
            
            soup = BeautifulSoup(r.text, "html.parser")
            element = soup.find(attrs={"data-id": True})
            
            if not element or not element.get('data-id'):
                raise self.exception('Gagal menemukan data-id dari halaman HTML.')
                
            return element['data-id']
            
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal scraping album ID: {e}")
            raise self.exception(f'Gagal scraping ID album dari URL: {e}')

    def get_album_metadata(self, album_id: str) -> dict:
        if not self.user_data_string:
            # Coba re-login jika data user kosong
            if self.username and self.password:
                self.re_login()
            else:
                raise self.exception("Klien tidak login (user_data tidak ada).")
            
        try:
            r = self.s.get(f'{self.API_URL}vault/album/', params={
                'album_id': album_id,
                'userData': self.user_data_string 
            }, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal mengambil metadata album: {e}")
            raise self.exception(f'Gagal mengambil metadata album: {e}')

    def get_track_stream(self, url: str, album_id_referer: str) -> requests.Response:
        headers = {
            "range": "bytes=0-",
            "referer": f"{self.STREAM_REFERER_URL}{album_id_referer}",
            "Connection": "close"
        }
        
        try:
            # Timeout dinaikkan
            r = self.s.get(url, headers=headers, stream=True, timeout=30)
            r.raise_for_status()
            return r
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal memulai stream lagu: {e}")
            raise self.exception(f'Gagal memulai stream lagu: {e}')
            
    def get_booklet_stream(self, url: str) -> requests.Response:
        try:
            headers = {"Connection": "close"}
            r = self.s.get(url, headers=headers, stream=True, timeout=30)
            r.raise_for_status()
            return r
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal memulai stream booklet: {e}")
            raise self.exception(f'Gagal memulai stream booklet: {e}')

    def close_session(self):
        if self.s:
            self.s.close()
