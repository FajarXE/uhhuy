# [GANTI SELURUH FILE: bot/helpers/lyrics/apis.py]

import re
import aiohttp
import asyncio
import time
import uuid
import hmac
import base64
import logging
import aiolimiter
from urllib.parse import urlencode
from datetime import datetime

LOGGER = logging.getLogger(__name__)

# --- KONTROL RATE LIMIT (ANTI-BAN LYRICS API) ---
MX_LIMITER = aiolimiter.AsyncLimiter(10, 5)
LRC_LIMITER = aiolimiter.AsyncLimiter(10, 5)
GENIUS_LIMITER = aiolimiter.AsyncLimiter(10, 5) 
# ------------------------------------------------

# =======================================================
# FUNGSI VALIDASI CERDAS (MENCEGAH SALAH LIRIK / LIRIK KOSONG)
# =======================================================
def clean_string(text):
    if not text: return ""
    text = str(text)
    # Hapus bagian dalam kurung ( ) atau [ ]
    text = re.sub(r'\([^)]*\)|\[[^\]]*\]', '', text)
    # Hapus atribut berlebihan di akhir judul
    text = re.sub(r'(?i)\b(feat\.?|ft\.?|with|remastered|remaster|version|explicit|live|bonus|instrumental)\b.*', '', text)
    # Hapus semua karakter non-alfanumerik (termasuk spasi dan tanda kutip)
    text = re.sub(r'[^a-zA-Z0-9]', '', text)
    return text.lower()

def is_valid_match(t1, t2, a1=None, a2=None):
    ct1 = clean_string(t1)
    ct2 = clean_string(t2)
    
    if not ct1 or not ct2: 
        return False
        
    # Jika salah satu judul sangat pendek (< 3 karakter), harus sama persis (mencegah false positive)
    if len(ct1) < 3 or len(ct2) < 3:
        title_match = (ct1 == ct2)
    else:
        # Cek apakah judul 1 memuat judul 2 atau sebaliknya
        title_match = (ct1 in ct2 or ct2 in ct1)
        
    if not title_match: 
        return False
        
    if a1 and a2:
        ca1 = clean_string(a1)
        ca2 = clean_string(a2)
        if ca1 and ca2:
            # Cek kecocokan artis (cukup salah satu memuat yang lain untuk mengatasi multi-artist)
            return (ca1 in ca2 or ca2 in ca1)
            
    return True
# =======================================================


