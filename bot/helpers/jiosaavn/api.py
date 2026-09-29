# [GANTI SELURUH FILE: bot/helpers/jiosaavn/api.py]

import aiohttp
import json
import aiolimiter

# --- KONTROL RATE LIMIT (ANTI-BAN JIOSAAVN) ---
# Membatasi maksimal 15 request dalam 5 detik
JIOSAAVN_LIMITER = aiolimiter.AsyncLimiter(15, 5)
# ----------------------------------------------

class JioSaavnAPI:
    def __init__(self):
        self.base_url = "https://www.jiosaavn.com/api.php"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    async def _get(self, session, params):
        # --- BUNGKUS DENGAN LIMITER ---
        async with JIOSAAVN_LIMITER:
            async with session.get(self.base_url, params=params, headers=self.headers) as resp:
                try:
                    text = await resp.text()
                    # API kadang mengembalikan komentar JSON, kita bersihkan
                    return json.loads(text.split('-->')[-1] if '-->' in text else text)
                except:
                    return None

    async def get_song_details(self, session: aiohttp.ClientSession, token: str):
        data = await self._get(session, {
            '__call': 'webapi.get', 'token': token, 'type': 'song', '_format': 'json', 'ctx': 'web6dot0'
        })
        if data and "songs" in data and data["songs"]: return data["songs"][0]
        if isinstance(data, dict) and len(data) > 0:
            key = list(data.keys())[0]
            if isinstance(data[key], dict): return data[key]
        return None

    async def get_album_details(self, session: aiohttp.ClientSession, token: str):
        return await self._get(session, {
            '__call': 'webapi.get', 'token': token, 'type': 'album', '_format': 'json', 'ctx': 'web6dot0'
        })

    # --- PERBAIKAN: Tambah n=1000 agar full track ---
    async def get_playlist_details(self, session: aiohttp.ClientSession, token: str):
        return await self._get(session, {
            '__call': 'webapi.get', 
            'token': token, 
            'type': 'playlist', 
            'n': '1000', # Limit lagu
            'p': '1',    # Page 1
            '_format': 'json', 
            'ctx': 'web6dot0'
        })
    # ------------------------------------------------

    async def get_lyrics(self, session: aiohttp.ClientSession, song_id: str):
        data = await self._get(session, {
            '__call': 'lyrics.getLyrics', 'lyrics_id': song_id, 'ctx': 'web6dot0', 'api_version': '4', '_format': 'json'
        })
        return data.get("lyrics") if data else None

    async def get_auth_url(self, session: aiohttp.ClientSession, encrypted_url: str):
        data = await self._get(session, {
            '__call': 'song.generateAuthToken',
            'url': encrypted_url,
            'bitrate': '320',
            'api_version': '4',
            '_format': 'json',
            'ctx': 'web6dot0',
            '_marker': '0',
        })
        
        if data and "auth_url" in data:
            url = data["auth_url"]
            if "web" in url: url = url.replace("web", "aac")
            if "preview" in url: url = url.replace("preview", "aac")
            
            if "_96_p.mp4" in url: url = url.replace("_96_p.mp4", "_320.mp4")
            if "_160_p.mp4" in url: url = url.replace("_160_p.mp4", "_320.mp4")
            if "_96.mp4" in url: url = url.replace("_96.mp4", "_320.mp4")
            
            return url
        return None
