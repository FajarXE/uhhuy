# [GANTI SELURUH FILE: bot/helpers/lyrics/apis.py]

import re
import aiohttp
import asyncio
import logging
import aiolimiter
from datetime import datetime

LOGGER = logging.getLogger(__name__)

# --- KONTROL RATE LIMIT (ANTI-BAN LYRICS API) ---
MX_LIMITER = aiolimiter.AsyncLimiter(10, 5)
LRC_LIMITER = aiolimiter.AsyncLimiter(10, 5)
GENIUS_LIMITER = aiolimiter.AsyncLimiter(2, 3) 

# --- [PERBAIKAN 1: KONEKSI GLOBAL] ---
# Mencegah Socket Exhaustion (Koneksi ditolak) saat mendownload album berisi puluhan lagu
_HTTP_SESSION = None

async def get_http_session():
    global _HTTP_SESSION
    if _HTTP_SESSION is None or _HTTP_SESSION.closed:
        connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
        _HTTP_SESSION = aiohttp.ClientSession(connector=connector)
    return _HTTP_SESSION
# -------------------------------------

# =======================================================
# FUNGSI VALIDASI CERDAS UNTUK LRCLIB & GENIUS
# =======================================================
def clean_string(text):
    if not text: return ""
    text = str(text)
    text = re.sub(r'\([^)]*\)|\[[^\]]*\]', '', text)
    text = re.sub(r'(?i)\b(feat\.?|ft\.?|with|remastered|remaster|version|explicit|live|bonus|instrumental)\b.*', '', text)
    text = re.sub(r'[^a-zA-Z0-9]', '', text)
    return text.lower()

def is_valid_match(t1, t2, a1=None, a2=None):
    ct1 = clean_string(t1)
    ct2 = clean_string(t2)
    if not ct1 or not ct2: return False
    
    if len(ct1) < 3 or len(ct2) < 3: title_match = (ct1 == ct2)
    else: title_match = (ct1 in ct2 or ct2 in ct1)
        
    if not title_match: return False
    if a1 and a2:
        ca1 = clean_string(a1)
        ca2 = clean_string(a2)
        if ca1 and ca2:
            return (ca1 in ca2 or ca2 in ca1)
    return True
# =======================================================


class MusixmatchAPI:
    def __init__(self):
        self.API_URL = "https://apic-appmobile.musixmatch.com/ws/1.1/"
        self.headers = {
            "Host": "apic-appmobile.musixmatch.com",
            "authority": "apic-appmobile.musixmatch.com",
            "X-Cookie": "x-mxm-token-guid=",
            "x-mxm-app-version": "10.1.1",
            "X-User-Agent": "Musixmatch/2025120901 CFNetwork/3860.300.31 Darwin/25.2.0",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Accept": "application/json"
        }
        self.token = None
        self._token_lock = asyncio.Lock()

    async def get_token(self, old_token=None):
        # [PERBAIKAN 2: ANTI RACE-CONDITION TOKEN]
        # Jika ada puluhan lagu yang meminta token secara serentak, 
        # mereka akan tertahan di sini dan menggunakan 1 token yang sama secara rukun.
        async with self._token_lock:
            # Jika token sudah berhasil diperbarui oleh lagu sebelumnya, gunakan token itu!
            if self.token and self.token != old_token:
                return self.token
                
            session = await get_http_session()
            try:
                params = {"app_id": "mac-ios-v2.0"}
                async with session.get(self.API_URL + "token.get", params=params, headers=self.headers, timeout=15) as r:
                    data = await r.json(content_type=None)
                    if data.get('message', {}).get('header', {}).get('status_code') == 200:
                        tkn = data['message']['body']['user_token']
                        if tkn and tkn != 'UpgradeOnlyUpgradeOnlyUpgradeOnlyUpgradeOnly':
                            self.token = tkn
                            LOGGER.info("Musixmatch: Token baru berhasil dicetak.")
                            return self.token
            except Exception as e:
                LOGGER.error(f"Musixmatch Token Error: {e}")
            return None

    async def get_lyrics(self, title, artist, album, duration=None):
        session = await get_http_session()
        
        if not self.token:
            await self.get_token()

        if not self.token:
            return None, None

        plain = None
        synced = None

        # Beri kesempatan 3 kali percobaan untuk setiap lagu jika gagal di tengah jalan
        for attempt in range(3):
            params = {
                "format": "json",
                "namespace": "lyrics_richsynched",
                "subtitle_format": "lrc",
                "app_id": "mac-ios-v2.0",
                "q_artist": artist or "",
                "q_track": title or "",
                "usertoken": self.token
            }
            if album:
                params["q_album"] = album

            try:
                async with MX_LIMITER:
                    async with session.get(self.API_URL + "macro.subtitles.get", params=params, headers=self.headers, timeout=15) as r:
                        data = await r.json(content_type=None)
                        
                        # [PERBAIKAN 3: KEAMANAN STRUKTUR DATA]
                        msg = data.get("message", {})
                        if not isinstance(msg, dict): msg = {}
                        
                        body = msg.get("body", {})
                        if not isinstance(body, dict): body = {}
                        
                        macro_calls = body.get("macro_calls", {})
                        if not isinstance(macro_calls, dict): macro_calls = {}

                        lyrics_get = macro_calls.get("track.lyrics.get", {})
                        if isinstance(lyrics_get, dict):
                            l_header = lyrics_get.get("message", {}).get("header", {})
                            status_code = l_header.get("status_code")
                            
                            if status_code == 401:
                                LOGGER.warning(f"Musixmatch: Token Expired (401) pada lagu '{title}'. Antre perbarui token...")
                                # Minta token baru dan berikan token saat ini sebagai referensi usang
                                await self.get_token(old_token=self.token)
                                continue # Ulangi percobaan dengan token baru

                            if status_code == 200:
                                lyrics_body = lyrics_get.get("message", {}).get("body", {}).get("lyrics", {})
                                if lyrics_body.get("restricted"):
                                    pass
                                elif lyrics_body.get("instrumental"):
                                    plain = "This song is instrumental.\nLet the music play..."
                                else:
                                    plain = lyrics_body.get("lyrics_body")

                                subs_get = macro_calls.get("track.subtitles.get", {})
                                if isinstance(subs_get, dict):
                                    subs_msg = subs_get.get("message", {})
                                    subs_header = subs_msg.get("header", {})
                                    
                                    if subs_header.get("status_code") == 200 and subs_header.get("available") == 1:
                                        sub_list = subs_msg.get("body", {}).get("subtitle_list", [])
                                        if sub_list and isinstance(sub_list, list):
                                            synced = sub_list[0].get("subtitle", {}).get("subtitle_body")
                                            
                                return plain, synced
                                
                    # Jika proses berjalan lancar dan tidak ada error 401, keluar dari loop retry
                    break 
                    
            except Exception as e:
                LOGGER.warning(f"Musixmatch Retry {attempt+1}/3 pada lagu '{title}' karena: {e}")
                await asyncio.sleep(1)

        return None, None


