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
GENIUS_LIMITER = aiolimiter.AsyncLimiter(10, 5) 
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

    async def get_token(self, session):
        async with self._token_lock:
            if self.token:
                return self.token
                
            try:
                params = {"app_id": "mac-ios-v2.0"}
                async with MX_LIMITER:
                    async with session.get(self.API_URL + "token.get", params=params, headers=self.headers, timeout=15) as r:
                        data = await r.json(content_type=None)
                        
                        # Validasi mendalam untuk Token
                        if isinstance(data, dict):
                            msg = data.get('message')
                            if isinstance(msg, dict):
                                header = msg.get('header', {})
                                if isinstance(header, dict) and header.get('status_code') == 200:
                                    body = msg.get('body', {})
                                    if isinstance(body, dict):
                                        token = body.get('user_token')
                                        if token and token != 'UpgradeOnlyUpgradeOnlyUpgradeOnlyUpgradeOnly':
                                            self.token = token
                                            LOGGER.info("Musixmatch: Token berhasil diperbarui.")
                                            return self.token
            except Exception as e:
                LOGGER.error(f"Musixmatch Token Error: {e}")
            return None

    async def get_lyrics(self, title, artist, album, duration=None):
        if not title or not artist:
            return None, None

        async with aiohttp.ClientSession() as session:
            if not self.token:
                await self.get_token(session)
                
            if not self.token:
                LOGGER.warning(f"Musixmatch: Lewati '{title}' karena gagal mendapatkan token.")
                return None, None

            plain = None
            synced = None

            params = {
                "format": "json",
                "namespace": "lyrics_richsynched",
                "subtitle_format": "lrc",
                "app_id": "mac-ios-v2.0",
                "q_artist": str(artist),
                "q_track": str(title),
                "usertoken": str(self.token)
            }
            if album:
                params["q_album"] = str(album)

            try:
                async with MX_LIMITER:
                    async with session.get(self.API_URL + "macro.subtitles.get", params=params, headers=self.headers, timeout=15) as r:
                        data = await r.json(content_type=None)
                        
                        # 0. Validasi Lapis demi Lapis untuk mencegah List Object Error
                        if not isinstance(data, dict): return None, None
                        
                        message = data.get("message")
                        if not isinstance(message, dict): return None, None
                        
                        body = message.get("body")
                        if not isinstance(body, dict): return None, None
                        
                        macro_calls = body.get("macro_calls")
                        if not isinstance(macro_calls, dict): return None, None
                        
                        # 1. Parsing Plain Lyrics secara aman
                        track_lyrics = macro_calls.get("track.lyrics.get")
                        if isinstance(track_lyrics, dict):
                            tl_msg = track_lyrics.get("message")
                            if isinstance(tl_msg, dict) and tl_msg.get("header", {}).get("status_code") == 200:
                                tl_body = tl_msg.get("body")
                                if isinstance(tl_body, dict):
                                    lyrics = tl_body.get("lyrics")
                                    if isinstance(lyrics, dict):
                                        if lyrics.get("restricted"):
                                            LOGGER.debug(f"Musixmatch: Lirik restricted untuk {title}")
                                        elif lyrics.get("instrumental"):
                                            plain = "This song is instrumental.\nLet the music play..."
                                        else:
                                            plain = lyrics.get("lyrics_body")

                        # 2. Parsing Synced LRC secara aman
                        track_subs = macro_calls.get("track.subtitles.get")
                        if isinstance(track_subs, dict):
                            ts_msg = track_subs.get("message")
                            if isinstance(ts_msg, dict) and ts_msg.get("header", {}).get("status_code") == 200:
                                ts_body = ts_msg.get("body")
                                if isinstance(ts_body, dict):
                                    sub_list = ts_body.get("subtitle_list")
                                    if isinstance(sub_list, list) and len(sub_list) > 0:
                                        first_sub = sub_list[0]
                                        if isinstance(first_sub, dict):
                                            subtitle = first_sub.get("subtitle")
                                            if isinstance(subtitle, dict):
                                                synced = subtitle.get("subtitle_body")
            except Exception as e:
                LOGGER.warning(f"Musixmatch Lyrics Error untuk '{title}': {e}")

            return plain, synced


