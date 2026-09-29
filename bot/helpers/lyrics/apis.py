# [GANTI SELURUH FILE: bot/helpers/lyrics/apis.py]

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
                    try:
                        data = await r.json(content_type=None)
                        if data['message']['header']['status_code'] == 200:
                            token = data['message']['body']['user_token']
                            if token != 'UpgradeOnlyUpgradeOnlyUpgradeOnlyUpgradeOnly':
                                self.token = token
                                return self.token
                    except:
                        LOGGER.warning("Musixmatch: Gagal decode JSON saat get_token")
        except Exception as e:
            LOGGER.error(f"Musixmatch Token Error: {e}")
        return None

    async def get_lyrics(self, title, artist, album, duration=None):
        async with aiohttp.ClientSession(cookies=self.cookies) as session:
            if not self.token:
                await self.get_token(session)

            method = 'track.search'
            params = {
                'format': 'json',
                'q_track': title,
                'q_artist': artist,
                'quorum_factor': 1,
                'usertoken': self.token,
                'app_id': 'web-desktop-app-v1.0'
            }
            
            track_id = None
            try:
                async with MX_LIMITER:
                    async with session.get(self.API_URL + method, params=params, headers=self.headers, timeout=15) as r:
                        data = await r.json(content_type=None)
                        track_list = data['message']['body']['track_list']
                        if track_list:
                            track_id = track_list[0]['track']['track_id']
            except:
                pass

            if not track_id:
                return None, None

            plain = None
            synced = None
            
            method = 'macro.subtitles.get'
            params = {
                'format': 'json',
                'q_track': title,
                'q_artist': artist,
                'usertoken': self.token,
                'app_id': 'web-desktop-app-v1.0',
                'optional_calls': 'track.subtitles.get,track.lyrics.get'
            }
            
            try:
                async with MX_LIMITER:
                    async with session.get(self.API_URL + method, params=params, headers=self.headers, timeout=15) as r:
                        data = await r.json(content_type=None)
                        body = data['message']['body']['macro_calls']
                        
                        if body.get('track.lyrics.get', {}).get('message', {}).get('header', {}).get('status_code') == 200:
                            plain = body['track.lyrics.get']['message']['body']['lyrics']['lyrics_body']

                        if body.get('track.subtitles.get', {}).get('message', {}).get('header', {}).get('status_code') == 200:
                            try:
                                sub_list = body['track.subtitles.get']['message']['body']['subtitle_list']
                                if sub_list:
                                    synced = sub_list[0]['subtitle']['subtitle_body']
                            except: pass
            except:
                pass
            
            return plain, synced


class LRCLibAPI:
    def __init__(self):
        self.base_url = 'https://lrclib.net/api'
        self.headers = {'User-Agent': 'BotMusic/1.0'}

    async def _fetch_with_retry(self, session, url, params):
        """Fungsi helper untuk menangani Retry-After (429/503) secara asinkron."""
        for attempt in range(3): # Maksimal 3 percobaan
            try:
                async with LRC_LIMITER:
                    async with session.get(url, params=params, headers=self.headers, timeout=15) as r:
                        if r.status == 200:
                            return await r.json(content_type=None)
                        elif r.status in (429, 503):
                            # Ambil header Retry-After, default ke 5 detik jika tidak ada
                            retry_after = int(r.headers.get('Retry-After', 5))
                            LOGGER.warning(f"LRCLib Rate Limit {r.status}. Retrying in {retry_after}s...")
                            await asyncio.sleep(retry_after)
                            continue
                        elif r.status == 404:
                            return None # Tidak ditemukan
                        else:
                            return None
            except Exception as e:
                LOGGER.debug(f"LRCLib Fetch Error: {e}")
                return None
        return None

    async def get_lyrics(self, title, artist, album, duration):
        async with aiohttp.ClientSession() as session:
            params = {
                'track_name': title,
                'artist_name': artist,
                'album_name': album,
                'duration': duration
            }
            
            # --- Try Cached (/get) ---
            data = await self._fetch_with_retry(session, f'{self.base_url}/get', params)
            if data:
                return data.get('plainLyrics'), data.get('syncedLyrics')
            
            # --- Try Search (/search) ---
            params_search = {'q': f"{title} {artist}"}
            data = await self._fetch_with_retry(session, f'{self.base_url}/search', params_search)
            if data and isinstance(data, list) and len(data) > 0:
                return data[0].get('plainLyrics'), data[0].get('syncedLyrics')
            
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
                            
                            for hit in hits:
                                result = hit.get('result', {})
                                res_title = result.get('title', '').lower()
                                res_title_feat = result.get('title_with_featured', '').lower()
                                res_artist = result.get('artist_names', '').lower()
                                
                                if (title.lower() in res_title or title.lower() in res_title_feat) and \
                                   (artist.lower() in res_artist):
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