class LRCLibAPI:
    def __init__(self):
        self.base_url = 'https://lrclib.net/api'
        self.headers = {'User-Agent': 'BotMusic/1.0'}

    async def _fetch_with_retry(self, url, params):
        session = await get_http_session()
        for attempt in range(3): 
            try:
                async with LRC_LIMITER:
                    async with session.get(url, params=params, headers=self.headers, timeout=15) as r:
                        if r.status == 200:
                            return await r.json(content_type=None)
                        elif r.status in (429, 503):
                            retry_after = int(r.headers.get('Retry-After', 5))
                            LOGGER.warning(f"LRCLib Rate Limit {r.status}. Retrying in {retry_after}s...")
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            return None
            except Exception as e:
                LOGGER.debug(f"LRCLib Fetch Error: {e}")
                await asyncio.sleep(2)
        return None

    async def get_lyrics(self, title, artist, album, duration):
        params = {'track_name': title, 'artist_name': artist, 'album_name': album, 'duration': duration}
        data = await self._fetch_with_retry(f'{self.base_url}/get', params)
        if data:
            return data.get('plainLyrics'), data.get('syncedLyrics')
        
        params_search = {'q': f"{title} {artist}"}
        data = await self._fetch_with_retry(f'{self.base_url}/search', params_search)
        if data and isinstance(data, list) and len(data) > 0:
            for item in data:
                res_title = item.get('trackName', '')
                res_artist = item.get('artistName', '')
                
                if is_valid_match(title, res_title, artist, res_artist):
                    return item.get('plainLyrics'), item.get('syncedLyrics')
        
        return None, None


class GeniusAPI:
    def __init__(self):
        self.API_URL = "https://api.genius.com/"
        self.access_token = 'ZTejoT_ojOEasIkT9WrMBhBQOz6eYKK5QULCMECmOhvwqjRZ6WbpamFe3geHnvp3'
        self.headers = {
            'x-genius-app-background-request': '0',
            'user-agent': 'okhttp/4.9.1',
            'authorization': f'Bearer {self.access_token}',
            'x-genius-logged-out': 'true',
            'x-genius-android-version': '5.8.0'
        }

    async def _fetch_with_retry(self, url, params):
        session = await get_http_session()
        for attempt in range(4): 
            try:
                async with GENIUS_LIMITER:
                    async with session.get(url, params=params, headers=self.headers, timeout=15) as r:
                        if r.status == 200:
                            return await r.json(content_type=None)
                        else:
                            # [PERBAIKAN 4: RETRY SEMUA ERROR GENIUS]
                            # Tidak peduli apakah itu 401, 403, 429, atau 500, bot akan selalu mengulang
                            # Ini menjamin file lirik .txt terbuat meskipun API Genius sedang tersendat
                            retry_after = int(r.headers.get('Retry-After', 2)) + (attempt * 2)
                            LOGGER.warning(f"Genius API HTTP [{r.status}]. Menunggu {retry_after}s untuk mengulang...")
                            await asyncio.sleep(retry_after)
                            continue
            except Exception as e:
                await asyncio.sleep(2)
        return None

    async def get_lyrics(self, title, artist, album, duration):
        track_id = None
        search_query = f"{artist} {title}"
        
        data = await self._fetch_with_retry(f'{self.API_URL}search', {'q': search_query})
        
        if data:
            hits = data.get('response', {}).get('hits', [])
            if hits:
                for hit in hits:
                    result = hit.get('result', {})
                    res_title = result.get('title', '')
                    res_title_feat = result.get('title_with_featured', '')
                    res_artist = result.get('artist_names', '')
                    
                    if is_valid_match(title, res_title, artist, res_artist) or \
                       is_valid_match(title, res_title_feat, artist, res_artist):
                        track_id = result.get('id')
                        break
                        
        if not track_id:
            return None, None
            
        song_data = await self._fetch_with_retry(f'{self.API_URL}songs/{track_id}', {'text_format': 'plain'})
        if song_data:
            plain_lyrics = song_data.get('response', {}).get('song', {}).get('lyrics', {}).get('plain')
            return plain_lyrics, None 
            
        return None, None
