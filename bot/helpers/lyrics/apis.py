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
# Genius dibatasi menjadi 1 request per 1.5 detik agar aman saat download Album masif
GENIUS_LIMITER = aiolimiter.AsyncLimiter(1, 1.5) 
# ------------------------------------------------

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

    async def get_token(self, session, force_refresh=False):
        # [PERBAIKAN] Kunci sesi agar jika 23 lagu meminta token secara bersamaan,
        # hanya 1 lagu yang menghubungi server, sisanya akan memakai token yang sama.
        async with self._token_lock:
            if self.token and not force_refresh:
                return self.token
                
            try:
                params = {"app_id": "mac-ios-v2.0"}
                async with session.get(self.API_URL + "token.get", params=params, headers=self.headers, timeout=15) as r:
                    data = await r.json(content_type=None)
                    if data.get('message', {}).get('header', {}).get('status_code') == 200:
                        tkn = data['message']['body']['user_token']
                        if tkn and tkn != 'UpgradeOnlyUpgradeOnlyUpgradeOnlyUpgradeOnly':
                            self.token = tkn
                            LOGGER.info("Musixmatch: Token berhasil diperbarui.")
                            return self.token
            except Exception as e:
                LOGGER.error(f"Musixmatch Token Error: {e}")
            return None

    async def get_lyrics(self, title, artist, album, duration=None):
        async with aiohttp.ClientSession() as session:
            if not self.token:
                await self.get_token(session)

            if not self.token:
                return None, None

            plain = None
            synced = None

            # [PERBAIKAN] Auto-Retry jika terkena limit atau token invalid (Status 401)
            for attempt in range(2):
                # Validasi or "" untuk mencegah Error NoneType bawaan aiohttp
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
                            
                            # Ekstraksi aman untuk mencegah Error 'list' object has no attribute 'get'
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
                                
                                # [PERBAIKAN] Regenerasi Token jika Kadaluarsa (401) seperti di main.py
                                if status_code == 401:
                                    LOGGER.warning(f"Musixmatch: Token Invalid (401) pada lagu '{title}'. Meregenerasi token...")
                                    await self.get_token(session, force_refresh=True)
                                    continue # Ulangi pencarian dengan token baru!

                                if status_code == 200:
                                    # 1. Parsing Plain Lyrics
                                    lyrics_body = lyrics_get.get("message", {}).get("body", {}).get("lyrics", {})
                                    if lyrics_body.get("restricted"):
                                        pass
                                    elif lyrics_body.get("instrumental"):
                                        plain = "This song is instrumental.\nLet the music play..."
                                    else:
                                        plain = lyrics_body.get("lyrics_body")

                                    # 2. Parsing Synced LRC
                                    subs_get = macro_calls.get("track.subtitles.get", {})
                                    if isinstance(subs_get, dict):
                                        subs_msg = subs_get.get("message", {})
                                        subs_header = subs_msg.get("header", {})
                                        
                                        # Syarat "available" sesuai referensi main.py
                                        if subs_header.get("status_code") == 200 and subs_header.get("available") == 1:
                                            sub_list = subs_msg.get("body", {}).get("subtitle_list", [])
                                            if sub_list and isinstance(sub_list, list):
                                                synced = sub_list[0].get("subtitle", {}).get("subtitle_body")
                                                
                                    return plain, synced
                                    
                        break # Jika sukses dan bukan 401, keluar dari loop
                        
                except Exception as e:
                    LOGGER.warning(f"Musixmatch Lyrics Error: {e}")
                    break

            return None, None


class LRCLibAPI:
    def __init__(self):
        self.base_url = 'https://lrclib.net/api'
        self.headers = {'User-Agent': 'BotMusic/1.0'}

    async def _fetch_with_retry(self, session, url, params):
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
                        elif r.status == 404:
                            return None 
                        else:
                            return None
            except Exception as e:
                LOGGER.debug(f"LRCLib Fetch Error: {e}")
                return None
        return None

    async def get_lyrics(self, title, artist, album, duration):
        async with aiohttp.ClientSession() as session:
            # --- Try Cached (/get) ---
            params = {'track_name': title, 'artist_name': artist, 'album_name': album, 'duration': duration}
            data = await self._fetch_with_retry(session, f'{self.base_url}/get', params)
            if data:
                return data.get('plainLyrics'), data.get('syncedLyrics')
            
            # --- Try Search (/search) ---
            params_search = {'q': f"{title} {artist}"}
            data = await self._fetch_with_retry(session, f'{self.base_url}/search', params_search)
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

    # [PERBAIKAN] Mengamankan Rate Limit Genius dengan Exponential Backoff
    async def _fetch_with_retry(self, session, url, params):
        for attempt in range(4): 
            try:
                async with GENIUS_LIMITER:
                    async with session.get(url, params=params, headers=self.headers, timeout=15) as r:
                        if r.status == 200:
                            return await r.json(content_type=None)
                        elif r.status in (429, 503):
                            # Jika ditolak, mundurkan waktu tunggu progresif
                            retry_after = int(r.headers.get('Retry-After', 3)) + (attempt * 2)
                            LOGGER.warning(f"Genius Terkena Spam Limit ({r.status}). Menunggu {retry_after}s...")
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            return None
            except Exception as e:
                await asyncio.sleep(2)
        return None

    async def get_lyrics(self, title, artist, album, duration):
        async with aiohttp.ClientSession() as session:
            track_id = None
            search_query = f"{artist} {title}"
            
            data = await self._fetch_with_retry(session, f'{self.API_URL}search', {'q': search_query})
            
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
                
            song_data = await self._fetch_with_retry(session, f'{self.API_URL}songs/{track_id}', {'text_format': 'plain'})
            if song_data:
                plain_lyrics = song_data.get('response', {}).get('song', {}).get('lyrics', {}).get('plain')
                return plain_lyrics, None 
                
            return None, None
