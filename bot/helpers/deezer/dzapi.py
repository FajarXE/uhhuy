# [GANTI FILE: bot/helpers/deezer/dzapi.py]

import re
import os
import aiohttp
import aiofiles
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

class APIError(Exception):
    def __init__(self, type, msg, payload):
        self.type = type
        self.msg = msg
        self.payload = payload
    def __str__(self):
        return ', '.join((self.type, self.msg, str(self.payload)))

class DeezerAPI:
    def __init__(self):
        self.gw_light_url = 'https://www.deezer.com/ajax/gw-light.php'
        self.api_token = ''
        self.client_id = '447462'
        self.client_secret = 'a83bf7f38ad2f137e444727cfc3775cf'
        self.ratelimit = aiolimiter.AsyncLimiter(30, 60)
        self.quality = 'MP3_128'
        self.session = None 
        self.user = None
        self.country = None
        self.license_token = None
        self.renew_timestamp = ceil(time())
        self.language = 'en'
        self.available_formats = ['MP3_128']
        
        if not Config.DEEZER_BF_SECRET:
            LOGGER.warning("DEEZER_BF_SECRET tidak diatur di Config!")
            self.bf_secret = b'' 
        else:
            self.bf_secret = Config.DEEZER_BF_SECRET.encode('ascii')

    async def _api_call(self, method, payload={}):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    'accept': '*/*',
                    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
                    'content-type': 'text/plain;charset=UTF-8',
                    'origin': 'https://www.deezer.com',
                    'sec-fetch-site': 'same-origin',
                    'sec-fetch-mode': 'same-origin',
                    'sec-fetch-dest': 'empty',
                    'referer': 'https://www.deezer.com/',
                    'accept-language': 'en-US,en;q=0.9',
                }
            )
            
        api_token = self.api_token if method not in ('deezer.getUserData', 'user.getArl') else ''
        params = {
            'method': method,
            'input': 3,
            'api_version': 1.0,
            'api_token': api_token,
            'cid': randint(0, 1_000_000_000),
        }

        async with self.ratelimit:
            async with self.session.post(self.gw_light_url, params=params, json=payload) as r:
                resp = await r.json()

        if resp['error']:
            type = list(resp['error'].keys())[0]
            msg = list(resp['error'].values())[0]
            if type=='VALID_TOKEN_REQUIRED':
                LOGGER.debug("Deezer: Refreshing User data")
                try:
                    await asyncio.sleep(1)
                    await self._api_call('deezer.getUserData')
                    return await self._api_call(method, payload)
                except:
                    LOGGER.error("Deezer: Refreshing User data failed")
            raise APIError(type, msg, resp['payload'])

        if method == 'deezer.getUserData':
            self.api_token = resp['results']['checkForm']
            self.country = resp['results']['COUNTRY']
            self.license_token = resp['results']['USER']['OPTIONS']['license_token']
            self.renew_timestamp = ceil(time())
            self.language = resp['results']['USER']['SETTING']['global']['language']
            
            self.available_formats = ['MP3_128']
            format_dict = {'web_hq': 'MP3_320', 'web_lossless': 'FLAC'}
            for k, v in format_dict.items():
                if resp['results']['USER']['OPTIONS'][k]:
                    self.available_formats.append(v)
            self.user = resp['results'] 
        
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
            if self.session:
                await self.session.close()
            raise e 

        LOGGER.info(f"Deezer: Berhasil login untuk user ID {self.user['USER']['USER_ID']}")
        return True

    async def login_via_email(self, email, password):
        async with self.ratelimit:
            await self._api_call('deezer.getUserData') 
        
        password = MD5.new(password.encode()).hexdigest()

        params = {
            'app_id': self.client_id,
            'login': email,
            'password': password,
            'hash': MD5.new((self.client_id + email + password + self.client_secret).encode()).hexdigest(),
        }

        async with self.ratelimit:
            async with self.session.get('https://connect.deezer.com/oauth/user_auth.php', params=params) as r:
                json_data = await r.json()

        if 'error' in json_data:
            raise Exception(f'Error saat mendapatkan access token: {json_data["error"]}')

        arl = await self._api_call('user.getArl')

        return arl, await self.login_via_arl(arl)

    async def login_via_arl(self, arl):
        cookie = {'arl':arl}
        if not self.session:
            await self._api_call('deezer.getUserData') 
            
        self.session.cookie_jar.update_cookies(cookie)
        user_data = await self._api_call('deezer.getUserData')
        if not user_data['USER']['USER_ID']:
            raise Exception('Invalid arl')
        self.user = user_data
        return user_data

    async def custom_url_parse(self, link) -> (str, int):
        url = urlparse(link)
        if url.hostname == 'link.deezer.com':
            async with self.ratelimit:
                if not self.session:
                    raise Exception("Sesi Deezer belum diinisialisasi sebelum parsing URL")
                
                async with self.session.get(link, allow_redirects=True) as r:
                    if r.status != 200:
                        raise Exception(f'DEEZER : Invalid URL: {link}')
                    url = r.real_url

        path_match = re.match(r'^\/(?:[a-z]{2}\/)?(track|album|artist|playlist)\/(\d+)\/?$', url.path)
        if not path_match:
            raise Exception(f'DEEZER : Invalid URL: {link}')
        return path_match.group(1), path_match.group(2)

    async def get_track(self, id):
        res = await self._api_call('deezer.pageTrack', {'sng_id': id})
        return res

    async def get_track_data(self, id):
        # Memastikan kita meminta CONTRIBUTORS dan data ALBUM untuk label
        payload = {
            'sng_id': id,
            'array_default': ['CONTRIBUTORS', 'ALB_TITLE', 'ALB_LABEL', 'ART_NAME']
        }
        res = await self._api_call('song.getData', payload)
        return res

    async def get_track_url(self, id, track_token, track_token_expiry, format):
        if time() - self.renew_timestamp >= 3600:
            LOGGER.debug("Deezer: License token expired - trying to refresh User data")
            await self._api_call('deezer.getUserData')
        if time() - track_token_expiry >= 0:
            LOGGER.debug("Deezer: Track token expired - trying to refresh token")
            track_token = await self._api_call('song.getData', {'sng_id': id, 'array_default': ['TRACK_TOKEN']})['TRACK_TOKEN']
        json_payload = { 
            'license_token': self.license_token,
            'media': [{'type': 'FULL','formats': [{'cipher': 'BF_CBC_STRIPE', 'format': format}]}],
            'track_tokens': [track_token]
        }
        async with self.ratelimit:
            async with self.session.post('https://media.deezer.com/v1/get_url', json=json_payload) as r:
                resp = await r.json()
        return resp['data'][0]['media'][0]['sources'][0]['url']

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
            'filter_role_id': [0,5] if credited_albums else [0],
            'nb_songs': 0, 'discography_mode': 'all' if credited_albums else None,
            'array_default': ['ALB_ID']
        }
        resp = await self._api_call('album.getDiscography', payload)
        return [a['ALB_ID'] for a in resp['data']]

    async def get_playlist(self, id, nb, start):
        res = await self._api_call('deezer.pagePlaylist', {'nb': nb, 'start': start, 'playlist_id': id, 'lang': self.language, 'tab': 0, 'tags': True, 'header': True})
        return res

    def _get_blowfish_key(self, track_id):
        md5_id = MD5.new(str(track_id).encode()).hexdigest().encode('ascii')
        key = bytes([md5_id[i] ^ md5_id[i + 16] ^ self.bf_secret[i] for i in range(16)])
        return key
    
    async def dl_track(self, id, url, path, details=None):
        bf_key = self._get_blowfish_key(id)
        enc_path = path + ".enc"
        
        from bot.helpers.utils import download_file
        import os
        import aiofiles
        import asyncio
        import random
        
        # [FIX] Beri sedikit jeda acak (0-1 detik) agar panggilan ke Aria2 tidak tabrakan di memori
        await asyncio.sleep(random.uniform(0.1, 1.2))
        
        # 1. Biarkan Aria2 yang ngebut mengunduh file
        err = await download_file(url, enc_path, details=details)
        
        # Jika dibatalkan (/cancel) atau gagal, bersihkan!
        if err is not None:
            if os.path.exists(enc_path):
                try: os.remove(enc_path)
                except: pass
            return err 
            
        # 2. Setelah Aria2 sukses, bongkar gembok (Dekripsi) secara lokal
        try:
            encrypt_chunk_size = 3 * 2048
            os.makedirs(os.path.dirname(path), exist_ok=True)
            async with aiofiles.open(enc_path, "rb") as enc_file:
                async with aiofiles.open(path, "wb") as audio:
                    while True:
                        chunk = await enc_file.read(encrypt_chunk_size)
                        if not chunk:
                            break
                        if len(chunk) >= 2048:
                            decrypted_chunk = (self._decrypt_chunk(bf_key, chunk[:2048]) + chunk[2048:])
                        else:
                            decrypted_chunk = chunk
                        await audio.write(decrypted_chunk)
                        
            # Bersihkan file .enc mentah setelah sukses menjadi FLAC/MP3
            if os.path.exists(enc_path):
                os.remove(enc_path)
            return None 
            
        except Exception as e:
            from bot.logger import LOGGER
            LOGGER.error(f"Deezer Decryption error: {e}")
            if os.path.exists(enc_path):
                try: os.remove(enc_path)
                except: pass
            return str(e)

    @staticmethod
    def _decrypt_chunk(key, data):
        return Blowfish.new(key, Blowfish.MODE_CBC, b"\x00\x01\x02\x03\x04\x05\x06\x07").decrypt(data)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            user_id = self.user['USER']['USER_ID'] if self.user and self.user.get('USER') else 'N/A'
            LOGGER.debug(f"DeezerAPI (User {user_id}): Sesi aiohttp ditutup.")
