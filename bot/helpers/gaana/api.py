# [GANTI SELURUH FILE: bot/helpers/gaana/api.py]

import aiohttp
import base64
import aiolimiter
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

# --- KONTROL RATE LIMIT (ANTI-BAN GAANA) ---
# Membatasi maksimal 15 request dalam 5 detik
GAANA_LIMITER = aiolimiter.AsyncLimiter(15, 5)
# -------------------------------------------

class GaanaAPI:
    def __init__(self):
        self.api_url = "https://gaana.com/apiv2"
        # Meniru header dari referensi gaana.py
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Origin': 'https://gaana.com',
            'Referer': 'https://gaana.com/'
        }
        
    def decrypt_stream_path(self, encrypted_path: str) -> str:
        # Logika dekripsi persis dari gaana.py
        try:
            AES_KEY = b"".join(w.to_bytes(4, byteorder="big", signed=True)
                               for w in [1735995764, 593641578, 1814585892, 2004118885])
            offset = int(encrypted_path[0])
            iv = encrypted_path[offset: offset + 16].encode("utf-8")
            ciphertext = base64.b64decode(encrypted_path[offset + 16:])
            cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
            return unpad(cipher.decrypt(ciphertext), AES.block_size).decode("utf-8")
        except Exception as e:
            raise Exception(f"Gagal dekripsi URL Gaana: {e}")

    async def get_metadata(self, session: aiohttp.ClientSession, identifier: str, meta_type: str):
        params = {
            'seokey': identifier,
            'type': meta_type,
        }
        # --- BUNGKUS DENGAN LIMITER ---
        async with GAANA_LIMITER:
            async with session.post(self.api_url, params=params, headers=self.headers) as resp:
                return await resp.json()