class MusixmatchAPI:
    def __init__(self):
        self.API_URL = 'https://apic-desktop.musixmatch.com/ws/1.1/'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Musixmatch/0.19.4 Chrome/58.0.3029.110 Electron/1.7.6 Safari/537.36'
        }
        self.cookies = {'AWSELB': '0', 'AWSELBCORS': '0'}
        self.token = None

    def sign_request(self, method, params, timestamp):
        to_hash = self.API_URL + method + '?' + urlencode(params)
        key = ("IEJ5E8XFaH" "QvIQNfs7IC").encode()
        signature = hmac.digest(key, (to_hash + timestamp).encode(), digest='SHA1')
        return base64.urlsafe_b64encode(signature).decode()

    async def get_token(self, session):
        currenttime = datetime.now()
        timestamp = currenttime.strftime('%Y-%m-%dT%H:%M:%SZ')
        signature_timestamp = currenttime.strftime('%Y%m%d')
        method = 'token.get'
        params = {
            'format': 'json',
            'guid': str(uuid.uuid4()),
            'timestamp': timestamp,
            'build_number': '2017091202',
            'lang': 'en-GB',
            'app_id': 'web-desktop-app-v1.0'
        }
        params['signature'] = self.sign_request(method, params, signature_timestamp)
        params['signature_protocol'] = 'sha1'

        try:
            async with MX_LIMITER:
                async with session.get(self.API_URL + method, params=params, headers=self.headers, cookies=self.cookies, timeout=15) as r:
                    data = await r.json(content_type=None)
                    if data.get('message', {}).get('header', {}).get('status_code') == 200:
                        token = data['message']['body']['user_token']
                        if token != 'UpgradeOnlyUpgradeOnlyUpgradeOnlyUpgradeOnly':
                            self.token = token
                            return self.token
        except Exception:
            pass
        return None

    async def get_lyrics(self, title, artist, album, duration=None):
        async with aiohttp.ClientSession(cookies=self.cookies) as session:
            if not self.token:
                await self.get_token(session)

            track_id = None
            commontrack_id = None

            # 1. Gunakan 'matcher.track.get' (Jauh lebih akurat dari track.search)
            try:
                method = 'matcher.track.get'
                params = {
                    'format': 'json',
                    'q_track': title,
                    'q_artist': artist,
                    'usertoken': self.token,
                    'app_id': 'web-desktop-app-v1.0'
                }
                if album: params['q_album'] = album
                
                async with MX_LIMITER:
                    async with session.get(self.API_URL + method, params=params, headers=self.headers, timeout=15) as r:
                        data = await r.json(content_type=None)
                        if data.get('message', {}).get('header', {}).get('status_code') == 200:
                            t = data['message']['body'].get('track', {})
                            res_title = t.get('track_name', '')
                            res_artist = t.get('artist_name', '')
                            
                            if is_valid_match(title, res_title, artist, res_artist):
                                track_id = t.get('track_id')
                                commontrack_id = t.get('commontrack_id')
            except Exception: pass

            # 2. Fallback ke 'track.search' jika matcher.track.get gagal
            if not track_id:
                try:
                    method = 'track.search'
                    params = {
                        'format': 'json',
                        'q_track': title,
                        'q_artist': artist,
                        's_track_rating': 'desc',
                        'usertoken': self.token,
                        'app_id': 'web-desktop-app-v1.0'
                    }
                    async with MX_LIMITER:
                        async with session.get(self.API_URL + method, params=params, headers=self.headers, timeout=15) as r:
                            data = await r.json(content_type=None)
                            track_list = data.get('message', {}).get('body', {}).get('track_list', [])
                            
                            for t_data in track_list:
                                t = t_data.get('track', {})
                                res_title = t.get('track_name', '')
                                res_artist = t.get('artist_name', '')
                                
                                if is_valid_match(title, res_title, artist, res_artist):
                                    track_id = t.get('track_id')
                                    commontrack_id = t.get('commontrack_id')
                                    break
                except Exception: pass

            # Berhenti jika lagu benar-benar tidak ditemukan (Instrumental/Intro)
            if not track_id:
                return None, None

            plain = None
            synced = None
            
            # 3. Ambil Plain Lyrics menggunakan Exact ID
            try:
                params_plain = {
                    'format': 'json',
                    'track_id': track_id,
                    'usertoken': self.token,
                    'app_id': 'web-desktop-app-v1.0'
                }
                async with MX_LIMITER:
                    async with session.get(self.API_URL + 'track.lyrics.get', params=params_plain, headers=self.headers, timeout=15) as r:
                        data = await r.json(content_type=None)
                        if data.get('message', {}).get('header', {}).get('status_code') == 200:
                            plain = data['message']['body']['lyrics']['lyrics_body']
            except Exception: pass

            # 4. Ambil Synced Lyrics (LRC) menggunakan Exact ID
            if commontrack_id:
                try:
                    params_sync = {
                        'format': 'json',
                        'commontrack_id': commontrack_id,
                        'usertoken': self.token,
                        'app_id': 'web-desktop-app-v1.0'
                    }
                    async with MX_LIMITER:
                        async with session.get(self.API_URL + 'track.subtitle.get', params=params_sync, headers=self.headers, timeout=15) as r:
                            data = await r.json(content_type=None)
                            if data.get('message', {}).get('header', {}).get('status_code') == 200:
                                sub_list = data['message']['body'].get('subtitle_list', [])
                                if sub_list:
                                    synced = sub_list[0]['subtitle']['subtitle_body']
                except Exception: pass
            
            return plain, synced


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

    async def get_lyrics(self, title, artist, album, duration):
        async with aiohttp.ClientSession() as session:
            track_id = None
            
            # 1. Search Track
            search_query = f"{artist} {title}"
            try:
                async with GENIUS_LIMITER:
                    async with session.get(f'{self.API_URL}search', params={'q': search_query}, headers=self.headers, timeout=15) as r:
                        if r.status == 200:
                            data = await r.json(content_type=None)
                            hits = data.get('response', {}).get('hits', [])
                            
                            if hits:
                                for hit in hits:
                                    result = hit.get('result', {})
                                    res_title = result.get('title', '')
                                    res_title_feat = result.get('title_with_featured', '')
                                    res_artist = result.get('artist_names', '')
                                    
                                    # Pengecekan cerdas
                                    if is_valid_match(title, res_title, artist, res_artist) or \
                                       is_valid_match(title, res_title_feat, artist, res_artist):
                                        track_id = result.get('id')
                                        break
            except Exception as e:
                LOGGER.warning(f"Genius Search Error: {e}")
            
            if not track_id:
                return None, None
                
            # 2. Get Lyrics
            try:
                async with GENIUS_LIMITER:
                    async with session.get(f'{self.API_URL}songs/{track_id}', params={'text_format': 'plain'}, headers=self.headers, timeout=15) as r:
                        if r.status == 200:
                            data = await r.json(content_type=None)
                            song_data = data.get('response', {}).get('song', {})
                            plain_lyrics = song_data.get('lyrics', {}).get('plain')
                            return plain_lyrics, None 
            except Exception as e:
                LOGGER.warning(f"Genius Lyrics Error: {e}")
            
            return None, None
