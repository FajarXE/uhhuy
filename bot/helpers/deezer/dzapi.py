# [GANTI FILE: bot/helpers/deezer/dzapi.py]

import re
import os
import aiohttp
import aiolimiter
import asyncio

from random import randint
from time import time
from math import ceil
from urllib.parse import urlparse
from Cryptodome.Hash import MD5
from Cryptodome.Cipher import Blowfish

from config import Config 
from bot.logger import LOGGER

# --- GLOBAL RATE LIMITER UNTUK SEMUA AKUN DEEZER ---
GLOBAL_DZ_LIMITER = aiolimiter.AsyncLimiter(30, 60)
# ---------------------------------------------------

def get_deezer_speed() -> int:
    """Kecepatan unduh Deezer sudah dihitung otomatis melalui Aria2c global stat."""
    return 0

class APIError(Exception):
    def __init__(self, type, msg, payload):
        self.type = type
        self.msg = msg
        self.payload = payload
    def __str__(self):
        return ', '.join((str(self.type), str(self.msg), str(self.payload)))

class DeezerAPI:
    def __init__(self):
        self.gw_light_url = 'https://www.deezer.com/ajax/gw-light.php'
        self.api_token = ''
        self.client_id = '447462'
        self.client_secret = 'a83bf7f38ad2f137e444727cfc3775cf'
        self.quality = 'MP3_128'
        self.session = None 
        self.user = None
        self.country = None
        self.license_token = None
        self.renew_timestamp = ceil(time())
        self.language = 'en'
        self.available_formats = ['MP3_128']
        self._auth_lock = asyncio.Lock()
        
        if not Config.DEEZER_BF_SECRET:
            LOGGER.warning("DEEZER_BF_SECRET tidak diatur di Config!")
            self.bf_secret = b'' 
        else:
            self.bf_secret = Config.DEEZER_BF_SECRET.encode('ascii')

    def _ensure_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(limit=50, keepalive_timeout=30, enable_cleanup_closed=True)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'accept': '*/*',
                    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
                    'content-type': 'text/plain;charset=UTF-8',
                    'origin': 'https://www.deezer.com',
                    'sec-fetch-site': 'same-origin',
                    'sec-fetch-mode': 'same-origin',
                    'sec-fetch-dest': 'empty',
                    'referer': 'https://www.deezer.com/',
                    'accept-language': 'en-US,en;q=0.9',
                }
            )

    async def _api_call(self, method, payload=None, _retry=False):
        if payload is None:
            payload = {}
        self._ensure_session()
            
        api_token = self.api_token if method not in ('deezer.getUserData', 'user.getArl') else ''
        params = {
            'method': method,
            'input': 3,
            'api_version': 1.0,
            'api_token': api_token,
            'cid': randint(0, 1_000_000_000),
        }

        async with GLOBAL_DZ_LIMITER:
            async with self.session.post(self.gw_light_url, params=params, json=payload) as r:
                resp = await r.json(content_type=None)

        if resp.get('error'):
            err_type = list(resp['error'].keys())[0]
            err_msg = list(resp['error'].values())[0]
            if err_type == 'VALID_TOKEN_REQUIRED' and not _retry:
                LOGGER.debug("Deezer: Refreshing User data (VALID_TOKEN_REQUIRED)")
                try:
                    async with self._auth_lock:
                        await asyncio.sleep(0.5)
                        await self._api_call('deezer.getUserData', _retry=True)
                    return await self._api_call(method, payload, _retry=True)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    LOGGER.error(f"Deezer: Refreshing User data failed: {e}")
            raise APIError(err_type, err_msg, resp.get('payload'))

        if method == 'deezer.getUserData':
            results = resp['results']
            self.api_token = results['checkForm']
            self.country = results['COUNTRY']
            self.license_token = results['USER']['OPTIONS']['license_token']
            self.renew_timestamp = ceil(time())
            self.language = results['USER']['SETTING']['global'].get('language', 'en')
            
            self.available_formats = ['MP3_128']
            format_dict = {'web_hq': 'MP3_320', 'web_lossless': 'FLAC'}
            for k, v in format_dict.items():
                if results['USER']['OPTIONS'].get(k):
                    self.available_formats.append(v)
            
            if 'FLAC' in self.available_formats:
                self.available_formats.append('FLAC_24')
            
            self.user = results 
        
        return resp['results']

    async def login(self, arl: str = None, email: str = None, password: str = None):
        try:
            if arl:
                await self.login_via_arl(arl)
            elif email and password: 
                await self.login_via_email(email, password)
            else:
                raise Exception("Tidak ada kredensial Deezer (ARL atau Email/Password) yang disediakan.")
                
        except Exception as e:
            LOGGER.error(f"DEEZER : {e}")
            await self.close()
            raise e 

        LOGGER.info(f"Deezer: Berhasil login untuk user ID {self.user['USER']['USER_ID']}")
        return True

    async def login_via_email(self, email, password):
        await self._api_call('deezer.getUserData') 
        
        password_md5 = MD5.new(password.encode()).hexdigest()

        params = {
            'app_id': self.client_id,
            'login': email,
            'password': password_md5,
            'hash': MD5.new((self.client_id + email + password_md5 + self.client_secret).encode()).hexdigest(),
        }

        async with GLOBAL_DZ_LIMITER:
            async with self.session.get('https://connect.deezer.com/oauth/user_auth.php', params=params) as r:
                json_data = await r.json(content_type=None)

        if 'error' in json_data:
            raise Exception(f'Error saat mendapatkan access token: {json_data["error"]}')

        arl = await self._api_call('user.getArl')
        return arl, await self.login_via_arl(arl)

    async def login_via_arl(self, arl):
        self._ensure_session()
        if not self.api_token:
            await self._api_call('deezer.getUserData') 
            
        self.session.cookie_jar.update_cookies({'arl': arl})
        user_data = await self._api_call('deezer.getUserData')
        if not user_data['USER']['USER_ID']:
            raise Exception('Invalid arl')
        self.user = user_data
        return user_data

    async def custom_url_parse(self, link) -> tuple[str, str]:
        self._ensure_session()
        url = urlparse(link)
        if url.hostname and 'link.deezer.com' in url.hostname:
            async with GLOBAL_DZ_LIMITER:
                async with self.session.get(link, allow_redirects=True) as r:
                    if r.status != 200:
                        raise Exception(f'DEEZER : Invalid URL: {link}')
                    url = r.real_url

        path_str = str(url.path)
        path_match = re.search(r'/(track|album|artist|playlist)/(\d+)', path_str)
        if not path_match:
            raise Exception(f'DEEZER : Invalid URL: {link}')
        return path_match.group(1), path_match.group(2)

    async def get_track(self, id):
        return await self._api_call('deezer.pageTrack', {'sng_id': id})

    async def get_track_data(self, id):
        payload = {
            'sng_id': id,
            'array_default': ['CONTRIBUTORS', 'ALB_TITLE', 'ALB_LABEL', 'ART_NAME']
        }
        return await self._api_call('song.getData', payload)

    async def get_track_url(self, id, track_token, track_token_expiry, format):
        if time() - self.renew_timestamp >= 3600:
            async with self._auth_lock:
                if time() - self.renew_timestamp >= 3600:
                    LOGGER.debug("Deezer: License token expired - trying to refresh User data")
                    await self._api_call('deezer.getUserData')

        if not track_token or (track_token_expiry and time() - track_token_expiry >= 0):
            LOGGER.debug("Deezer: Track token expired or missing - refreshing token")
            fresh_data = await self._api_call('song.getData', {'sng_id': id, 'array_default': ['TRACK_TOKEN']})
            track_token = fresh_data.get('TRACK_TOKEN')

        if not track_token:
            raise Exception("Deezer: Track token kosong (Not available in country).")

        # Susun rantai prioritas format sesuai pilihan kualitas (FLAC_24 tetap di urutan pertama)
        if format == 'FLAC_24':
            fallback_chain = ['FLAC_24', 'FLAC', 'MP3_320', 'MP3_128']
        elif format == 'FLAC':
            fallback_chain = ['FLAC', 'MP3_320', 'MP3_128']
        elif format == 'MP3_320':
            fallback_chain = ['MP3_320', 'MP3_128']
        else:
            fallback_chain = ['MP3_128']

        formats_payload = [{'cipher': 'BF_CBC_STRIPE', 'format': fmt} for fmt in fallback_chain]
        json_payload = { 
            'license_token': self.license_token,
            'media': [{'type': 'FULL', 'formats': formats_payload}],
            'track_tokens': [track_token]
        }

        async with GLOBAL_DZ_LIMITER:
            async with self.session.post('https://media.deezer.com/v1/get_url', json=json_payload) as r:
                resp = await r.json(content_type=None)

        data_list = resp.get('data') if isinstance(resp, dict) else None
        if not data_list:
            raise Exception(f"Deezer: Media URL response kosong ({resp}).")

        first_data = data_list[0]
        if 'errors' in first_data and not first_data.get('media'):
            err_detail = first_data['errors'][0].get('message', 'Unknown media error')
            raise Exception(f"Deezer: Track not available ({err_detail})")

        media_list = first_data.get('media')
        if not media_list or not media_list[0].get('sources'):
            raise Exception("Deezer: Track not available (Sources kosong / Region lock).")

        return media_list[0]['sources'][0]['url']

    async def get_album(self, id):
        try:
            res = await self._api_call('album.getData', {'alb_id': id, 'lang': self.language})
        except APIError as e:
            try:
                LOGGER.warning(f"Deezer: album.getData gagal, mencoba fallback ke deezer.pageAlbum. Error: {e}")
                res = await self._api_call('deezer.pageAlbum', {'alb_id': id, 'lang': self.language})
                if 'DATA' in res:
                    res = res['DATA'] 
            except APIError as e_fallback:
                if e_fallback.payload and e_fallback.payload.get('FALLBACK') and e_fallback.payload['FALLBACK'].get('ALB_ID'):
                    res = await self._api_call('album.getData', {'alb_id': e_fallback.payload['FALLBACK']['ALB_ID'], 'lang': self.language})
                else:
                    raise e_fallback
        return res 

    async def get_album_tracks(self, id):
        try:
            res = await self._api_call('deezer.pageAlbum', {'alb_id': id, 'lang': self.language})
        except APIError as e:
            if e.payload and e.payload.get('FALLBACK') and e.payload['FALLBACK'].get('ALB_ID'):
                LOGGER.warning(f"Deezer: get_album_tracks gagal, mencoba fallback ID {e.payload['FALLBACK']['ALB_ID']}")
                res = await self._api_call('deezer.pageAlbum', {'alb_id': e.payload['FALLBACK']['ALB_ID'], 'lang': self.language})
            else:
                raise e
        return res 
    
    async def get_artist(self, id):
        return await self._api_call('artist.getData', {'art_id': id})
    
    async def get_artist_album_ids(self, id, start, nb, credited_albums):
        payload = {
            'art_id': id, 'start': start, 'nb': nb,
            'filter_role_id': [0, 5] if credited_albums else [0],
            'nb_songs': 0, 'discography_mode': 'all' if credited_albums else None,
            'array_default': ['ALB_ID']
        }
        resp = await self._api_call('album.getDiscography', payload)
        return [a['ALB_ID'] for a in resp.get('data', [])]

    async def get_playlist(self, id, nb, start):
        return await self._api_call('deezer.pagePlaylist', {
            'nb': nb, 'start': start, 'playlist_id': id,
            'lang': self.language, 'tab': 0, 'tags': True, 'header': True
        })

    def _get_blowfish_key(self, track_id):
        md5_id = MD5.new(str(track_id).encode()).hexdigest().encode('ascii')
        key = bytes([md5_id[i] ^ md5_id[i + 16] ^ self.bf_secret[i] for i in range(16)])
        return key
    
    async def dl_track(self, id, url, path, details=None):
        bf_key = self._get_blowfish_key(id)
        enc_path = path + ".enc"
        
        from bot.helpers.utils import download_file
        
        try:
            err = await download_file(url, enc_path, details=details)
        except asyncio.CancelledError:
            for p in (enc_path, f"{enc_path}.aria2", path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            raise
        
        if err is not None:
            if os.path.exists(enc_path):
                try:
                    os.remove(enc_path)
                except OSError:
                    pass
            return err 
            
        try:
            await asyncio.to_thread(self._decrypt_file_sync, bf_key, enc_path, path)
            if os.path.exists(enc_path):
                try:
                    os.remove(enc_path)
                except OSError:
                    pass
            return None 
        except asyncio.CancelledError:
            for p in (enc_path, path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            raise
        except Exception as e:
            LOGGER.error(f"Deezer Decryption error: {e}")
            for p in (enc_path, path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            return str(e)

    @staticmethod
    def _decrypt_file_sync(bf_key, enc_path, path):
        encrypt_chunk_size = 3 * 2048
        iv = b"\x00\x01\x02\x03\x04\x05\x06\x07"
        
        with open(enc_path, "rb") as enc_file, open(path, "wb") as audio:
            while True:
                chunk = enc_file.read(encrypt_chunk_size)
                if not chunk:
                    break
                if len(chunk) >= 2048:
                    cipher = Blowfish.new(bf_key, Blowfish.MODE_CBC, iv)
                    decrypted_chunk = cipher.decrypt(chunk[:2048]) + chunk[2048:]
                else:
                    decrypted_chunk = chunk
                audio.write(decrypted_chunk)

    @staticmethod
    def _decrypt_chunk(key, data):
        return Blowfish.new(key, Blowfish.MODE_CBC, b"\x00\x01\x02\x03\x04\x05\x06\x07").decrypt(data)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            user_id = self.user['USER']['USER_ID'] if self.user and self.user.get('USER') else 'N/A'
            LOGGER.debug(f"DeezerAPI (User {user_id}): Sesi aiohttp ditutup.")
