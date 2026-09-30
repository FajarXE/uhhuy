# [GANTI SELURUH FILE: bot/helpers/lyrics/apis.py]

import re
import aiohttp
import asyncio
import logging
import aiolimiter
from datetime import datetime

LOGGER = logging.getLogger(__name__)

# --- KONTROL RATE LIMIT (ANTI-BAN LYRICS API) ---
MX_LIMITER = aiolimiter.AsyncLimiter(5, 5)
LRC_LIMITER = aiolimiter.AsyncLimiter(5, 5)
GENIUS_LIMITER = aiolimiter.AsyncLimiter(5, 5) 
# ------------------------------------------------

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
        self.cookies = {'AWSELB': '0', 'AWSELBCORS': '0'}
        self.token = None

    async def _fetch_with_retry(self, session, endpoint, params):
        # --- [PENGAMAN UTAMA] Mencegah aiohttp crash karena value 'None' ---
        clean_params = {k: v for k, v in params.items() if v is not None}
        
        for attempt in range(4):
            try:
                async with MX_LIMITER:
                    async with session.get(self.API_URL + endpoint, params=clean_params, headers=self.headers, cookies=self.cookies, timeout=15) as r:
                        if r.status == 200:
                            return await r.json(content_type=None)
                        elif r.status in (429, 503):
                            retry_after = int(r.headers.get('Retry-After', 5))
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            return None
            except Exception as e:
                LOGGER.debug(f"MX Error Fetch: {e}")
                await asyncio.sleep(2)
        return None

    async def get_token(self, session):
        params = {"app_id": "mac-ios-v2.0"}
        data = await self._fetch_with_retry(session, "token.get", params)
        if data and data.get('message', {}).get('header', {}).get('status_code') == 200:
            token = data['message']['body']['user_token']
            if token != 'UpgradeOnlyUpgradeOnlyUpgradeOnlyUpgradeOnly':
                self.token = token
                return self.token
        return None

    async def get_lyrics(self, title, artist, album, duration=None):
        async with aiohttp.ClientSession(cookies=self.cookies) as session:
            if not self.token:
                await self.get_token(session)

            plain = None
            synced = None
            params = {
                "format": "json",
                "namespace": "lyrics_richsynched",
                "subtitle_format": "lrc",
                "app_id": "mac-ios-v2.0",
                "q_artist": artist or "",  # Fallback string kosong jika None
                "q_track": title or "",
                "usertoken": self.token or ""
            }
            if album: params["q_album"] = album

            data = await self._fetch_with_retry(session, "macro.subtitles.get", params)
            if data:
                macro_calls = data.get("message", {}).get("body", {}).get("macro_calls", {})
                
                lyrics_get = macro_calls.get("track.lyrics.get", {}).get("message", {})
                if lyrics_get.get("header", {}).get("status_code") == 200:
                    lyrics_body = lyrics_get.get("body", {}).get("lyrics", {})
                    if lyrics_body.get("instrumental"):
                        plain = "This song is instrumental.\nLet the music play..."
                    elif not lyrics_body.get("restricted"):
                        plain = lyrics_body.get("lyrics_body")

                subs_get = macro_calls.get("track.subtitles.get", {}).get("message", {})
                if subs_get.get("header", {}).get("status_code") == 200:
                    sub_list = subs_get.get("body", {}).get("subtitle_list", [])
                    if sub_list:
                        synced = sub_list[0].get("subtitle", {}).get("subtitle_body")

            return plain, synced


class LRCLibAPI:
    def __init__(self):
        self.base_url = 'https://lrclib.net/api'
        self.headers = {'User-Agent': 'BotMusic/1.0'}

    async def _fetch_with_retry(self, session, url, params):
        # --- [PENGAMAN UTAMA] Mencegah aiohttp crash karena value 'None' ---
        clean_params = {k: v for k, v in params.items() if v is not None}
        
        for attempt in range(4): 
            try:
                async with LRC_LIMITER:
                    async with session.get(url, params=clean_params, headers=self.headers, timeout=15) as r:
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
                LOGGER.debug(f"LRCLib Error Fetch: {e}")
                await asyncio.sleep(2)
        return None

    async def get_lyrics(self, title, artist, album, duration):
        async with aiohttp.ClientSession() as session:
            params = {'track_name': title or "", 'artist_name': artist or "", 'album_name': album or "", 'duration': duration}
            data = await self._fetch_with_retry(session, f'{self.base_url}/get', params)
            if data:
                return data.get('plainLyrics'), data.get('syncedLyrics')
            
            params_search = {'q': f"{title or ''} {artist or ''}".strip()}
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

    async def _fetch_with_retry(self, session, endpoint, params):
        # --- [PENGAMAN UTAMA] Mencegah aiohttp crash karena value 'None' ---
        clean_params = {k: v for k, v in params.items() if v is not None}
        
        for attempt in range(4): 
            try:
                async with GENIUS_LIMITER:
                    async with session.get(self.API_URL + endpoint, params=clean_params, headers=self.headers, timeout=15) as r:
                        if r.status == 200:
                            return await r.json(content_type=None)
                        elif r.status in (429, 503):
                            retry_after = int(r.headers.get('Retry-After', 5))
                            LOGGER.warning(f"Genius Rate Limit {r.status}. Retrying in {retry_after}s...")
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            return None
            except Exception as e:
                LOGGER.debug(f"Genius Error Fetch: {e}")
                await asyncio.sleep(2)
        return None

    async def get_lyrics(self, title, artist, album, duration):
        async with aiohttp.ClientSession() as session:
            track_id = None
            search_query = f"{artist or ''} {title or ''}".strip()
            
            data = await self._fetch_with_retry(session, 'search', {'q': search_query})
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
                
            song_data = await self._fetch_with_retry(session, f'songs/{track_id}', {'text_format': 'plain'})
            if song_data:
                lyrics_obj = song_data.get('response', {}).get('song', {}).get('lyrics')
                if isinstance(lyrics_obj, dict):
                    return lyrics_obj.get('plain'), None 
            
            return None, None