class LRCLibAPI:
    def __init__(self):
        self.base_url = 'https://lrclib.net/api'
        # Menggunakan User-Agent yang lebih menyerupai browser/aplikasi asli seperti di referensi
        self.headers = {'User-Agent': 'BotMusic/1.0'}

    async def _fetch_with_retry(self, session, url, params):
        for attempt in range(3): 
            try:
                async with LRC_LIMITER:
                    async with session.get(url, params=params, headers=self.headers, timeout=15) as r:
                        if r.status == 200:
                            return await r.json(content_type=None)
                        elif r.status in (429, 503):
                            # [FIX] Aman dari error ValueError jika header Retry-After bukan angka
                            try:
                                retry_after = int(r.headers.get('Retry-After', 5))
                            except ValueError:
                                retry_after = 5
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
            # --- 1. [FIX] SUSUN PARAMETER SECARA DINAMIS (Seperti Referensi) ---
            params = {'track_name': title, 'artist_name': artist}
            
            # Hanya masukkan album jika string-nya tidak kosong
            if album:
                params['album_name'] = album
                
            # Hanya masukkan durasi jika lebih dari 0 detik (menghindari error default 0 dari manager)
            if duration and int(duration) > 0:
                params['duration'] = str(duration)

            # --- 2. COBA EXACT MATCH (/get) ---
            data = await self._fetch_with_retry(session, f'{self.base_url}/get', params)
            if data:
                return data.get('plainLyrics'), data.get('syncedLyrics')
            
            # --- 3. [FIX] COBA SEARCH FALLBACK (/search) ---
            # Jangan gunakan parameter 'q', gunakan parameter spesifik seperti referensi
            search_params = {'track_name': title, 'artist_name': artist}
            data_list = await self._fetch_with_retry(session, f'{self.base_url}/search', search_params)
            
            if data_list and isinstance(data_list, list) and len(data_list) > 0:
                for item in data_list:
                    res_title = item.get('trackName', '')
                    res_artist = item.get('artistName', '')
                    
                    # Tetap gunakan fungsi validasi Anda untuk memastikan kecocokan
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

    async def _fetch_with_retry(self, session, endpoint, params):
        # Mengadaptasi sistem HTTPAdapter max_retries=10 dari referensi
        for attempt in range(5):
            try:
                async with GENIUS_LIMITER:
                    async with session.get(f'{self.API_URL}{endpoint}', params=params, headers=self.headers, timeout=15) as r:
                        if r.status in [200, 201, 202]:
                            data = await r.json(content_type=None)
                            if data.get('meta', {}).get('status') == 200:
                                return data.get('response')
                            return None
                        
                        # Menangkap status forcelist (429, 500, 502, 503, 504) seperti referensi
                        elif r.status in [429, 500, 502, 503, 504]:
                            delay = 0.4 * (2 ** attempt) # Backoff factor
                            LOGGER.warning(f"Genius API {r.status}. Retrying in {delay}s...")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            return None
            except Exception as e:
                LOGGER.debug(f"Genius Fetch Error: {e}")
                await asyncio.sleep(0.4 * (2 ** attempt))
        return None

    async def get_lyrics(self, title, artist, album, duration):
        async with aiohttp.ClientSession() as session:
            track_id = None
            
            # 1. Search Track (Mengikuti kueri pencarian dari interface_2.py)
            search_query = f"{artist} {title}"
            response = await self._fetch_with_retry(session, 'search', {'q': search_query})
            
            if response and 'hits' in response:
                for hit in response['hits']:
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
                
            # 2. Get Lyrics (Mengikuti endpoint songs/{id} dari genius_api.py)
            song_data = await self._fetch_with_retry(session, f'songs/{track_id}', {'text_format': 'plain'})
            
            if song_data and 'song' in song_data:
                lyrics_data = song_data['song'].get('lyrics')
                if lyrics_data:
                    plain_lyrics = lyrics_data.get('plain')
                    return plain_lyrics, None
            
            return None, None
